/* dmctl - freestanding device-mapper helper for the 7.1 test boots
 * (no libc: raw aarch64 syscalls, small binary, pushed over the
 * CDC-ACM serial shell like memrw).
 *
 * Creates one dm target and resumes it, then mknods the block node.
 * Built for validating the dm-default-key port against the real
 * metadata-encrypted /data, read-only, before booting the stock
 * Android userspace on the 7.1 kernel:
 *
 *   dmctl NAME DEV KEYFILE SIZE_SECTORS [target] [args]
 *
 *   NAME        dm device name (-> /dev/mapper/NAME)
 *   DEV         underlying block device path (e.g. /dev/sda68)
 *   KEYFILE     raw key file (e.g. /metadata/mount/vold/.../key)
 *   SIZE_SECTORS device size in 512-byte sectors (decimal)
 *   target      dm target type, default "default-key"
 *   args        raw target argument string; when omitted the
 *               default-key line is built from the key file:
 *               "aes-xts-plain64 <keyhex> 0 <DEV> 0
 *                2 sector_size:4096 iv_large_sectors"
 *
 * Build (VPS):
 *   clang --target=aarch64-linux-gnu -ffreestanding -nostdlib -static \
 *     -O2 -o dmctl dmctl_nolibc.c freestanding_start.S
 * Push: same chunked base64 flow as memrw_nolibc.c (the tty line
 * buffer truncates around 2 KB).
 *
 * NOTE: the dm-ioctl command numbers are an enum, not the old
 * hardcoded values: DEV_CREATE=0x03, DEV_SUSPEND=0x06, DEV_STATUS=0x07,
 * TABLE_LOAD=0x09.
 */

typedef unsigned long ul;
typedef unsigned int u32;
typedef unsigned long long u64;

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

#define SYS_ioctl	29
#define SYS_mknodat	33
#define SYS_mkdirat	34
#define SYS_openat	56
#define SYS_close	57
#define SYS_read	63
#define SYS_write	64
#define SYS_exit	93

static void wr(const char *s, unsigned long n)
{
	sys(SYS_write, 1, (long)s, n, 0, 0, 0);
}

static void wstr(const char *s)
{
	ul n = 0;

	while (s[n])
		n++;
	wr(s, n);
}

static void whex(ul v)
{
	char b[17];
	int i;

	for (i = 15; i >= 0; i--) {
		b[i] = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	}
	wr(b, 16);
}

static long slen(const char *s)
{
	long n = 0;

	while (s[n])
		n++;
	return n;
}

static void scopy(char *d, const char *s)
{
	while ((*d++ = *s++))
		;
}

static void scat(char *d, const char *s)
{
	d += slen(d);
	scopy(d, s);
}

static ul parsedec(const char *s)
{
	ul v = 0;

	while (*s >= '0' && *s <= '9')
		v = v * 10 + (*s++ - '0');
	return v;
}

/* ---- uapi/linux/dm-ioctl.h (subset) ---- */

#define DM_NAME_LEN	128
#define DM_UUID_LEN	129
#define DM_MAX_TYPE_NAME 16

struct dm_ioctl {
	u32 version[3];
	u32 data_size;
	u32 data_start;
	u32 target_count;
	u32 open_count;
	u32 flags;
	u32 event_nr;
	u32 padding;
	u64 dev;
	char name[DM_NAME_LEN];
	char uuid[DM_UUID_LEN];
	char data[7];
};

struct dm_target_spec {
	u64 sector_start;
	u64 length;
	int status;
	u32 next;
	char target_type[DM_MAX_TYPE_NAME];
};

#define IOCTL_SZ	312

#define DM_CMD(nr)	((3ul << 30) | (IOCTL_SZ << 16) | (0xfdul << 8) | (nr))
#define DM_VERSION	DM_CMD(0x00)
#define DM_DEV_CREATE	DM_CMD(0x03)
#define DM_DEV_SUSPEND	DM_CMD(0x06)
#define DM_DEV_STATUS	DM_CMD(0x07)
#define DM_TABLE_LOAD	DM_CMD(0x09)

static char iocbuf[1024] __attribute__((aligned(8)));
static struct dm_ioctl *ioc = (struct dm_ioctl *)iocbuf;
static char args[512];

static void ioc_init(void)
{
	char *p = (char *)ioc;
	long i;

	for (i = 0; i < 1024; i++)
		p[i] = 0;
	ioc->version[0] = 4;
	ioc->version[1] = 48;
	ioc->version[2] = 0;
	ioc->data_size = IOCTL_SZ;
	ioc->data_start = IOCTL_SZ;
}

void real_main(unsigned long *sp)
{
	ul argc = sp[0];
	char **argv = (char **)(sp + 1);
	const char *name, *dev, *keyfile, *target;
	ul sectors;
	long ctlfd, fd, n, r, i;
	char key[128];
	char *spec;
	long spec_off = IOCTL_SZ;
	long args_off = IOCTL_SZ + 40;

	if (argc < 5) {
		wstr("dmctl NAME DEV KEYFILE SIZE_SECTORS [target] [args]\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	name = argv[1];
	dev = argv[2];
	keyfile = argv[3];
	sectors = parsedec(argv[4]);
	target = (argc > 5) ? argv[5] : "default-key";

	/* 1. read the key (unused for generic targets) */
	fd = sys(SYS_openat, -100, (long)keyfile, 0 /* O_RDONLY */, 0, 0, 0);
	if (fd < 0) {
		wstr("dmctl: open key failed\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	n = sys(SYS_read, fd, (long)key, sizeof(key), 0, 0, 0);
	sys(SYS_close, fd, 0, 0, 0, 0, 0);
	if (n <= 0) {
		wstr("dmctl: key file empty\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	wr("dmctl: key bytes: ", 18);
	whex(n);
	wr("\n", 1);

	if (argc > 6) {
		scopy(args, argv[6]);
	} else {
	{
		static const char hexd[] = "0123456789abcdef";
		char *p = args;

		scopy(p, "aes-xts-plain64 ");
		p += slen(p);
		for (i = 0; i < n; i++) {
			*p++ = hexd[(key[i] >> 4) & 0xf];
			*p++ = hexd[key[i] & 0xf];
		}
		*p++ = ' ';
		scopy(p, "0 ");
		p += 2;
		scopy(p, dev);
		p += slen(p);
		scopy(p, " 0 ");
		p += 3;
		scopy(p, "2 sector_size:4096 iv_large_sectors");
	}
	}
	wr("dmctl: args: ", 13);
	wr(args, slen(args));
	wr("\n", 1);

	/* 3. /dev/mapper/control via /sys/class/misc/device-mapper/dev */
	sys(SYS_mkdirat, -100, (long)"/dev/mapper", 0755, 0, 0, 0);
	fd = sys(SYS_openat, -100,
		  (long)"/sys/class/misc/device-mapper/dev", 0, 0, 0, 0);
	if (fd < 0) {
		wstr("dmctl: no /sys/class/misc/device-mapper (dm not up?)\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	{
		char b[32];
		long m;

		m = sys(SYS_read, fd, (long)b, sizeof(b) - 1, 0, 0, 0);
		sys(SYS_close, fd, 0, 0, 0, 0, 0);
		if (m <= 0) {
			wstr("dmctl: read misc dev failed\n");
			sys(SYS_exit, 1, 0, 0, 0, 0, 0);
		}
		b[m] = 0;
		{
			ul maj = 0, min = 0, i;

			for (i = 0; b[i] >= '0' && b[i] <= '9'; i++)
				maj = maj * 10 + (b[i] - '0');
			while (b[i] && b[i] != ':')
				i++;
			i++;
			for (; b[i] >= '0' && b[i] <= '9'; i++)
				min = min * 10 + (b[i] - '0');
			wr("dmctl: control maj:min ", 24);
			whex(maj);
			wr(":", 1);
			whex(min);
			wr("\n", 1);
			sys(SYS_mknodat, -100,
			    (long)"/dev/mapper/control",
			    020600 /* S_IFCHR|0600 */,
			    (long)((maj << 20) | min), 0, 0);
		}
	}

	ctlfd = sys(SYS_openat, -100, (long)"/dev/mapper/control",
		    2 /* O_RDWR */, 0, 0, 0);
	if (ctlfd < 0) {
		wstr("dmctl: open control failed\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}

	/* 4. DM_VERSION */
	ioc_init();
	r = sys(SYS_ioctl, ctlfd, DM_VERSION, (long)ioc, 0, 0, 0);
	if (r) {
		wstr("dmctl: DM_VERSION failed\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}

	/* 5. DM_DEV_CREATE */
	ioc_init();
	scopy(ioc->name, name);
	r = sys(SYS_ioctl, ctlfd, DM_DEV_CREATE, (long)ioc, 0, 0, 0);
	if (r) {
		wr("dmctl: DM_DEV_CREATE failed r=", 31);
		whex((ul)(long)r);
		wr("\n", 1);
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}

	/* 6. DM_TABLE_LOAD */
	ioc_init();
	scopy(ioc->name, name);
	ioc->target_count = 1;
	ioc->data_size = args_off + slen(args) + 8;
	spec = (char *)ioc + spec_off;
	*(u64 *)(spec + 0) = 0;			/* sector_start */
	*(u64 *)(spec + 8) = sectors;		/* length */
	*(u32 *)(spec + 16) = 0;		/* status */
	*(u32 *)(spec + 20) = 0;		/* next = end */
	scopy(spec + 24, target);
	{
		char *d = (char *)ioc + args_off;

		for (i = 0; i < slen(args); i++)
			d[i] = args[i];
		d[i] = 0;
	}
	r = sys(SYS_ioctl, ctlfd, DM_TABLE_LOAD, (long)ioc, 0, 0, 0);
	if (r) {
		wr("dmctl: DM_TABLE_LOAD failed r=", 31);
		whex((ul)(long)r);
		wr("\n", 1);
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}

	/* 7. resume */
	ioc_init();
	scopy(ioc->name, name);
	r = sys(SYS_ioctl, ctlfd, DM_DEV_SUSPEND, (long)ioc, 0, 0, 0);
	if (r) {
		wr("dmctl: resume failed r=", 24);
		whex((ul)(long)r);
		wr("\n", 1);
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}

	/* 8. status -> dev, then mknod the block node */
	ioc_init();
	scopy(ioc->name, name);
	r = sys(SYS_ioctl, ctlfd, DM_DEV_STATUS, (long)ioc, 0, 0, 0);
	if (r) {
		wstr("dmctl: DM_DEV_STATUS failed\n");
		sys(SYS_exit, 1, 0, 0, 0, 0, 0);
	}
	{
		ul devt = ioc->dev;
		ul maj = devt >> 20;
		ul min = devt & 0xfffff;
		char path[160];

		scopy(path, "/dev/mapper/");
		scopy(path + slen(path), name);
		sys(SYS_mknodat, -100, (long)path,
		    060600 /* S_IFBLK|0600 */,
		    (long)((maj << 20) | min), 0, 0);
		wr("dmctl: OK ", 10);
		wr(path, slen(path));
		wr(" (maj ", 6);
		whex(maj);
		wr(" min ", 5);
		whex(min);
		wr(")\n", 2);
	}
	sys(SYS_exit, 0, 0, 0, 0, 0, 0);
}
