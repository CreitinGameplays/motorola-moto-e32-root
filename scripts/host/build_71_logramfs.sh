#!/bin/sh
# Build the 7.1 flash-test initramfs: a tiny cpio.gz whose /init is
# scripts/host/logsave.c (dump the kernel ring into the sysdumpdb
# partition, then reboot into the boot_a rescue path).
#
# Run on the VPS (needs gcc + aarch64-linux-gnu-gcc and the kernel's
# gen_init_cpio host tool):
#   ./scripts/host/build_71_logramfs.sh [workdir]
#
# Output: <workdir>/71_logramfs.cpio.gz (a few kB)
set -eu

WORK="${1:-$HOME/71logramfs}"
HERE="$(cd "$(dirname "$0")" && pwd)"
KROOT="${KROOT:-$HOME/linux-ums9230}"

mkdir -p "$WORK"
cd "$WORK"

[ -f "$HERE/logsave.c" ] || { echo "missing: $HERE/logsave.c" >&2; exit 1; }

if [ ! -x gen_init_cpio ]; then
	gcc -O2 -o gen_init_cpio "$KROOT/usr/gen_init_cpio.c"
fi

# static aarch64 busybox: gives the /init a real shell on the USB serial
# line once the g_serial gadget binds (busybox-static apk from Alpine;
# musl static-pie, runs fine as an initramfs binary).
BB="$WORK/bin/busybox.static"
if [ ! -x "$BB" ]; then
	mkdir -p "$WORK/bin" "$WORK/bb"
	curl -s -o "$WORK/bb/busybox.apk" \
		https://dl-cdn.alpinelinux.org/alpine/latest-stable/main/aarch64/busybox-static-1.37.0-r31.apk
	tar -xzf "$WORK/bb/busybox.apk" -C "$WORK/bb"
	cp "$WORK/bb/bin/busybox.static" "$BB"
	chmod +x "$BB"
fi
ls -l "$BB"

aarch64-linux-gnu-gcc -static -Os -Wall -o init "$HERE/logsave.c"
aarch64-linux-gnu-strip init
ls -l init

# the Novatek NT36xxx touch controller firmware: the driver loads it with
# request_firmware("novatek_ts_fw.bin"), so it has to be in the initramfs
# (the vendor kernel gets it from /vendor/firmware on Android).
FW_DIR="${FW_DIR:-$HOME/fw}"
for f in novatek_ts_fw.bin novatek_ts_mp.bin; do
	[ -f "$FW_DIR/$f" ] || continue
done

# applet symlinks the debug shell gets out of the box (deliberately no
# reboot/poweroff: the 7.1 reset paths are broken and logsave must park)
APPLETS="sh ash echo printf cat ls ln rm cp mv mkdir rmdir touch mount
umount dmesg grep sed head tail cut wc hexdump od dd devmem sleep ps kill
uname id sync chmod find vi less"

{
	cat <<EOF
dir /dev 0755 0 0
nod /dev/console 0600 0 0 c 5 1
nod /dev/kmsg 0600 0 0 c 1 11
nod /dev/null 0666 0 0 c 1 3
nod /dev/zero 0666 0 0 c 1 5
nod /dev/tty 0666 0 0 c 5 0
nod /dev/mem 0600 0 0 c 1 1
dir /sys 0755 0 0
dir /proc 0755 0 0
dir /bin 0755 0 0
dir /lib 0755 0 0
dir /lib/firmware 0755 0 0
file /init $PWD/init 0755 0 0
file /bin/busybox $BB 0755 0 0
EOF
	for f in novatek_ts_fw.bin novatek_ts_mp.bin; do
		if [ -f "$FW_DIR/$f" ]; then
			printf 'file /lib/firmware/%s %s/%s 0644 0 0\n' "$f" "$FW_DIR" "$f"
		fi
	done
	for a in $APPLETS; do
		printf 'slink /bin/%s busybox 0777 0 0\n' "$a"
	done
} > cpio.list

./gen_init_cpio cpio.list > 71_logramfs.cpio
gzip -9 -c 71_logramfs.cpio > 71_logramfs.cpio.gz
rm -f 71_logramfs.cpio
sha256sum 71_logramfs.cpio.gz
ls -l 71_logramfs.cpio.gz
