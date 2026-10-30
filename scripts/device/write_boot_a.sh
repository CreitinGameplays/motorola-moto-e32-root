#!/system/bin/sh
# Write a boot image to boot_a (the test slot) and verify the readback.
# Usage: sh write_boot_a.sh /data/local/tmp/<image>
src="$1"
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
[ -f "$src" ] || { echo "missing $src"; exit 1; }

size=$(wc -c < "$src")
echo "source $size bytes  $(sha256sum "$src" | awk '{print $1}')"
if [ "$size" != "67108864" ]; then echo "refusing: image is not 64 MiB"; exit 1; fi

dd if="$src" of=/dev/block/by-name/boot_a bs=1048576 count=64 2>&1 | tail -1
sync
echo "boot_a $(sha256sum /dev/block/by-name/boot_a | awk '{print $1}')"
echo "boot_b $(sha256sum /dev/block/by-name/boot_b | awk '{print $1}')  (must stay ccd0faff...)"