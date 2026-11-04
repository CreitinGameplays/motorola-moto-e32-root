#!/system/bin/sh
# Post-recovery diagnostics after the bootbar-kernel hang:
#  - pstore console-ramoops tail (the hung kernel's last words)
#  - slot + boot state
echo "=== boot state ==="
uname -r
getprop sys.boot_completed
getprop ro.boot.slot_suffix

echo "=== pstore files ==="
ls -la /sys/fs/pstore/ 2>/dev/null

echo "=== ramoops console tail (last 3 KB) ==="
tail -c 3072 /sys/fs/pstore/console-ramoops-0 2>/dev/null

echo "=== ramoops dmesg tail ==="
tail -c 2048 /sys/fs/pstore/dmesg-ramoops-0 2>/dev/null
