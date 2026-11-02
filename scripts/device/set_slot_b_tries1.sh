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
# Must be run as root (the host wrapper does `su -c 'sh ...'`). It deliberately
# does not invoke the exploit-based root helper: that one leaves SELinux
# permissive, which spoils the integrity measurements the test boot is judged
# on, so persistent Magisk su is required instead.
#
# Prints AB_TRIES1_OK only after reading the block back and matching it
# byte-for-byte; the host wrapper refuses to reboot without it.
#
# Usage: su -c 'sh /data/local/tmp/set_slot_b_tries1.sh'
B64="X2IAAEJDQUIBAgAAjgAfAAAAAAAAAAAAAAAAALGCpSA="
EXPECT="5f62000042434142010200008e001f00000000000000000000000000b182a520"

if [ "$(id -u)" != "0" ]; then
    echo "AB_TRIES1_FAIL not root (uid=$(id -u))"
    exit 1
fi
echo "uid=$(id -u)"

echo "before:"
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1

echo "$B64" | base64 -d > /data/local/tmp/ab_tries1.bin
SIZE=$(wc -c < /data/local/tmp/ab_tries1.bin)
echo "block $SIZE bytes"
if [ "$SIZE" != "32" ]; then
    echo "AB_TRIES1_FAIL bad block size"
    exit 1
fi

dd if=/data/local/tmp/ab_tries1.bin of=/dev/block/by-name/misc bs=1 seek=2048 conv=notrunc 2>/dev/null
sync

echo "after:"
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1

GOT=$(dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1 | tr -d ' \n')
if [ "$GOT" != "$EXPECT" ]; then
    echo "AB_TRIES1_FAIL read-back $GOT"
    exit 1
fi
echo "AB_TRIES1_OK"
