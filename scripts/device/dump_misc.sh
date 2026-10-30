#!/system/bin/sh
# Dump misc (BCB + Android slot metadata) and the full boot-reason properties.
set -u
for i in 1 2 3 4 5 6; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== full cmdline ==="
cat /proc/cmdline
echo
echo "=== boot reason properties (full) ==="
getprop persist.sys.boot.reason.history
getprop ro.boot.bootreason
getprop sys.rescue_boot_count
getprop persist.device_config.attempted_boot_count
echo
echo "=== misc partition (first 8 KiB: BCB + slot metadata) ==="
dd if=/dev/block/by-name/misc of=/data/local/tmp/misc_first8k.img bs=4096 count=2 2>&1 | tail -1
ls -l /data/local/tmp/misc_first8k.img
echo "--- printable ---"
strings -n 3 /data/local/tmp/misc_first8k.img | head -20
echo
echo "=== boot_a header sanity (what we wrote) ==="
dd if=/dev/block/by-name/boot_a of=/data/local/tmp/boot_a_hdr.img bs=4096 count=1 2>&1 | tail -1
strings -n 4 /data/local/tmp/boot_a_hdr.img | head -5