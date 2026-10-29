#include <stdio.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <string.h>

#define KBASE_IOCTL_TYPE 0x80

struct kbase_ioctl_version_check {
    uint16_t major;
    uint16_t minor;
};

#define KBASE_IOCTL_VERSION_CHECK _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)

int main(void) {
    int fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "open /dev/mali0 failed: %s\n", strerror(errno));
        return 1;
    }
    struct kbase_ioctl_version_check v;
    memset(&v, 0, sizeof(v));
    if (ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &v) < 0) {
        fprintf(stderr, "VERSION_CHECK failed: %s\n", strerror(errno));
        return 2;
    }
    printf("kbase version: r%up%u\n", v.major, v.minor);
    printf("ioctl code: 0x%lx\n", (unsigned long)KBASE_IOCTL_VERSION_CHECK);
    close(fd);
    return 0;
}
