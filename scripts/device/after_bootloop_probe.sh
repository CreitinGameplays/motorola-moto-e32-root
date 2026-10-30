#!/system/bin/sh
# After the stock-kernel-in-our-container bootloop: what does the device remember?
# Reads only; copies the bootloader log to /data/local/tmp for pulling.
set -u
for i in 1 2 3 4 5 6; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== slot / boot state ==="
getprop ro.boot.slot_suffix
getprop sys.boot_completed
cat /proc/uptime
echo
echo "=== /sys/fs/pstore (records survive a warm reset) ==="
ls -la /sys/fs/pstore/ 2>&1
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    echo "--- $f ($(wc -c < "$f") bytes)"
    head -c 1200 "$f" | tr -d '\000'
    echo
done
echo
echo "=== partitions of interest ==="
for p in uboot_log sysdumpdb boot_a boot_b misc; do
    l=$(readlink -f "/dev/block/by-name/$p" 2>/dev/null)
    [ -n "$l" ] && echo "$p -> $l  $(blockdev --getsize64 "$l" 2>/dev/null) bytes"
done
echo
echo "=== last-reset / boot reason in cmdline ==="
tr ' ' '\n' < /proc/cmdline | grep -i -E 'reset|reason|slot|boot' | head -20
echo
echo "=== uboot_log: copy for pulling ==="
u=$(readlink -f /dev/block/by-name/uboot_log 2>/dev/null)
if [ -n "$u" ]; then
    sz=$(blockdev --getsize64 "$u" 2>/dev/null)
    echo "uboot_log size: $sz"
    dd if="$u" of=/data/local/tmp/uboot_log.img bs=4096 2>&1 | tail -1
    ls -l /data/local/tmp/uboot_log.img
    echo "--- printable strings (tail) ---"
    strings /data/local/tmp/uboot_log.img 2>/dev/null | tail -40
else
    echo "no uboot_log partition"
fi
echo
echo "=== sysdumpdb: nonzero size + banner ==="
s=$(readlink -f /dev/block/by-name/sysdumpdb 2>/dev/null)
if [ -n "$s" ]; then
    sz=$(blockdev --getsize64 "$s" 2>/dev/null); echo "size: $sz"
    dd if="$s" bs=4096 2>/dev/null | tr -d '\000' | wc -c
    strings -n 8 "$s" 2>/dev/null | grep -i -E 'kernel_crash|watchdog|panic|sysdump_panic|rst int' | head -20
fi