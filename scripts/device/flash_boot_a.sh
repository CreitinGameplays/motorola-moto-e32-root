#!/system/bin/sh
# Write the custom kernel image to the INACTIVE slot boot_a and verify it.
# The active stock boot_b is not touched.
#
# Usage: sh flash_boot_a.sh <image> <expected-sha256>
set -u

img="${1:-/data/local/tmp/boot_custom.img}"
want="${2:-}"
blocks=8611          # 35270656 / 4096

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >/data/local/tmp/kroot_write_$i.log 2>&1
    [ "$(id -u)" = "0" ] && break
    i=$((i + 1))
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

got=$(sha256sum "$img" | awk '{print $1}')
echo "image : $img"
echo "sha256: $got"
[ -n "$want" ] && [ "$got" != "$want" ] && { echo "IMAGE HASH MISMATCH, aborting"; exit 1; }

echo "--- writing ---"
dd if="$img" of=/dev/block/by-name/boot_a bs=4096 count=$blocks 2>&1
sync

echo "--- reading back ---"
back=$(dd if=/dev/block/by-name/boot_a bs=4096 count=$blocks 2>/dev/null | sha256sum | awk '{print $1}')
echo "readback: $back"
if [ "$back" = "$got" ]; then
    echo "VERIFY OK"
else
    echo "VERIFY MISMATCH"
    exit 1
fi