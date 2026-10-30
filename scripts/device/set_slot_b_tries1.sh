#!/system/bin/sh
# Set the A/B block so slot b gets exactly ONE boot attempt:
#   slot a = priority 14, tries 0, successful 1 (0x008e)
#   slot b = priority 15, tries 1, successful 0 (0x001f)
# crc32_le(bytes[0..27]) = 0x20a582b1
#
# This u-boot decrements tries_remaining on a boot attempt (measured: slot a
# went 1 -> 0), so if the test kernel dies the next boot should find slot b
# unbootable and fall back to slot a, the rescue - no Vol Down timing needed.
# A successful boot lets Android's boot_control restore the normal state.
#
# Usage: sh /data/local/tmp/set_slot_b_tries1.sh
B64="X2IAAEJDQUIBAgAAjgAfAAAAAAAAAAAAAAAAALGCpSA="
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"

echo "before:"
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1

echo "$B64" | base64 -d > /data/local/tmp/ab_tries1.bin
echo "block $(wc -c < /data/local/tmp/ab_tries1.bin) bytes"
[ "$(wc -c < /data/local/tmp/ab_tries1.bin)" = "32" ] || { echo "bad block size"; exit 1; }

dd if=/data/local/tmp/ab_tries1.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc 2>&1 | tail -1
sync
echo "after:"
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1