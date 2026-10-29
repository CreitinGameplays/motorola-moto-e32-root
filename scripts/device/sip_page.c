/*
 * sip_page - reserve one page below 4 GiB and report its physical address.
 *
 * The Spreadtrum SIP SMC gateway (U-Boot 0x8d0e8) truncates the buffer pointer
 * to 32 bits, so the payload page must live in the low 4 GiB of DRAM
 * (0x80000000..0x100000000 here).  On this kernel the buddy allocator hands
 * out pages from the top of RAM first, so a small allocation almost always
 * lands above 4 GiB.  The helper therefore maps the arena file in 64 MB
 * chunks, faults each chunk in and keeps it mapped; that pressure pushes the
 * allocator into low memory.  The first chunk containing a page below 4 GiB
 * wins, every other chunk is unmapped, and the winning chunk is mlock()ed.
 *
 * The chunk is a MAP_SHARED view of a plain file, so the host can read the SMC
 * result back with `dd if=<file> bs=4096 skip=<CHUNK*16384+IDX> count=1`.
 *
 * The process detaches from the terminal (setsid, stdio -> /dev/null) but keeps
 * running, so the page stays mapped and locked while the module executes.
 *
 * Build:
 *   $NDK/toolchains/llvm/prebuilt/windows-x86_64/bin/clang \
 *       --target=aarch64-linux-android21 -O2 -o sip_page sip_page.c
 *
 * Usage: sip_page <arena-file> <plaintext>
 */
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

#define PAGE       4096UL
#define CHUNK_MB   64
#define CHUNK_SZ   ((size_t)CHUNK_MB << 20)
#define MAX_CHUNKS 24                 /* ~1.5 GiB of pressure, then give up */
#define RAM_LO     0x80000000ULL
#define RAM_HI     0x100000000ULL     /* SMC buffer field is 32-bit */

static unsigned long long pfn_of(const void *p, int *present)
{
    uint64_t entry = 0;
    int fd = open("/proc/self/pagemap", O_RDONLY);
    off_t off = (off_t)((uintptr_t)p / PAGE) * 8;

    if (fd < 0 || pread(fd, &entry, 8, off) != 8) {
        if (fd >= 0)
            close(fd);
        *present = 0;
        return 0;
    }
    close(fd);
    *present = (int)(entry >> 63);
    return entry & ((1ULL << 55) - 1);
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/data/local/tmp/siparena.bin";
    const char *text = argc > 2 ? argv[2] : "VerifiedBoot-UNLOCK";
    unsigned char *chunk[MAX_CHUNKS];
    size_t npages = CHUNK_SZ / PAGE;
    unsigned char *pm;
    unsigned char *page = NULL;
    size_t i, c, idx = 0, win_chunk = 0, win_idx = 0;
    unsigned long long pa = 0, best_pa = 0;
    int present = 0, fd, pmfd, nchunks = 0;

    fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0600);
    if (fd < 0 || ftruncate(fd, (off_t)CHUNK_SZ * MAX_CHUNKS) < 0) {
        perror("open/ftruncate");
        return 1;
    }
    pm = mmap(NULL, npages * 8, PROT_READ | PROT_WRITE,
              MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (pm == MAP_FAILED) {
        perror("mmap pagemap buffer");
        return 1;
    }

    for (c = 0; c < MAX_CHUNKS && !page; c++) {
        unsigned long present_n = 0, low_n = 0;
        unsigned long long lo = ~0ULL, hi = 0;

        chunk[c] = mmap(NULL, CHUNK_SZ, PROT_READ | PROT_WRITE, MAP_SHARED,
                        fd, (off_t)c * CHUNK_SZ);
        if (chunk[c] == MAP_FAILED) {
            perror("mmap chunk");
            break;
        }
        nchunks = c + 1;
        for (i = 0; i < npages; i++)
            chunk[c][i * PAGE] = 1;       /* fault the chunk in */

        pmfd = open("/proc/self/pagemap", O_RDONLY);
        if (pmfd < 0) {
            perror("pagemap");
            return 1;
        }
        if (pread(pmfd, pm, npages * 8,
                  (off_t)((uintptr_t)chunk[c] / PAGE) * 8) < 0) {
            perror("pread pagemap");
            return 1;
        }
        close(pmfd);

        for (i = 0; i < npages; i++) {
            uint64_t entry;
            unsigned long long p;
            memcpy(&entry, pm + i * 8, 8);
            if (!(entry >> 63))
                continue;
            present_n++;
            p = (entry & ((1ULL << 55) - 1)) * PAGE;
            if (p < lo)
                lo = p;
            if (p > hi)
                hi = p;
            if (p < RAM_LO || p >= RAM_HI)
                continue;
            low_n++;
            if (!page) {
                win_chunk = c;
                win_idx = i;
                best_pa = p;
                page = chunk[c] + i * PAGE;
            }
        }
        printf("chunk %d: present=%lu low=%lu pa=%llx..%llx\n", (int)c,
               present_n, low_n, lo, hi);
        fflush(stdout);
    }

    if (!page) {
        fprintf(stderr, "no page below 4 GiB after %d chunks (%d MB)\n",
                nchunks, nchunks * CHUNK_MB);
        return 1;
    }

    /* Drop the pressure chunks; keep only the winner. */
    for (c = 0; c < (size_t)nchunks; c++) {
        if (c == win_chunk)
            continue;
        munmap(chunk[c], CHUNK_SZ);
    }
    idx = win_chunk * npages + win_idx;

    if (mlock(chunk[win_chunk], CHUNK_SZ) < 0)
        perror("mlock");

    memset(page, 0, PAGE);
    strncpy((char *)page, text, 63);

    /* Re-check: the page must still be present at the same PFN. */
    {
        unsigned long long pfn = pfn_of(page, &present);
        pa = pfn * PAGE;
    }
    printf("IDX=%zu CHUNK=%zu VA=%llx PA=%llx PRESENT=%d TEXT=%s\n", idx,
           win_chunk, (unsigned long long)(uintptr_t)page,
           (unsigned long long)pa, present, text);
    {
        char cmd[128];
        snprintf(cmd, sizeof(cmd), "grep -i VmLck /proc/%d/status",
                 (int)getpid());
        fflush(stdout);
        system(cmd);
        fflush(stdout);
    }

    if (!present || pa != best_pa || pa < RAM_LO || pa >= RAM_HI) {
        fprintf(stderr, "page moved/unmapped (was %llx), refusing\n",
                best_pa);
        return 1;
    }

    /* Detach from the terminal but keep the mapping (and mlock) alive. */
    signal(SIGHUP, SIG_IGN);
    setsid();
    {
        int nul = open("/dev/null", O_RDWR);
        if (nul >= 0) {
            dup2(nul, 0);
            dup2(nul, 1);
            dup2(nul, 2);
            if (nul > 2)
                close(nul);
        }
    }
    for (;;)
        pause();
    return 0;
}
