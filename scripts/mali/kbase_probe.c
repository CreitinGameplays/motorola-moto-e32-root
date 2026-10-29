#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

struct kbase_ioctl_version_check { uint16_t major; uint16_t minor; };
struct kbase_ioctl_set_flags { uint32_t create_flags; };
struct kbase_ioctl_get_ddk_version { uint64_t version_buffer; uint32_t size; uint32_t padding; };
struct kbase_ioctl_job_submit { uint64_t addr; uint32_t nr_atoms; uint32_t stride; };

#define KBASE_IOCTL_TYPE 0x80
#define KBASE_IOCTL_VERSION_CHECK _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)
#define KBASE_IOCTL_SET_FLAGS _IOW(KBASE_IOCTL_TYPE, 1, struct kbase_ioctl_set_flags)
#define KBASE_IOCTL_JOB_SUBMIT _IOW(KBASE_IOCTL_TYPE, 2, struct kbase_ioctl_job_submit)
#define KBASE_IOCTL_GET_DDK_VERSION _IOW(KBASE_IOCTL_TYPE, 13, struct kbase_ioctl_get_ddk_version)
#define BASE_MEM_MAP_TRACKING_HANDLE (3ull << 12)

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    int fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { printf("open: %s\n", strerror(errno)); return 1; }
    struct kbase_ioctl_version_check vc = { 999, 999 };
    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &vc) < 0) { printf("vc: %s\n", strerror(errno)); return 1; }
    printf("[+] api %u.%u\n", vc.major, vc.minor);
    struct kbase_ioctl_set_flags sf = { 0 };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { printf("sf: %s\n", strerror(errno)); return 1; }
    void *t = mmap(NULL, 0x1000, 0, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);
    printf("[%c] tracking %p\n", t == MAP_FAILED ? '-' : '+', t);

    char ver[256];
    memset(ver, 0, sizeof(ver));
    struct kbase_ioctl_get_ddk_version dv = { (uint64_t)ver, sizeof(ver), 0 };
    int r = ioctl(fd, KBASE_IOCTL_GET_DDK_VERSION, &dv);
    printf("[%c] ddk ioctl ret=%d errno=%s version='%s'\n", r >= 0 ? '+' : '-', r,
           r >= 0 ? "ok" : strerror(errno), ver);

    unsigned char atom[128];
    memset(atom, 0, sizeof(atom));
    for (unsigned stride = 32; stride <= 96; stride += 4) {
        struct kbase_ioctl_job_submit js = { (uint64_t)atom, 1, stride };
        errno = 0;
        int rr = ioctl(fd, KBASE_IOCTL_JOB_SUBMIT, &js);
        if (rr == 0 || errno != EINVAL)
            printf("[?] stride %u ret=%d errno=%s\n", stride, rr, strerror(errno));
        if (rr == 0)
            printf("[+] stride %u accepted\n", stride);
    }
    printf("[*] done\n");
    return 0;
}
