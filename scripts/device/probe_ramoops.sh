#!/system/bin/sh
# Why is /sys/fs/pstore empty even though the DTB has reserved-memory/ramoops@fff80000 ?
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

N=/proc/device-tree/reserved-memory/ramoops@fff80000
echo "=== node $N ==="
ls -l "$N" 2>&1

for f in compatible reg record-size console-size pmsg-size no-map status; do
    p="$N/$f"
    if [ -e "$p" ]; then
        printf '%-14s ' "$f:"
        od -An -tx1 -v "$p" | tr -d '\n'
        echo
    else
        printf '%-14s <absent>\n' "$f:"
    fi
done

echo
echo "=== platform devices matching ramoops/pstore ==="
ls /sys/bus/platform/devices | grep -i -E 'ramoops|pstore' || echo "(none)"

echo "=== iomem near the region ==="
grep -i -E 'ramoops|pstore|persistent|fff8|0xfff' /proc/iomem 2>&1 | head -20

echo "=== dmesg ==="
dmesg 2>/dev/null | grep -i -E 'ramoops|pstore|persistent_ram' | head -30 || echo "(dmesg blocked or no hits)"

echo "=== /dev/kmsg tail, filtered ==="
timeout 3 head -c 400000 /dev/kmsg 2>/dev/null | grep -i -E 'ramoops|pstore' | tail -20

echo "=== memblock / memory ==="
grep -i -E 'MemTotal|Memory:' /proc/meminfo | head -3