#!/system/bin/sh
# Write a boot image to boot_b and verify the readback.
# Usage: sh write_boot_b.sh /data/local/tmp/<image>
# Safety net: boot_a holds the restore rescue. If the new boot_b does not boot,
# force off -> Vol Down + Power -> fastboot set_active a -> the rescue rewrites
# boot_b from its embedded stock copy and returns to slot _b.
src="$1"
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
[ -f "$src" ] || { echo "missing $src"; exit 1; }

size=$(wc -c < "$src")
echo "source $size bytes  $(sha256sum "$src" | awk '{print $1}')"
if [ "$size" != "67108864" ]; then echo "refusing: image is not 64 MiB"; exit 1; fi
echo "boot_a $(sha256sum /dev/block/by-name/boot_a | awk '{print $1}')  (must be fc3ca0ef...44c0)"

# keep the current boot_b on /data before touching it (one-shot belt and braces)
dd if=/dev/block/by-name/boot_b of=/data/local/tmp/boot_b.prev.img bs=1048576 count=64 2>&1 | tail -1
echo "prev  $(sha256sum /data/local/tmp/boot_b.prev.img | awk '{print $1}')"

dd if="$src" of=/dev/block/by-name/boot_b bs=1048576 count=64 2>&1 | tail -1
sync
echo "boot_b $(sha256sum /dev/block/by-name/boot_b | awk '{print $1}')"
echo "expect $(sha256sum "$src" | awk '{print $1}')"