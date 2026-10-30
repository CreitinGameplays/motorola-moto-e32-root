#!/system/bin/sh
# Probe the live device for channels that are not "boot a new kernel in boot_a":
# listening sockets, serial/tty nodes, USB gadget support, and the partition map.
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"

echo "=== tcp listen (port, local addr, uid) ==="
awk 'NR>1 { printf "%s %s uid=%s\n", $2, $4, $10 }' /proc/net/tcp /proc/net/tcp6 2>/dev/null | head -40

echo "=== udp bound ==="
awk 'NR>1 { printf "%s %s uid=%s\n", $2, $4, $10 }' /proc/net/udp /proc/net/udp6 2>/dev/null | head -20

echo "=== ss ==="
ss -ltnup 2>/dev/null | head -40

echo "=== tty drivers ==="
cat /proc/tty/drivers 2>/dev/null

echo "=== tty nodes ==="
ls -l /dev/tty* 2>/dev/null
ls -l /dev/ttyHS* /dev/ttyGS* /dev/ttyMSM* 2>/dev/null

echo "=== uart ports present ==="
for d in /sys/class/tty/*; do
    n=$(basename "$d")
    case "$n" in ttyHS*|ttyGS*|ttyS*|ttyFIQ*) echo "$n -> $(readlink -f "$d/device" 2>/dev/null)";; esac
done

echo "=== usb gadget controller ==="
ls /sys/class/udc 2>/dev/null
cat /sys/class/udc/*/state 2>/dev/null

echo "=== configfs ==="
grep configfs /proc/filesystems 2>/dev/null
ls /sys/kernel/config 2>/dev/null

echo "=== usb gadget modules / config ==="
ls /sys/module 2>/dev/null | grep -i -E 'gadget|configfs|dwc|usb_f' | head -20

echo "=== by-name partitions ==="
ls -l /dev/block/by-name 2>/dev/null

echo "=== block devices ==="
ls -l /dev/block/sd* 2>/dev/null | head -40