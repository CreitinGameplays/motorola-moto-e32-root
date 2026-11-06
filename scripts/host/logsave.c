/* logsave - the /init of the 7.1 flash-test initramfs.
 *
 * Boot plan (see docs/23-7.1-flash-bringup.md): the 7.1 kernel is packed
 * into a self-signed AVB boot image, flashed to boot_b with one-attempt
 * slot arming, and the proven boot_a rescue image stands by. If the
 * kernel reaches userspace, this program:
 *
 *   1. waits a few seconds for late initcalls/workqueues (if boot is
 *      going to hang, that is where it hangs),
 *   2. dumps the WHOLE kernel ring into the sysdumpdb partition at a
 *      1 MiB offset (plus a backup copy at 2 MiB) with a magic header,
 *      so the log survives any recovery - including a cold power hold,
 *   3. reboots: the bootloader sees slot b's tries exhausted and boots
 *      the boot_a rescue, which restores the stock boot_b -> Android.
 *
 * Every step is echoed to /dev/kmsg, so the same text also lands in the
 * pstore console ring (0xfff80000) for warm-reboot recoveries. The
 * on-panel status grid (include/linux/diag_stage.h in the 7.1 fork)
 * lights slot 0 when init execs and blinks slot 7 while the scheduler
 * lives, so the panel alone shows how far boot got even if init never
 * runs.
 *
 * Once the kernel's musb + g_serial gadget bind, the whole ring is also
 * dumped to /dev/ttyGS0 (a CDC-ACM port on the PC) and the initramfs'
 * static busybox gets an interactive shell on the same line - the 7.1
 * test boot has no adb, so that shell is the only live debug console.
 *
 * The sysdumpdb node is located by parsing the GPT of /dev/sda (the
 * initramfs devtmpfs has no /dev/block/by-name - those symlinks come
 * from Android's init, which is not running here).
 *
 * Build (static aarch64):
 *   aarch64-linux-gnu-gcc -static -Os -Wall -o init logsave.c
 *   (via scripts/host/build_71_logramfs.sh)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <sys/klog.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <dirent.h>
#include <signal.h>
#include <termios.h>

#ifndef BLKSSZGET
#define BLKSSZGET _IO(0x12, 104)
#endif

#define LOG_OFF1	0x100000UL	/* primary copy, 1 MiB in */
#define LOG_OFF2	0x200000UL	/* backup copy, 2 MiB in */
#define LOG_OFF3	0x800000UL	/* merged DTB capture, 8 MiB in */
#define DTB_MAGIC	"H71DTB01"
#define DTB_MAX		0x100000UL	/* 1 MiB cap, the DTB is ~200 KB */
#define WAIT_SECONDS	30

static const char magic[8] = "H71LOG01";

/* USB serial (g_serial gadget): once the musb UDC binds, the PC gets a
 * CDC-ACM port and the whole ring goes over the wire - the panel
 * becomes the backup channel.  Opened lazily: the gadget may bind
 * seconds after /init starts. */
static int ser_fd = -1;
static char *ring_copy;		/* kept copy of the kernel ring */
static int ring_len;
static int ring_save_errno;	/* errno of the last failed flash save */
static int ring_save_phase;	/* 1 pwrite copy1, 2 pwrite copy2, 3 fsync */
static volatile sig_atomic_t save_phase;
static unsigned long irq_last;	/* previous /proc/interrupts sum */

/* SIGALRM just interrupts the blocked write/fsync (EINTR): the second
 * block write to the UFS device wedges the queue (tests 46/47: first
 * save fine, then a hang), and the saver child must survive that to
 * keep reporting - see docs/23-7.1-flash-bringup.md */
static void save_alarm_handler(int sig)
{
	(void)sig;
}

static void kmsg(const char *fmt, ...)
{
	char buf[512];
	va_list ap;
	int n, fd;

	va_start(ap, fmt);
	n = vsnprintf(buf, sizeof(buf) - 2, fmt, ap);
	va_end(ap);
	if (n < 0)
		return;
	buf[n++] = '\n';

	fd = open("/dev/kmsg", O_WRONLY);
	if (fd >= 0) {
		write(fd, buf, n);
		close(fd);
	}
	fd = open("/dev/console", O_WRONLY);
	if (fd >= 0) {
		write(fd, buf, n);
		close(fd);
	}
}

static void serial_try(void)
{
	int fd;

	if (ser_fd >= 0)
		return;
	fd = open("/dev/ttyGS0", O_WRONLY | O_NONBLOCK | O_NOCTTY);
	if (fd < 0)
		return;
	ser_fd = fd;
	kmsg("<6>H71-INIT: ttyGS0 open - USB serial live");
	if (ring_copy && ring_len > 0) {
		if (write(ser_fd, "\r\n=== H71 full kernel ring ===\r\n", 31) < 0)
			;
		if (write(ser_fd, ring_copy, ring_len) < 0)
			;
		if (write(ser_fd, "\r\n=== H71 end of ring ===\r\n", 27) < 0)
			;
	}
}

static void serial_printf(const char *fmt, ...)
{
	char buf[512];
	va_list ap;
	int n;

	if (ser_fd < 0)
		return;
	va_start(ap, fmt);
	n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
	va_end(ap);
	if (n > 0)
		(void)write(ser_fd, buf, (size_t)n);
}

/*
 * Interactive debug console on the USB serial line: g_serial gives the
 * PC a CDC-ACM port, and busybox (static, in the initramfs) gives us a
 * shell on it.  The 7.1 kernel has no usable reset path and no adb, so
 * this is the only way to poke at a live test boot (mount things, cat
 * /proc/device-tree, read /sys/firmware, poke registers with devmem...).
 * Started lazily: the gadget may bind after /init.
 */
static int shell_started;

static void shell_try(void)
{
	pid_t pid;
	int fd;

	if (shell_started || access("/bin/busybox", X_OK) != 0)
		return;
	fd = open("/dev/ttyGS0", O_RDWR | O_NOCTTY);
	if (fd < 0)
		return;
	shell_started = 1;
	pid = fork();
	if (pid == 0) {
		int c;

		setsid();
		c = open("/dev/ttyGS0", O_RDWR);
		if (c >= 0) {
			ioctl(c, TIOCSCTTY, 0);
			dup2(c, 0);
			dup2(c, 1);
			dup2(c, 2);
			if (c > 2)
				close(c);
		}
		execl("/bin/sh", "sh", "-i", (char *)NULL);
		_exit(127);
	}
	close(fd);
	if (pid > 0)
		kmsg("<6>H71-INIT: serial shell spawned (pid %d)", (int)pid);
}

/*
 * Feed the Unisoc FIQ watchdog (sprd,wdt-r2p0-fiq) while this boot is
 * alive.  The 4.14 daily driver arms it from hang_debug and feeds it
 * with per-CPU threads; the 7.1 port has neither, so if the bootloader
 * leaves the counter armed nobody would feed it here.  A kernel-side
 * early_initcall (arch/arm64/kernel/diag_wdt.c) prints the state it
 * found at kernel entry; logsave rewrites the original LOAD value every
 * few seconds - alive boots park forever, and a boot that hangs before
 * /init stops feeding, so the bite recovers the phone without a power
 * hold.
 *
 * Register map per 4.14 drivers/watchdog/sprd_wdt_fiq.c; the base is
 * the one of the vendor DTB's watchdog@644e0000 (the kernel-side
 * H71-WDT line cross-checks it at boot).
 */
#define WDT_BASE		0x644e0000UL
#define WDT_LOAD_LOW		0x0
#define WDT_LOAD_HIGH		0x4
#define WDT_CTRL		0x8
#define WDT_INT_CLR		0xc
#define WDT_INT_RAW		0x10
#define WDT_CNT_LOW		0x18
#define WDT_CNT_HIGH		0x1c
#define WDT_LOCK		0x20
#define WDT_LOCK_KEY		0xe551
#define WDT_LDBUSY_BIT		0x10u	/* INT_RAW: load busy */
#define WDT_INT_CLR_BIT		0x1u	/* INT_CLR: clear bark */
#define WDT_RST_CLR_BIT		0x8u	/* INT_CLR: clear bite */

static void wdt_pet(void);

static volatile unsigned int *wdt_regs;

static void wdt_init(void)
{
	int fd = open("/dev/mem", O_RDWR | O_SYNC);

	if (fd < 0) {
		kmsg("<3>H71-INIT: /dev/mem open failed (%d), "
		     "watchdog not fed", errno);
		return;
	}
	wdt_regs = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED,
			fd, WDT_BASE & ~4095UL);
	close(fd);
	if (wdt_regs == MAP_FAILED) {
		kmsg("<3>H71-INIT: wdt mmap failed (%d)", errno);
		wdt_regs = NULL;
		return;
	}
	wdt_regs += (WDT_BASE & 4095) / 4;
	{
		/* print everything the LK side left behind - test 46's
		 * LOAD value is what the old pet fed back, and it made
		 * the watchdog near-infinite (no bite in 901 s) */
		unsigned int lo = wdt_regs[WDT_LOAD_LOW / 4];
		unsigned int hi = wdt_regs[WDT_LOAD_HIGH / 4];

		kmsg("<6>H71-INIT: wdt ctrl=%#x load=%#x cnt=%#x raw=%#x",
		     wdt_regs[WDT_CTRL / 4], (hi << 16) | lo,
		     wdt_regs[WDT_CNT_LOW / 4] |
			     (wdt_regs[WDT_CNT_HIGH / 4] << 16),
		     wdt_regs[WDT_INT_RAW / 4]);
	}
	wdt_pet();
}


/*
 * Pet: re-arm with a deterministic 30 s timeout (the same protocol the
 * 4.14 hang_debug feed threads use via start(): rewrite LOAD, wait for
 * the load to land, clear pending reset, re-enable counter+reset).
 * The LOAD value LK left behind is NOT reused: test 46 fed it back and
 * the board then survived 901 s frozen with no bite, so whatever was in
 * the register made the timeout near-infinite.  30 s with 1 s pets
 * gives a wide margin while alive and a fast automatic rescue when a
 * freeze stops the feeding (bite -> reset -> SPL slot a -> rescue ->
 * adb back, no power hold needed).
 */
#define WDT_FEED_SECONDS	30u
#define WDT_FEED_STEPS		(WDT_FEED_SECONDS * 32768u)
#define WDT_CTRL_RUN		0xeu	/* CNT_EN | NEW_VER_EN | RST_EN */

static void wdt_pet(void)
{
	unsigned busy = 0;

	if (!wdt_regs)
		return;
	wdt_regs[WDT_LOCK / 4] = WDT_LOCK_KEY;
	wdt_regs[WDT_LOAD_LOW / 4] = WDT_FEED_STEPS & 0xffffu;
	wdt_regs[WDT_LOAD_HIGH / 4] = WDT_FEED_STEPS >> 16;
	while ((wdt_regs[WDT_INT_RAW / 4] & WDT_LDBUSY_BIT) &&
	       busy++ < 1000)
		;
	/* no INT_CLR write: the vendor feed (start()) reloads LOAD and
	 * re-enables CTRL only - test 46 also wrote RST_CLR here and the
	 * board then never bit, so stick to the proven protocol */
	wdt_regs[WDT_CTRL / 4] = WDT_CTRL_RUN;
	wdt_regs[WDT_LOCK / 4] = 0;
}

/* seconds until the bite, for the park heartbeat */
static unsigned wdt_timeleft(void)
{
	unsigned int cnt;

	if (!wdt_regs)
		return 0;
	cnt = wdt_regs[WDT_CNT_LOW / 4] |
	      (wdt_regs[WDT_CNT_HIGH / 4] << 16);
	return cnt / 32768u;
}

/*
 * IRQ-storm detector: sum every numeric field of /proc/interrupts.
 * A level interrupt nobody handles (the LK-armed watchdog's bark, a
 * PMIC line with no irqchip driver) pins the CPU and freezes the boot
 * with no message at all - that is the current best theory for the
 * 7.1 park-screen freeze.  The sum over one 10 s tick tells us: a
 * storm is > 100k interrupts per tick, a quiet park is a few thousand.
 */
static unsigned long irq_sum(void)
{
	static char buf[32768];
	unsigned long sum = 0, v = 0;
	int i, n, fd;

	fd = open("/proc/interrupts", O_RDONLY);
	if (fd < 0)
		return 0;
	n = (int)read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n <= 0)
		return 0;
	buf[n] = '\0';
	for (i = 0; i < n; i++) {
		if (buf[i] >= '0' && buf[i] <= '9') {
			v = 0;
			while (i < n && buf[i] >= '0' && buf[i] <= '9') {
				v = v * 10 + (unsigned)(buf[i] - '0');
				i++;
			}
			sum += v;
		}
	}
	return sum;
}

/*
 * Collect the whole kernel ring and write it to sysdumpdb (+1 MiB and
 * +2 MiB).  Called once after the wait and then again on every park
 * tick: the re-saves mean the copy on flash holds the LAST state of the
 * ring, so whatever the kernel printed right before a freeze (or the
 * watchdog's bark, or an IRQ-storm message) is on flash even though the
 * phone later reset.
 */
static int save_ring(int logfd, int verbose)
{
	unsigned char hdr[16];
	unsigned char *blob;
	char *buf = NULL;
	size_t total;
	int len = 0, size, n, ok = 0;

	ring_save_errno = 0;
	size = klogctl(10 /* size of the ring */, NULL, 0);
	if (size > 0)
		buf = malloc(size + 1);
	if (buf) {
		n = klogctl(3 /* read all */, buf, size);
		if (n > 0) {
			len = n;
			if (verbose)
				kmsg("<6>H71-INIT: ring is %d bytes", len);
			if (!ring_copy) {
				ring_copy = buf;
				ring_len = len;
				buf = NULL;	/* kept for the serial dump */
			}
		} else {
			free(buf);
			buf = NULL;
		}
	} else if (verbose) {
		kmsg("<3>H71-INIT: ring read failed (%d)", errno);
	}
	if (!ring_copy) {
		ring_save_errno = errno ? errno : EIO;
		return 0;
	}

	/* one sector-aligned write per copy: the header (16 B) and the
	 * ring together, zero-padded to a 4096 multiple - valid on 512-
	 * and 4096-byte disks alike (LOG_OFF1/2 are 1/2 MiB, aligned) */
	total = ((size_t)ring_len + sizeof(hdr) + 4095) & ~(size_t)4095;
	blob = calloc(1, total);
	if (!blob) {
		if (verbose)
			kmsg("<3>H71-INIT: blob alloc failed");
		return 0;
	}
	memcpy(hdr, magic, 8);
	hdr[8] = (ring_len >> 24) & 0xff;
	hdr[9] = (ring_len >> 16) & 0xff;
	hdr[10] = (ring_len >> 8) & 0xff;
	hdr[11] = ring_len & 0xff;
	hdr[12] = hdr[13] = hdr[14] = hdr[15] = 0;
	memcpy(blob, hdr, sizeof(hdr));
	memcpy(blob + sizeof(hdr), ring_copy, ring_len);
	save_phase = 1;
	alarm(5);
	if (pwrite(logfd, blob, total, LOG_OFF1) != (off_t)total) {
		alarm(0);
		save_phase = 0;
		ring_save_errno = errno ? errno : EIO;
		ring_save_phase = 1;
		if (verbose)
			kmsg("<3>H71-INIT: sysdumpdb write 1 failed (%d)",
			     errno);
		free(blob);
		return 0;
	}
	save_phase = 2;
	alarm(5);
	if (pwrite(logfd, blob, total, LOG_OFF2) != (off_t)total) {
		alarm(0);
		save_phase = 0;
		ring_save_errno = errno ? errno : EIO;
		ring_save_phase = 2;
		if (verbose)
			kmsg("<3>H71-INIT: sysdumpdb write 2 failed (%d)",
			     errno);
		free(blob);
		return 0;
	}
	save_phase = 3;
	alarm(5);
	if (fsync(logfd) != 0) {
		alarm(0);
		save_phase = 0;
		ring_save_errno = errno ? errno : EIO;
		ring_save_phase = 3;
		if (verbose)
			kmsg("<3>H71-INIT: sysdumpdb fsync failed (%d)", errno);
		free(blob);
		return 0;
	}
	alarm(0);
	save_phase = 0;
	ok = 1;
	if (verbose)
		kmsg("<6>H71-INIT: saved %d bytes to sysdumpdb "
		     "+0x%x and +0x%x", ring_len,
		     (unsigned)LOG_OFF1, (unsigned)LOG_OFF2);
	free(blob);
	return ok;
}

/*
 * The 7.1 reboot paths are all broken on this phone (the ADI SC2730
 * sequence powers it OFF, PSCI SYSTEM_RESET darkens it), so logsave
 * never reboots: it parks with a heartbeat and the user power-holds
 * (slot b's try is spent, the SPL takes slot a, the rescue restores
 * Android).  While parked the panel keeps showing the log tail.
 *
 * When the ring could not be saved to flash, echo the LAST storage-
 * related ring lines (ufs/scsi/blk) back to /dev/kmsg so they land at
 * the PANEL TAIL - otherwise the UFS probe story has already scrolled
 * off the 39-row text area.
 */
/* does this ring line belong to the storage/UFS story? */
static int interesting(const char *line)
{
	if (strstr(line, "H71-"))
		return 0;
	return strstr(line, "ufs") || strstr(line, "UFS") ||
	       strstr(line, "scsi") || strstr(line, "SCSI") ||
	       strstr(line, "blk") || strstr(line, "sysdumpdb") ||
	       strstr(line, "deferred probe pending") ||
	       strstr(line, "error -517") ||
	       strstr(line, "ap-clk") || strstr(line, "apapb-gate") ||
	       strstr(line, "regulator") || strstr(line, "clk");
}

/*
 * Live ring monitor for the wait window.  A one-shot scan at the end
 * of the wait lost everything: the ring is only 128 KB and the 12 s
 * boot messages were evicted by 32 s (measured on tests 37-39: a scan
 * right after the wait found "0 matching ring lines" while the panel's
 * own history still showed the deferred-probe messages).  Reading as
 * they arrive has no eviction window.
 */
static int monitor_ring(int seconds, int logfd)
{
	char line[512];
	int fd, n = 0, t;
	ssize_t r;

	fd = open("/dev/kmsg", O_RDONLY | O_NONBLOCK);
	if (fd < 0) {
		kmsg("<3>H71-INIT: /dev/kmsg open failed (%d)", errno);
		return 0;
	}
	/* replay what is already buffered */
	lseek(fd, 0, SEEK_SET);
	for (t = 0; t < seconds * 5; t++) {
		while ((r = read(fd, line, sizeof(line) - 1)) > 0) {
			line[r] = '\0';
			if (interesting(line)) {
				n++;
				kmsg("<6>H71-UFS[%d]: %.*s", n, (int)r, line);
			}
		}
		/* save the ring every second: if the kernel freezes in
		 * this window, the copy on flash holds the last second
		 * of kernel output - the freeze moment itself */
		if (logfd >= 0 && t % 5 == 4)
			save_ring(logfd, 0);
		usleep(200000);
	}
	close(fd);
	kmsg("<6>H71-UFS: %d matching lines during the wait", n);
	return n;
}

/* exists? */
static int have(const char *path)
{
	return access(path, F_OK) == 0;
}

static void write_file(const char *path, const char *value)
{
	int fd = open(path, O_WRONLY);
	int n = strlen(value);

	if (fd < 0) {
		kmsg("<3>H71-INIT: write %s failed (%d)", path, errno);
		return;
	}
	if (write(fd, value, n) != n)
		kmsg("<3>H71-INIT: write %s short (%d)", path, errno);
	close(fd);
}

/*
 * Build the debug gadget from configfs: the legacy composite gadget
 * (g_acm_ms) fails to bind on this UDC (-22, its mass-storage function
 * wants a backing file) and the vendor-class g_serial never gets a
 * Windows driver.  configfs + the acm function give a real class-
 * compliant CDC-ACM port the PC enumerates natively, and logsave can
 * do the whole dance with plain syscalls.  The UDC is bound LAST, so
 * the host sees the device only when everything is in place.
 */
static void gadget_setup(void)
{
	char base[64] = "/sys/kernel/config/usb_gadget/h71";
	char path[128];
	char name[64];
	struct dirent *de;
	DIR *d;

	if (mount("configfs", "/sys/kernel/config", "configfs", 0, "")) {
		if (errno != EBUSY) {
			kmsg("<3>H71-INIT: configfs mount failed (%d)", errno);
			return;
		}
	}
	if (mkdir(base, 0755)) {
		kmsg("<3>H71-INIT: gadget mkdir failed (%d)", errno);
		return;
	}
	write_file("/sys/kernel/config/usb_gadget/h71/idVendor", "0x0525");
	write_file("/sys/kernel/config/usb_gadget/h71/idProduct", "0xa4a4");
	write_file("/sys/kernel/config/usb_gadget/h71/bcdUSB", "0x0200");
	write_file("/sys/kernel/config/usb_gadget/h71/bcdDevice", "0x0100");
	snprintf(path, sizeof(path), "%s/strings/0x409", base);
	mkdir(path, 0755);
	write_file("/sys/kernel/config/usb_gadget/h71/strings/0x409/product",
		   "H71 7.1 debug console");
	write_file("/sys/kernel/config/usb_gadget/h71/strings/0x409/serialnumber",
		   "h71serial0");
	snprintf(path, sizeof(path), "%s/functions/acm.0", base);
	if (mkdir(path, 0755)) {
		kmsg("<3>H71-INIT: acm.0 mkdir failed (%d)", errno);
		return;
	}
	snprintf(path, sizeof(path), "%s/configs/c.1", base);
	mkdir(path, 0755);
	snprintf(path, sizeof(path), "%s/configs/c.1/maxpower", base);
	write_file(path, "100");
	snprintf(path, sizeof(path), "/sys/kernel/config/usb_gadget/h71/functions/acm.0");
	if (symlink(path, "/sys/kernel/config/usb_gadget/h71/configs/c.1/acm0")) {
		kmsg("<3>H71-INIT: function symlink failed (%d)", errno);
		return;
	}
	d = opendir("/sys/class/udc");
	if (!d) {
		kmsg("<3>H71-INIT: no /sys/class/udc (%d)", errno);
		return;
	}
	name[0] = '\0';
	while ((de = readdir(d))) {
		if (de->d_name[0] == '.')
			continue;
		snprintf(name, sizeof(name), "%s", de->d_name);
		break;
	}
	closedir(d);
	if (!name[0]) {
		kmsg("<3>H71-INIT: no UDC in /sys/class/udc - musb did not probe");
		return;
	}
	snprintf(path, sizeof(path), "%s/UDC", base);
	write_file(path, name);
	kmsg("<6>H71-INIT: gadget bound to UDC %s - CDC-ACM live", name);
}

/*
 * Hardware X-ray: facts straight from sysfs instead of log archaeology.
 * Answers "did the UFS device probe and bind" without depending on
 * printk at all.
 */
static void xray(void)
{
	char buf[256];
	int fd, n;

	kmsg("<6>H71-XRAY: platform 20200000.ufs %s",
	     have("/sys/bus/platform/devices/20200000.ufs") ? "EXISTS" : "absent");
	kmsg("<6>H71-XRAY: driver bound %s",
	     have("/sys/bus/platform/devices/20200000.ufs/driver") ? "YES" : "NO");
	kmsg("<6>H71-XRAY: ufshcd-sprd driver dir %s",
	     have("/sys/bus/platform/drivers/ufshcd-sprd") ? "EXISTS" : "absent");
	n = 0;
	fd = open("/sys/bus/platform/drivers/ufshcd-sprd", O_RDONLY);
	if (fd >= 0) {
		while ((n = read(fd, buf, sizeof(buf) - 1)) > 0) {
			buf[n] = '\0';
			kmsg("<6>H71-XRAY: ufshcd-sprd binds: %s", buf);
			break;
		}
		close(fd);
	}
	kmsg("<6>H71-XRAY: /dev/sda %s, /dev/block %s",
	     have("/dev/sda") ? "EXISTS" : "absent",
	     have("/dev/block") ? "EXISTS" : "absent");
	kmsg("<6>H71-XRAY: scsi_host %s, block class %s",
	     have("/sys/class/scsi_host") ? "EXISTS" : "absent",
	     have("/sys/class/block") ? "EXISTS" : "absent");
}

/* Find the sysdumpdb partition by parsing the GPT of the first SCSI
 * disk (the UFS device, /dev/sda). Returns an open O_WRONLY fd, or -1.
 *
 * UFS disks have 4096-byte logical sectors: every access on the raw
 * block device must be sector-aligned in offset AND length, or it
 * fails outright (test 41: the 512-byte read at byte offset 512 died
 * and the save failed with the partition plainly there - the X-ray
 * showed /dev/sda EXISTS while this function returned -1). */
static int open_log_partition(void)
{
	static const unsigned char zero[16];
	unsigned char hdr[4096];
	unsigned char *ents;
	uint64_t ent_lba, first_lba, last_lba;
	uint32_t nent, esz;
	size_t total;
	unsigned int ssize;
	int fd, i, n, out = -1;
	char name[40];

	fd = open("/dev/sda", O_RDONLY);
	if (fd < 0) {
		kmsg("<3>H71-INIT: open /dev/sda failed (%d)", errno);
		return -1;
	}
	if (ioctl(fd, BLKSSZGET, &ssize) != 0 || ssize < 512 ||
	    ssize > sizeof(hdr)) {
		kmsg("<3>H71-INIT: BLKSSZGET failed (%d), assuming 512",
		     errno);
		ssize = 512;
	}
	/* GPT header is LBA 1 - one sector-aligned read */
	if (pread(fd, hdr, ssize, (off_t)ssize) != (off_t)ssize ||
	    memcmp(hdr, "EFI PART", 8)) {
		kmsg("<3>H71-INIT: GPT header read failed (%d)", errno);
		close(fd);
		return -1;
	}
	memcpy(&ent_lba, hdr + 72, 8);
	memcpy(&nent, hdr + 80, 4);
	memcpy(&esz, hdr + 84, 4);
	if (!nent || esz < 128 || esz > sizeof(hdr) || nent > 512) {
		kmsg("<3>H71-INIT: GPT shape invalid (nent %u esz %u)",
		     nent, esz);
		close(fd);
		return -1;
	}
	total = ((size_t)nent * esz + ssize - 1) & ~(size_t)(ssize - 1);
	ents = malloc(total);
	if (!ents) {
		close(fd);
		return -1;
	}
	/* the whole entry array in one sector-aligned read */
	if (pread(fd, ents, total, (off_t)ent_lba * ssize) != (off_t)total) {
		kmsg("<3>H71-INIT: GPT entries read failed (%d)", errno);
		free(ents);
		close(fd);
		return -1;
	}
	for (i = 0; i < (int)nent; i++) {
		const unsigned char *ent = ents + (size_t)i * esz;

		if (!memcmp(ent, zero, 16))	/* unused entry */
			continue;
		memcpy(&first_lba, ent + 32, 8);
		memcpy(&last_lba, ent + 40, 8);
		for (n = 0; n < 36; n++) {
			unsigned char lo = ent[56 + n * 2];
			unsigned char hi = ent[57 + n * 2];

			if (!lo && !hi)
				break;
			name[n] = lo;		/* UTF16LE, ASCII names */
		}
		name[n] = '\0';
		while (n > 0 && name[n - 1] == ' ')	/* GPT space padding */
			name[--n] = '\0';
		if (!strcmp(name, "sysdumpdb") && last_lba > first_lba) {
			char node[32];

			snprintf(node, sizeof(node), "/dev/sda%d", i + 1);
			out = open(node, O_WRONLY);
			if (out >= 0)
				kmsg("<6>H71-INIT: sysdumpdb is %s "
				     "(%llu blocks)", node,
				     (unsigned long long)(last_lba -
							 first_lba + 1));
			else
				kmsg("<3>H71-INIT: open %s failed (%d)",
				     node, errno);
			break;
		}
	}
	free(ents);
	close(fd);
	return out;
}

/*
 * Continuous saver: a forked child re-saves the ring every second so
 * the copy on flash holds the LAST second of kernel output before any
 * freeze.  It is a separate process on purpose - test 46 showed a
 * re-save failing once and the boot freezing shortly after; if the UFS
 * write itself hangs, the parent keeps petting the watchdog, painting
 * the park screen and serving the serial shell, and the failure mode
 * (kernel-wide freeze vs. storage wedge) becomes distinguishable.
 * Prints only on state change, so a healthy saver is silent.
 */
static void run_saver(int logfd)
{
	int ok = -1;

	for (;;) {
		int now = save_ring(logfd, 0);

		if (now != ok) {
			if (now)
				kmsg("<6>H71-INIT: saver ok (%d B/s)",
				     ring_len);
			else
				kmsg("<3>H71-INIT: saver FAILING (errno %d "
				     "at phase %d: 1 pwrite, 2 pwrite2, "
				     "3 fsync)",
				     ring_save_errno, ring_save_phase);
			ok = now;
		}
		sleep(1);
	}
}

int main(void)
{
	int logfd;
	struct sigaction sa;

	/* SIGALRM interrupts a wedged UFS write instead of hanging the
	 * (parent or child) caller for ever - the second block write to
	 * the device reliably wedges the queue (tests 46/47) */
	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = save_alarm_handler;
	sigaction(SIGALRM, &sa, NULL);

	kmsg("<6>H71-INIT: logsave up (pid %d, waiting %d s, ring monitor on)",
	     (int)getpid(), WAIT_SECONDS);

	/* mounts first: the monitor's 1 s ring saves and the watchdog
	 * feed both need them */
	if (access("/dev/sda", F_OK) != 0) {
		if (mount("devtmpfs", "/dev", "devtmpfs", 0, "") == 0)
			kmsg("<6>H71-INIT: devtmpfs mounted on /dev");
		else
			kmsg("<3>H71-INIT: devtmpfs mount failed (%d), "
			     "trying anyway", errno);
	}
	/* sysfs for the X-ray: /sys/bus/platform/... - the kernel does not
	 * automount it either (measured on test 40: every H71-XRAY line
	 * said "absent" because /sys was an empty directory) */
	if (access("/sys/bus", F_OK) != 0) {
		if (mount("sysfs", "/sys", "sysfs", 0, "") == 0)
			kmsg("<6>H71-INIT: sysfs mounted on /sys");
		else
			kmsg("<3>H71-INIT: sysfs mount failed (%d), "
			     "trying anyway", errno);
	}
	/* /proc for the serial debug shell (dmesg, cmdline, partitions) */
	if (access("/proc/cmdline", F_OK) != 0 &&
	    mount("proc", "/proc", "proc", 0, "") == 0)
		kmsg("<6>H71-INIT: proc mounted on /proc");

	wdt_init();
	gadget_setup();
	logfd = open_log_partition();
	if (logfd < 0)
		logfd = open("/dev/block/by-name/sysdumpdb", O_WRONLY);
	if (logfd < 0)
		kmsg("<3>H71-INIT: sysdumpdb not found - ring not saved "
		     "to flash");

	monitor_ring(WAIT_SECONDS, logfd);
	kmsg("<6>H71-INIT: wait done, collecting the kernel ring");
	if (logfd >= 0) {
		save_ring(logfd, 1);
		/* ground truth for every DT question: the merged DTB
		 * exactly as the kernel consumed it (the LK dtbo merge
		 * output), from /sys/firmware/fdt -> sysdumpdb +8 MiB */
		{
			int ffd = open("/sys/firmware/fdt", O_RDONLY);
			struct stat st;

			if (ffd < 0) {
				kmsg("<3>H71-INIT: /sys/firmware/fdt open "
				     "failed (%d)", errno);
			} else if (fstat(ffd, &st) != 0 || st.st_size <= 0 ||
				   st.st_size > (off_t)DTB_MAX) {
				kmsg("<3>H71-INIT: fdt stat failed (%d, %ld)",
				     errno, ffd >= 0 ? (long)st.st_size : -1);
				close(ffd);
			} else {
				size_t dtotal = ((size_t)st.st_size + 16 + 4095) &
					~(size_t)4095;
				unsigned char *dblb = calloc(1, dtotal);

				if (!dblb) {
					close(ffd);
				} else if (read(ffd, dblb + 16,
					       (size_t)st.st_size) !=
					   (ssize_t)st.st_size) {
					kmsg("<3>H71-INIT: fdt read failed "
					     "(%d)", errno);
					free(dblb);
					close(ffd);
				} else {
					memcpy(dblb, DTB_MAGIC, 8);
					dblb[8] = (st.st_size >> 24) & 0xff;
					dblb[9] = (st.st_size >> 16) & 0xff;
					dblb[10] = (st.st_size >> 8) & 0xff;
					dblb[11] = st.st_size & 0xff;
					dblb[12] = dblb[13] = dblb[14] =
						dblb[15] = 0;
					if (pwrite(logfd, dblb, dtotal,
						   LOG_OFF3) == (off_t)dtotal) {
						kmsg("<6>H71-INIT: merged dtb "
						     "%ld bytes to sysdumpdb "
						     "+0x%x",
						     (long)st.st_size,
						     (unsigned)LOG_OFF3);
					} else {
						kmsg("<3>H71-INIT: fdt write "
						     "failed (%d)", errno);
					}
					free(dblb);
					close(ffd);
				}
			}
		}
	}

	/* no reboot: every 7.1 reset path on this phone is broken (ADI
	 * powers it off, PSCI darkens it).  Keep the LK-armed watchdog
	 * fed while parked; if the kernel freezes the bite resets the
	 * board, the SPL takes slot a and the rescue restores Android
	 * without a power hold. */
	xray();
	kmsg("<6>H71-INIT: PARKED - power-hold to recover");
	serial_try();
	shell_try();
	if (logfd >= 0) {
		pid_t sp = fork();

		if (sp == 0) {
			if (ser_fd >= 0)
				close(ser_fd);
			run_saver(logfd);
			_exit(0);
		}
		if (sp > 0)
			kmsg("<6>H71-INIT: saver pid %d (1 s ring saves)",
			     (int)sp);
	}
	for (;;) {
		int tick;

		for (tick = 0; tick < 10; tick++) {
			unsigned long isum;

			sleep(1);
			serial_try();	/* the gadget may bind late */
			shell_try();
			wdt_pet();
			isum = irq_sum();
			if (isum && irq_last && isum > irq_last + 100000)
				kmsg("<3>H71-INIT: IRQ STORM +%lu in 1 s",
				     isum - irq_last);
			irq_last = isum;
		}
		kmsg("<4>H71-INIT: parked, wdt %u s left", wdt_timeleft());
		/* once the shell runs, keep the wire quiet for it */
		if (!shell_started)
			serial_printf("H71-INIT: parked, wdt %u s left\r\n",
				      wdt_timeleft());
	}
	return 0;
}
