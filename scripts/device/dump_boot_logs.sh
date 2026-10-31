#!/system/bin/sh
# Collect every boot-time log the phone kept from the last boot attempt.
# Run as root (mali_kroot first).  Reads only; writes only to /data/local/tmp.

echo "=== boot reason history ==="
getprop sys.boot.reason.history
getprop sys.boot.reason
getprop ro.boot.slot_suffix

echo
echo "=== pstore ==="
ls -l /sys/fs/pstore/
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    echo "--- $f ---"
    cat "$f"
    echo
done

echo
echo "=== misc A/B block ==="
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1

echo
echo "=== this boot: dmesg head (first 25 lines) ==="
dmesg | head -25

echo
echo "=== dump uboot_log ==="
dd if=/dev/block/by-name/uboot_log of=/data/local/tmp/uboot_log_after.img bs=1M 2>&1 | tail -1
echo "done"