#!/system/bin/sh
# Pre-flight before writing boot_a:
#   - gain root (same shell!)
#   - report partition sizes
#   - sha256 the CURRENT boot_a so it can be compared with the verified backup
set -u

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >/data/local/tmp/kroot_pre_$i.log 2>&1
    [ "$(id -u)" = "0" ] && break
    i=$((i + 1))
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "--- sizes ---"
for p in boot_a boot_b; do
    echo "$p: $(cat /sys/class/block/$(basename "$(readlink -f /dev/block/by-name/$p)" 2>/dev/null)/size 2>/dev/null) sectors"
done
echo "by-name links:"
ls -l /dev/block/by-name/boot_a /dev/block/by-name/boot_b

echo "--- sha256 of current boot_a (stock, for backup comparison) ---"
dd if=/dev/block/by-name/boot_a bs=1048576 2>/dev/null | sha256sum

echo "--- current slot ---"
getprop ro.boot.slot_suffix