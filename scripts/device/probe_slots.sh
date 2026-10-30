#!/system/bin/sh
# Is slot a a bootable Android slot at all? Read-only.
set -u
for i in 1 2 3 4 5 6; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== partition sizes ==="
for p in boot_a boot_b system_a system_b vendor_a vendor_b product_a product_b vbmeta_a vbmeta_b super; do
    l=$(readlink -f "/dev/block/by-name/$p" 2>/dev/null)
    [ -n "$l" ] && printf '%-10s %s %s\n' "$p" "$l" "$(blockdev --getsize64 "$l" 2>/dev/null)"
done

echo
echo "=== misc: BCB + slot metadata (first 8 KiB) ==="
dd if=/dev/block/by-name/misc of=/data/local/tmp/misc8k.img bs=4096 count=2 2>&1 | tail -1
od -A d -t x1z /data/local/tmp/misc8k.img 2>/dev/null | head -20
echo "--- offset 2048 (slot metadata structs) ---"
od -A d -t x4 -j 2048 -N 64 /data/local/tmp/misc8k.img 2>/dev/null

echo
echo "=== system_a / system_b first 64 KiB (magic check) ==="
for s in system_a system_b; do
    l=$(readlink -f "/dev/block/by-name/$s" 2>/dev/null)
    [ -n "$l" ] || { echo "$s missing"; continue; }
    dd if="$l" of=/data/local/tmp/${s}_head.img bs=4096 count=16 2>/dev/null
    echo "--- $s ($(blockdev --getsize64 "$l") bytes)"
    echo "first 8 bytes: $(dd if=$l bs=8 count=1 2>/dev/null | od -A n -t x1 | head -1)"
    # ext4 superblock magic sits at offset 0x438 (1080)
    dd if="$l" bs=1 skip=1080 count=2 2>/dev/null | od -A n -t x1 | sed 's/^/  ext4 magic bytes: /'
    strings -n 6 /data/local/tmp/${s}_head.img 2>/dev/null | head -5
    echo "  nonzero bytes in first 64 KiB: $(tr -d '\000' < /data/local/tmp/${s}_head.img | wc -c)"
done