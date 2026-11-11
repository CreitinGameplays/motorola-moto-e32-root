/* memrw - minimal freestanding /dev/mem accessor for the 7.1 test
 * boots (no libc: raw aarch64 syscalls, ~3 KB binary so it can be
 * pushed over the CDC-ACM serial shell in one base64 line).
 *
 *   memrw ADDR [COUNT]  - read COUNT 32-bit words
 *   memrw -w ADDR VALUE - write one word
 *
 * Build (VPS):
 *   clang --target=aarch64-linux-gnu -ffreestanding -nostdlib -static \
 *     -O2 -o memrw memrw_nolibc.c freestanding_start.S
 * Push to the parked 7.1 (the shell line buffer truncates around
 * 2 KB, so the base64 goes in 1 KB appends):
 *   base64 -w0 memrw.gz > memrw.b64   # then "echo <chunk> >> /m.b64"
 *   busybox base64 -d /m.b64 > /memrw.gz && busybox gzip -d -c
 *     /memrw.gz > /memrw && chmod +x /memrw
 * Note: /dev/mem needs the mmap path above (pread on /dev/mem does
 * not work on this kernel) and the binary has to be re-pushed after
 * every reboot - it lives in the initramfs only.
 */

typedef unsigned long ul;

static long sys(long n, long a, long b, long c, long d, long e, long f)
{
	register long x8 asm("x8") = n;
	register long x0 asm("x0") = a;
	register long x1 asm("x1") = b;
	register long x2 asm("x2") = c;
	register long x3 asm("x3") = d;
	register long x4 asm("x4") = e;
	register long x5 asm("x5") = f;

	asm volatile("svc 0"
		     : "=r"(x0)
		     : "r"(x8), "r"(x0), "r"(x1), "r"(x2), "r"(x3),
		       "r"(x4), "r"(x5)
		     : "memory", "cc");
	return x0;
}

#define SYS_write	64
#define SYS_openat	56
#define SYS_mmap	222
#define SYS_close	57
#define SYS_exit	93

static void wr(const char *s, unsigned long n)
{
	sys(SYS_write, 1, (long)s, n, 0, 0, 0);
}

static void outhex(ul v)
{
	char b[9];
	int i;

	for (i = 7; i >= 0; i--) {
		b[i] = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	}
	wr(b, 8);
}

static ul parsehex(const char *s)
{
	ul v = 0;

	while (*s) {
		char c = *s++;
		ul d;

		if (c >= '0' && c <= '9')
			d = c - '0';
		else if (c >= 'a' && c <= 'f')
			d = c - 'a' + 10;
		else if (c >= 'A' && c <= 'F')
			d = c - 'A' + 10;
		else
			break;
		v = v * 16 + d;
	}
	return v;
}

void real_main(unsigned long *sp)
{
	ul argc, addr = 0, count = 16, val = 0, i;
	char **argv;
	volatile unsigned int *p;
	long fd;

	argc = sp[0];
	argv = (char **)(sp + 1);

	if (argc < 2) {
		wr("memrw ADDR [COUNT] | memrw -w ADDR VALUE\n", 41);
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	if (argv[1][0] == '-' && argv[1][1] == 'w' && argc >= 4) {
		addr = parsehex(argv[2]);
		val = parsehex(argv[3]);
	} else {
		addr = parsehex(argv[1]);
		if (argc > 2)
			count = parsehex(argv[2]);
	}

	/* AT_FDCWD = -100 */
	fd = sys(SYS_openat, -100, (long)"/dev/mem", 2 /* O_RDWR */, 0, 0, 0);
	if (fd < 0) {
		wr("open /dev/mem failed\n", 21);
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	{
		ul page = addr & ~4095UL;
		ul span = ((addr + 65536) & ~4095UL) - page;
		long r = sys(SYS_mmap, 0, span, 3 /* RW */, 1 /* SHARED */,
			     fd, (long)page);

		sys(SYS_close, fd, 0, 0, 0, 0, 0);
		if (r < 0) {
			wr("mmap failed\n", 12);
			sys(SYS_exit, 1, 0, 0, 0, 0, 0);
		}
		p = (volatile unsigned int *)(r + (addr & 4095));
	}

	if (argv[1][0] == '-' && argv[1][1] == 'w') {
		*p = (unsigned int)val;
	}

	for (i = 0; i < count; i++) {
		outhex(addr + i * 4);
		wr(": ", 2);
		outhex(p[i]);
		wr("\n", 1);
	}
	sys(SYS_exit, 0, 0, 0, 0, 0, 0);
}
