/* freestanding aarch64 CPU frequency probe: times a fixed dependent-add
 * loop with CLOCK_MONOTONIC via raw syscalls (no libc).  Static ELF,
 * runs on Android via adb shell.  Usage: bench <iters-in-millions> */

typedef unsigned long u64;
typedef long i64;

struct ts { i64 sec; i64 nsec; };

static inline long sys3(long n, long a, long b, long c)
{
	register long r0 asm("x0") = a;
	register long r1 asm("x1") = b;
	register long r2 asm("x2") = c;
	register long r8 asm("x8") = n;
	long ret;
	asm volatile("svc #0" : "=r"(ret)
		     : "r"(r0), "r"(r1), "r"(r2), "r"(r8)
		     : "memory");
	return ret;
}

#define SYS_CLOCK_GETTIME 113
#define SYS_WRITE         64
#define SYS_EXIT          93

static void print_u64(u64 v)
{
	char buf[24];
	int i = 24;
	buf[--i] = '\n';
	if (!v)
		buf[--i] = '0';
	while (v) {
		buf[--i] = '0' + (v % 10);
		v /= 10;
	}
	sys3(SYS_WRITE, 1, (long)(buf + i), 24 - i);
}

void _start(void)
{
	struct ts t0, t1;
	volatile u64 x = 0;
	u64 iters = 100000000UL;	/* 100M default */
	u64 i;

	/* optional argv[1] in millions - parse via /proc self is overkill;
	 * fixed 100M iters (~0.3-1.5 s) is enough for A/B */
	(void)iters;

	sys3(SYS_CLOCK_GETTIME, 1, (long)&t0, 0);
	for (i = 0; i < 400000000UL; i++)
		x += i;
	sys3(SYS_CLOCK_GETTIME, 1, (long)&t1, 0);

	u64 ms = (u64)(t1.sec - t0.sec) * 1000UL +
		 (u64)(t1.nsec - t0.nsec) / 1000000UL;
	print_u64(ms);
	sys3(SYS_EXIT, 0, 0, 0);
}
