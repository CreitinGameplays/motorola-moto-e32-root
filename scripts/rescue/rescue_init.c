/*
 * rescue_init.c - PID 1 for the boot_a rescue image.
 *
 * Runs from the STOCK kernel's initramfs (no devtmpfs, no console, no
 * filesystems are mounted). Does exactly one job: if built with
 * -DRESCUE_RESTORE it rewrites boot_b from the blob embedded in this same
 * initramfs, zero-fills the pad up to the AVB footer, writes the footer, and
 * flips the A/B suffix back to "_b"; otherwise (dry build) it only hashes the
 * blob and writes a marker record to sysdumpdb. Then it reboots.
 *
 * Freestanding: no libc, no crt, no stack protector. Entry point _start.
 *
 * Build (aarch64):
 *   clang --target=aarch64-linux-gnu -O2 -ffreestanding -nostdlib -static \
 *         -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables \
 *         -mgeneral-regs-only -fuse-ld=lld -Wl,-e,_start \
 *         [-DRESCUE_RESTORE] -o rescue_init rescue_init.c
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned char u8;
typedef long i64;

#define AT_FDCWD (-100)
#define S_IFBLK 0060000
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2

#define SYS_openat 56
#define SYS_close 57
#define SYS_lseek 62
#define SYS_read 63
#define SYS_write 64
#define SYS_fsync 82
#define SYS_mknodat 33
#define SYS_reboot 142

#define SEEK_SET 0

#define BLK_BOOT_B 0x0103      /* minor 0x1a  -> 259:26  (sda41) */
#define BLK_MISC_MAJOR 8
#define BLK_MISC_MINOR 4       /* sda4 */
#define BLK_SYSDMP_MAJOR 259
#define BLK_SYSDMP_MINOR 43    /* sda58 */

#define PART_SIZE 0x4000000UL        /* 64 MiB */
#define FOOTER_OFF (PART_SIZE - 64)  /* AVBf lives in the last 64 bytes */
#define BLOB_EXPECT 34724096UL       /* stock extent incl. vbmeta (0x211d900) */
#define MARK_OFF 0x900000UL          /* inside sysdumpdb (10 MiB) */
#define CHUNK 65536

static char zbuf[CHUNK];  /* .bss, zeroed by the ELF loader */

static i64 sc(i64 n, i64 a, i64 b, i64 c, i64 d, i64 e, i64 f) {
    register i64 x8 __asm__("x8") = n;
    register i64 x0 __asm__("x0") = a;
    register i64 x1 __asm__("x1") = b;
    register i64 x2 __asm__("x2") = c;
    register i64 x3 __asm__("x3") = d;
    register i64 x4 __asm__("x4") = e;
    register i64 x5 __asm__("x5") = f;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
                     : "memory");
    return x0;
}

void *memset(void *d, int c, u64 n) {
    u8 *p = (u8 *)d;
    while (n--) *p++ = (u8)c;
    return d;
}

void *memcpy(void *d, const void *s, u64 n) {
    u8 *a = (u8 *)d;
    const u8 *b = (const u8 *)s;
    while (n--) *a++ = *b++;
    return d;
}

static u64 slen(const char *s) {
    u64 n = 0;
    while (s[n]) n++;
    return n;
}

static int memeq(const void *a, const void *b, u64 n) {
    const u8 *x = (const u8 *)a;
    const u8 *y = (const u8 *)b;
    while (n--) if (*x++ != *y++) return 0;
    return 1;
}

static void say(const char *s) { sc(SYS_write, 1, (i64)s, (i64)slen(s), 0, 0, 0); }

static i64 open_ro(const char *p) { return sc(SYS_openat, AT_FDCWD, (i64)p, O_RDONLY, 0, 0, 0); }
static i64 open_wo(const char *p) { return sc(SYS_openat, AT_FDCWD, (i64)p, O_WRONLY, 0, 0, 0); }

static i64 write_all(i64 fd, const void *buf, u64 n) {
    const u8 *p = (const u8 *)buf;
    u64 done = 0;
    while (done < n) {
        i64 w = sc(SYS_write, fd, (i64)(p + done), (i64)(n - done), 0, 0, 0);
        if (w <= 0) return -1;
        done += (u64)w;
    }
    return 0;
}

static u64 fnv_seed(void) { return 1469598103934665603ULL; }
static u64 fnv_byte(u64 h, u8 b) { return (h ^ b) * 1099511628211ULL; }

static u32 crc32_le(const u8 *p, u64 n) {
    u32 crc = 0xffffffffu;
    for (u64 i = 0; i < n; i++) {
        crc ^= p[i];
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xedb88320u & (u32)(-(i64)(crc & 1)));
    }
    return ~crc;
}

static void put32(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); p[2] = (u8)(v >> 16); p[3] = (u8)(v >> 24); }
static void put64(u8 *p, u64 v) { put32(p, (u32)v); put32(p + 4, (u32)(v >> 32)); }

static void marker(u32 status, u32 mode, u64 bsize, u64 bhash, u64 fhash,
                   const u8 *ab_old, const u8 *ab_new, u64 extra) {
    u8 rec[128];
    u8 *p = rec;
    memset(rec, 0, sizeof(rec));
    memcpy(p, "DRESCUE1", 8);
    put32(p + 8, 1);
    put32(p + 12, mode);
    put32(p + 16, status);
    put64(p + 24, bsize);
    put64(p + 32, bhash);
    put64(p + 40, fhash);
    put64(p + 48, extra);
    memcpy(p + 64, ab_old, 32);
    memcpy(p + 96, ab_new, 32);
    i64 fd = open_wo("/dev/sysdumpdb");
    if (fd < 0) return;
    sc(SYS_lseek, fd, (i64)MARK_OFF, SEEK_SET, 0, 0, 0);
    write_all(fd, rec, sizeof(rec));
    sc(SYS_fsync, fd, 0, 0, 0, 0, 0);
    sc(SYS_close, fd, 0, 0, 0, 0, 0);
}

/* hash + size of a file; if out_fd >= 0 the bytes are also written to it */
static i64 stream(const char *path, u64 *size, u64 *hash, i64 out_fd) {
    u8 buf[CHUNK];
    i64 fd = open_ro(path);
    u64 n = 0, h = fnv_seed();
    if (fd < 0) return -2;
    for (;;) {
        i64 r = sc(SYS_read, fd, (i64)buf, CHUNK, 0, 0, 0);
        if (r < 0) { sc(SYS_close, fd, 0, 0, 0, 0, 0); return -3; }
        if (r == 0) break;
        for (i64 i = 0; i < r; i++) h = fnv_byte(h, buf[i]);
        if (out_fd >= 0 && write_all(out_fd, buf, (u64)r) < 0) {
            sc(SYS_close, fd, 0, 0, 0, 0, 0);
            return -4;
        }
        n += (u64)r;
    }
    sc(SYS_close, fd, 0, 0, 0, 0, 0);
    *size = n;
    *hash = h;
    return 0;
}

static i64 read_into(const char *path, u64 off, u8 *dst, u64 len) {
    i64 fd = open_ro(path);
    if (fd < 0) return -1;
    sc(SYS_lseek, fd, (i64)off, SEEK_SET, 0, 0, 0);
    u64 got = 0;
    while (got < len) {
        i64 r = sc(SYS_read, fd, (i64)(dst + got), (i64)(len - got), 0, 0, 0);
        if (r <= 0) { sc(SYS_close, fd, 0, 0, 0, 0, 0); return -2; }
        got += (u64)r;
    }
    sc(SYS_close, fd, 0, 0, 0, 0, 0);
    return 0;
}

static void mk(void) {
    sc(SYS_mknodat, AT_FDCWD, (i64)"/dev/misc", (i64)(S_IFBLK | 0600),
       (i64)((BLK_MISC_MAJOR << 8) | BLK_MISC_MINOR), 0, 0);
    sc(SYS_mknodat, AT_FDCWD, (i64)"/dev/boot_b", (i64)(S_IFBLK | 0600),
       (i64)((259 << 8) | 26), 0, 0);
    sc(SYS_mknodat, AT_FDCWD, (i64)"/dev/sysdumpdb", (i64)(S_IFBLK | 0600),
       (i64)((BLK_SYSDMP_MAJOR << 8) | BLK_SYSDMP_MINOR), 0, 0);
}

/*
 * The 32-byte A/B metadata block at misc+0x800, captured from the device in a
 * state that booted slot _b (crc32_le(bytes[0..27]) == 0x49b9de16):
 *
 *   +0  "_b\0\0"        slot_suffix   (which slot the *bootloader* booted)
 *   +4  "BCAB"          magic
 *   +8  01 02           version 1, nb_slot 2
 *   +12 slot a info     priority 14, tries 0, successful 1  = 0x008e
 *   +14 slot b info     priority 15, tries 6, successful 1  = 0x00ef
 *   +28 crc32_le over [0..27]
 *
 * Slot selection is by **priority** (docs/11), not by the suffix field: the
 * suffix is the bootloader's own report of the slot it chose. The first dry
 * run patched only the suffix and left slot a at priority 15, so the
 * bootloader kept choosing slot a on every reboot - a bootloop. Write the
 * whole known-good block instead: slot b priority 15 wins.
 */
static const u8 ab_block[32] = {
    0x5f, 0x62, 0x00, 0x00, 0x42, 0x43, 0x41, 0x42,
    0x01, 0x02, 0x00, 0x00, 0x8e, 0x00, 0xef, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x16, 0xde, 0xb9, 0x49,
};

/* write the known-good A/B block at misc+0x800 and read it back */
static i64 set_slot_b(u8 *old_out, u8 *new_out) {
    u8 cur[32];
    if (read_into("/dev/misc", 0x800, cur, 32) < 0) return -1;
    memcpy(old_out, cur, 32);
    memcpy(new_out, ab_block, 32);
    if (crc32_le(ab_block, 28) != 0x49b9de16u) return -2;   /* table typo guard */

    i64 fd = open_wo("/dev/misc");
    if (fd < 0) return -3;
    sc(SYS_lseek, fd, 0x800, SEEK_SET, 0, 0, 0);
    if (write_all(fd, ab_block, 32) < 0) { sc(SYS_close, fd, 0, 0, 0, 0, 0); return -4; }
    sc(SYS_fsync, fd, 0, 0, 0, 0, 0);
    sc(SYS_close, fd, 0, 0, 0, 0, 0);

    if (read_into("/dev/misc", 0x800, cur, 32) < 0) return -5;
    for (int i = 0; i < 32; i++) if (cur[i] != ab_block[i]) return -6;
    return 0;
}

static void restart(void) {
    sc(SYS_reboot, 0xfee1dead, 672274793, 0x01234567, 0, 0, 0);
    for (;;) __asm__ volatile("wfi");
}

void _start(void) {
    u8 ab_old[32], ab_new[32];
    u8 *z_old = ab_old, *z_new = ab_new;
    memset(ab_old, 0, 32);
    memset(ab_new, 0, 32);
    u64 bsize = 0, bhash = 0, fsize = 0, fhash = 0;
    u64 rbhash = 0;
    u32 mode = 0;

    mk();

    /* first thing after the nodes exist: prove /init ran at all */
    marker(99, 0, 0, 0, 0, z_old, z_new, 0);

    if (stream("/blob/boot_b", &bsize, &bhash, -1) < 0) {
        marker(90, 0, 0, 0, 0, z_old, z_new, 0);
        restart();
    }
    if (stream("/blob/footer", &fsize, &fhash, -1) < 0) {
        marker(91, 0, bsize, bhash, 0, z_old, z_new, 0);
        restart();
    }
    if (bsize != BLOB_EXPECT || fsize != 64) {
        marker(92, 0, bsize, bhash, fhash, z_old, z_new, 0);
        restart();
    }

#ifdef RESCUE_RESTORE
    mode = 1;
    marker(1, mode, bsize, bhash, fhash, z_old, z_new, 0);   /* started */

    i64 fd = open_wo("/dev/boot_b");
    if (fd < 0) { marker(93, mode, bsize, bhash, fhash, z_old, z_new, 0); restart(); }

    u64 n2 = 0, h2 = 0;
    if (stream("/blob/boot_b", &n2, &h2, fd) < 0 || n2 != bsize || h2 != bhash) {
        sc(SYS_close, fd, 0, 0, 0, 0, 0);
        marker(94, mode, n2, h2, fhash, z_old, z_new, 0);
        restart();
    }
    /* pad with zeros up to the footer */
    u64 off = bsize;
    while (off < FOOTER_OFF) {
        u64 n = FOOTER_OFF - off;
        if (n > CHUNK) n = CHUNK;
        if (write_all(fd, zbuf, n) < 0) { sc(SYS_close, fd, 0, 0, 0, 0, 0); marker(95, mode, bsize, bhash, fhash, z_old, z_new, off); restart(); }
        off += n;
    }
    u8 ftr[64];
    if (read_into("/blob/footer", 0, ftr, 64) < 0 || write_all(fd, ftr, 64) < 0) {
        sc(SYS_close, fd, 0, 0, 0, 0, 0);
        marker(96, mode, bsize, bhash, fhash, z_old, z_new, 0);
        restart();
    }
    sc(SYS_fsync, fd, 0, 0, 0, 0, 0);
    sc(SYS_close, fd, 0, 0, 0, 0, 0);

    /* verify: payload prefix and footer as read back from the device */
    u8 a[2048], b[64];
    if (read_into("/dev/boot_b", 0, a, 2048) == 0) {
        for (int i = 0; i < 2048; i++) rbhash = fnv_byte(rbhash, a[i]);
    } else {
        rbhash = 0;
    }
    u8 exp[2048];
    read_into("/blob/boot_b", 0, exp, 2048);
    u8 rbftr[64];
    if (read_into("/dev/boot_b", FOOTER_OFF, rbftr, 64) < 0) rbftr[0] = 0x55;
    if (read_into("/blob/footer", 0, b, 64) < 0) b[0] = 0xaa;

    u32 ok = 1;
    if (!memeq(a, exp, 2048)) ok = 0;
    if (!memeq(rbftr, b, 64)) ok = 0;

    i64 r = set_slot_b(ab_old, ab_new);
    if (r < 0) ok = 0;
    marker(ok ? 2 : 3, mode, bsize, bhash, fhash, ab_old, ab_new, rbhash);
    restart();
#else
    mode = 0;
    marker(10, mode, bsize, bhash, fhash, z_old, z_new, 0);  /* blob hashed ok */
    i64 r = set_slot_b(ab_old, ab_new);
    marker(r == 0 ? 11 : 12, mode, bsize, bhash, fhash, ab_old, ab_new, (u64)r);
    restart();
#endif
}