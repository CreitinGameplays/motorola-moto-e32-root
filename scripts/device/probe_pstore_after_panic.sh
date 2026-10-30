#!/system/bin/sh
# After the deliberate sysrq-c panic: did anything capture the crash?
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== /sys/fs/pstore (warm reset keeps DRAM) ==="
ls -la /sys/fs/pstore/ 2>&1
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    echo "--- $f ($(wc -c < "$f") bytes)"
    head -c 2500 "$f"
    echo
done

echo
echo "=== panic cause recorded in ramoops? (reason header) ==="
for f in /sys/fs/pstore/dmesg-ramoops-*; do
    [ -f "$f" ] || continue
    echo "--- $f"
    head -c 300 "$f" | tr -d '\000'
    echo
done

echo
echo "=== sysdumpdb size ==="
ls -l /dev/block/by-name/sysdumpdb 2>&1