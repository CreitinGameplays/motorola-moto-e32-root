#!/system/bin/sh
# Pull the bootloader log after a 'fastboot boot' attempt and show its tail.
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }
u=$(readlink -f /dev/block/by-name/uboot_log)
dd if="$u" of=/data/local/tmp/uboot_log2.img bs=4096 2>&1 | tail -1
ls -l /data/local/tmp/uboot_log2.img