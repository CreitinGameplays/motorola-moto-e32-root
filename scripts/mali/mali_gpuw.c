#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

struct kbase_ioctl_version_check { uint16_t major; uint16_t minor; };
struct kbase_ioctl_set_flags { uint32_t create_flags; };
union kbase_ioctl_mem_alloc {
    struct { uint64_t va_pages; uint64_t commit_pages; uint64_t extent; uint64_t flags; } in;
    struct { uint64_t flags; uint64_t gpu_va; } out;
};
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

#define KBASE_IOCTL_TYPE 0x80
#define KBASE_IOCTL_VERSION_CHECK _IOWR(KBASE_IOCTL_TYPE, 0, struct kbase_ioctl_version_check)
#define KBASE_IOCTL_SET_FLAGS _IOW(KBASE_IOCTL_TYPE, 1, struct kbase_ioctl_set_flags)
#define KBASE_IOCTL_JOB_SUBMIT _IOW(KBASE_IOCTL_TYPE, 2, struct kbase_ioctl_job_submit)
#define KBASE_IOCTL_MEM_ALLOC _IOWR(KBASE_IOCTL_TYPE, 5, union kbase_ioctl_mem_alloc)

#define BASE_MEM_SAME_VA (1ull << 13)
#define BASE_MEM_PROT_CPU_RD (1ull << 0)
#define BASE_MEM_PROT_CPU_WR (1ull << 1)
#define BASE_MEM_PROT_GPU_RD (1ull << 2)
#define BASE_MEM_PROT_GPU_WR (1ull << 3)
#define BASE_MEM_MAP_TRACKING_HANDLE (3ull << 12)
#define BASE_JD_REQ_CS 0x2

static int fd;

static void *map_gpu(unsigned pages) {
    union kbase_ioctl_mem_alloc ma;
    memset(&ma, 0, sizeof(ma));
    ma.in.flags = BASE_MEM_SAME_VA | BASE_MEM_PROT_CPU_RD | BASE_MEM_PROT_CPU_WR | BASE_MEM_PROT_GPU_RD | BASE_MEM_PROT_GPU_WR;
    ma.in.va_pages = pages;
    ma.in.commit_pages = pages;
    if (ioctl(fd, KBASE_IOCTL_MEM_ALLOC, &ma) < 0) { perror("MEM_ALLOC"); return NULL; }
    void *r = mmap(NULL, pages << 12, PROT_READ | PROT_WRITE, MAP_SHARED, fd, ma.out.gpu_va);
    if (r == MAP_FAILED) { perror("mmap"); return NULL; }
    return r;
}

static void pack_header(uint32_t *cl, uint32_t type, uint64_t next) {
    cl[0]=0; cl[1]=0; cl[2]=0; cl[3]=0;
    cl[4] = 1 | (type << 1);
    cl[5] = 0;
    cl[6] = (uint32_t)next; cl[7] = (uint32_t)(next >> 32);
}
struct write_value_payload { uint64_t address, type, immediate_value; };

static int submit_cs(uint64_t jc, uint8_t id) {
    struct base_jd_atom_v2 atom;
    memset(&atom, 0, sizeof(atom));
    atom.jc = jc;
    atom.atom_number = id;
    atom.core_req = BASE_JD_REQ_CS;
    struct kbase_ioctl_job_submit js = { (uint64_t)&atom, 1, sizeof(atom) };
    return ioctl(fd, KBASE_IOCTL_JOB_SUBMIT, &js);
}
static int wait_event(uint32_t *code) {
    struct pollfd pfd = { fd, POLLIN, 0 };
    if (poll(&pfd, 1, 3000) <= 0) return -1;
    struct base_jd_event_v2 ev;
    if (read(fd, &ev, sizeof(ev)) < (int)sizeof(ev)) return -1;
    *code = ev.event_code;
    return 0;
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    struct kbase_ioctl_version_check vc = { 999, 999 };
    fd = open("/dev/mali0", O_RDWR);
    if (fd < 0) { perror("open"); return 1; }
    ioctl(fd, KBASE_IOCTL_VERSION_CHECK, &vc);
    struct kbase_ioctl_set_flags sf = { 0 };
    if (ioctl(fd, KBASE_IOCTL_SET_FLAGS, &sf) < 0) { perror("SET_FLAGS"); return 1; }
    mmap(NULL, 0x1000, 0, MAP_SHARED, fd, BASE_MEM_MAP_TRACKING_HANDLE);
    printf("[+] api %u.%u init ok\n", vc.major, vc.minor);

    void *jc = map_gpu(1);
    void *target = map_gpu(1);
    if (!jc || !target) return 1;
    memset(jc, 0, 0x1000);
    *(volatile uint64_t *)target = 0xdead0000dead0000ULL;

    pack_header((uint32_t *)jc, 2, 0);
    struct write_value_payload pl = { (uint64_t)target, 7, 0x4141414142424242ULL };
    memcpy((uint32_t *)jc + 8, &pl, sizeof(pl));

    printf("[*] jc=%p target=%p submitting...\n", jc, target);
    if (submit_cs((uint64_t)jc, 1) < 0) { perror("submit"); return 1; }
    uint32_t ev = 0xffffffff;
    int wr = wait_event(&ev);
    printf("[%c] event wait ret=%d code=0x%x\n", wr == 0 ? '+' : '-', wr, ev);
    printf("[%c] target=0x%016llx (expect 0x4141414142424242)\n",
           *(volatile uint64_t *)target == 0x4141414142424242ULL ? '+' : '-',
           (unsigned long long)*(volatile uint64_t *)target);
    return 0;
}
