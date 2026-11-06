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
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/ioctl.h>
#include <sys/stat.h>

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
static int monitor_ring(int seconds)
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
	kmsg("<6>H71-XRAY: ufs-sprd driver dir %s",
	     have("/sys/bus/platform/drivers/ufs-sprd") ? "EXISTS" : "absent");
	n = 0;
	fd = open("/sys/bus/platform/drivers/ufs-sprd", O_RDONLY);
	if (fd >= 0) {
		while ((n = read(fd, buf, sizeof(buf) - 1)) > 0) {
			buf[n] = '\0';
			kmsg("<6>H71-XRAY: ufs-sprd binds: %s", buf);
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

int main(void)
{
	char *buf = NULL;
	int logfd, len = 0, n, saved = 0;

	kmsg("<6>H71-INIT: logsave up (pid %d, waiting %d s, ring monitor on)",
	     (int)getpid(), WAIT_SECONDS);
	monitor_ring(WAIT_SECONDS);
	kmsg("<6>H71-INIT: wait done, collecting the kernel ring");

	/* make sure devtmpfs nodes exist (kernel may not automount it) */
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

	logfd = open_log_partition();
	if (logfd < 0)
		logfd = open("/dev/block/by-name/sysdumpdb", O_WRONLY);
	if (logfd < 0) {
		kmsg("<3>H71-INIT: sysdumpdb not found - ring not saved "
		     "to flash");
	} else {
		len = klogctl(10 /* size of the ring */, NULL, 0);
		if (len > 0)
			buf = malloc(len + 1);
		if (buf) {
			n = klogctl(3 /* read all */, buf, len);
			if (n > 0) {
				len = n;
				kmsg("<6>H71-INIT: ring is %d bytes", len);
			} else {
				free(buf);
				buf = NULL;
			}
		}
		if (buf) {
			unsigned char hdr[16];
			/* one sector-aligned write per copy: the header
			 * (16 B) and the ring together, zero-padded to a
			 * 4096 multiple - valid on 512- and 4096-byte
			 * disks alike (LOG_OFF1/2 are 1/2 MiB, aligned) */
			size_t total = ((size_t)len + sizeof(hdr) + 4095) &
				~(size_t)4095;
			unsigned char *blob = calloc(1, total);

			memcpy(hdr, magic, 8);
			hdr[8] = (len >> 24) & 0xff;
			hdr[9] = (len >> 16) & 0xff;
			hdr[10] = (len >> 8) & 0xff;
			hdr[11] = len & 0xff;
			hdr[12] = hdr[13] = hdr[14] = hdr[15] = 0;

			if (blob) {
				memcpy(blob, hdr, sizeof(hdr));
				memcpy(blob + sizeof(hdr), buf, len);
				if (pwrite(logfd, blob, total, LOG_OFF1) ==
					    (off_t)total &&
				    pwrite(logfd, blob, total, LOG_OFF2) ==
					    (off_t)total) {
					fsync(logfd);
					saved = 1;
					kmsg("<6>H71-INIT: saved %d bytes to "
					     "sysdumpdb +0x%x and +0x%x", len,
					     (unsigned)LOG_OFF1,
					     (unsigned)LOG_OFF2);
				} else {
					kmsg("<3>H71-INIT: sysdumpdb write "
					     "failed (%d)", errno);
				}
			} else {
				kmsg("<3>H71-INIT: blob alloc failed");
			}
			free(blob);
		} else {
			kmsg("<3>H71-INIT: ring read failed (%d)", errno);
		}
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
		close(logfd);
	}

	/* no reboot: every 7.1 reset path on this phone is broken (ADI
	 * powers it off, PSCI darkens it).  Report the storage story on
	 * the panel tail, then park - the user power-holds, the SPL takes
	 * slot a and the rescue restores Android. */
	xray();
	kmsg("<6>H71-INIT: PARKED - power-hold to recover");
	for (;;) {
		sleep(10);
		kmsg("<4>H71-INIT: parked, ring %s",
		     saved ? "SAVED to sysdumpdb" : "NOT saved");
	}
	return 0;
}
