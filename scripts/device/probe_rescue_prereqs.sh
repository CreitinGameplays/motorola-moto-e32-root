#!/system/bin/sh
# Prereqs for a boot_a "rescue" image: an unused 100 MiB cache partition, stable
# block dev numbers, and the current BCB (slot b active) to replay later.
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"

echo "=== cache usage ==="
mount 2>/dev/null | grep -i cache
grep -w cache /proc/mounts 2>/dev/null
getprop 2>/dev/null | grep -i -E 'cache|recovery' | head -20

echo "=== block dev numbers (DEVNAME DEVNUM) ==="
for b in sda4 sda11 sda40 sda41 sda50 sda58 sda68; do
    printf "%-8s %s\n" "$b" "$(cat /sys/class/block/$b/dev 2>/dev/null)"
done

echo "=== cache first bytes (expect zero if unused) ==="
dd if=/dev/block/by-name/cache bs=4096 count=1 2>/dev/null | od -An -tx1 -N32

echo "=== misc BCB (0x800) ==="
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=64 2>/dev/null | od -An -tx1
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=4 2>/dev/null

echo "=== slot state ==="
getprop ro.boot.slot_suffix
getprop ro.boot.verifiedbootstate

echo "=== boot_a current image header ==="
dd if=/dev/block/by-name/boot_a bs=4096 count=1 2>/dev/null | od -An -c -N64
echo "=== kernel cmdline on boot_a header (0x40) ==="
dd if=/dev/block/by-name/boot_a bs=1 skip=64 count=64 2>/dev/null