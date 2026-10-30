#!/system/bin/sh
# Write a boot image to the INACTIVE slot boot_a and verify it.
# The active stock boot_b is not touched.
#
# The block count is derived from the image size. A 64 MiB AVB-signed image
# therefore overwrites the whole partition, so no stale bytes from the previous
# content survive past a shorter payload.
#
# Usage: sh flash_boot_a.sh <image> <expected-sha256>
set -u

img="${1:-/data/local/tmp/boot_custom.img}"
want="${2:-}"

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >/data/local/tmp/kroot_write_$i.log 2>&1
    [ "$(id -u)" = "0" ] && break
    i=$((i + 1))
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

got=$(sha256sum "$img" | awk '{print $1}')
size=$(wc -c < "$img")
blocks=$((size / 4096))
echo "image : $img"
echo "size  : $size bytes ($blocks x 4096)"
echo "sha256: $got"
[ -n "$want" ] && [ "$got" != "$want" ] && { echo "IMAGE HASH MISMATCH, aborting"; exit 1; }
[ $((blocks * 4096)) -ne "$size" ] && { echo "size not a multiple of 4096, aborting"; exit 1; }
[ "$blocks" -le 16384 ] || { echo "image larger than 64 MiB, aborting"; exit 1; }

echo "--- target ---"
echo "boot_a -> $(readlink -f /dev/block/by-name/boot_a)"
echo "current slot: $(getprop ro.boot.slot_suffix)"

echo "--- writing $blocks blocks ---"
dd if="$img" of=/dev/block/by-name/boot_a bs=4096 count=$blocks 2>&1
sync

echo "--- reading back $blocks blocks ---"
back=$(dd if=/dev/block/by-name/boot_a bs=4096 count=$blocks 2>/dev/null | sha256sum | awk '{print $1}')
echo "readback: $back"
if [ "$back" = "$got" ]; then
    echo "VERIFY OK"
else
    echo "VERIFY MISMATCH"
    exit 1
fi