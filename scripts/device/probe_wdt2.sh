#!/system/bin/sh
# Is the AON watchdog registered/usable on stock, and what does /chosen/bootargs hold?
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== /sys/class/watchdog (raw) ==="
ls -la /sys/class/watchdog/ 2>&1
echo
echo "=== AON wdt device bound to driver? ==="
ls -la /sys/bus/platform/devices/644e0000.watchdog 2>&1
ls -la /sys/bus/platform/drivers/sprd-wdt-fiFO 2>/dev/null
ls -la /sys/bus/platform/drivers/sprd-wdt-fiq/ 2>&1
echo
echo "=== pmic wdt device ==="
ls -la /sys/bus/platform/drivers/sprd-pmic-wdt/ 2>&1
echo
echo "=== /chosen/bootargs (raw, first 1200 bytes) ==="
cat /proc/device-tree/chosen/bootargs 2>&1 | head -c 1200
echo
echo
echo "=== is there an AON wdt DT node with status? ==="
for n in /proc/device-tree/soc/aon/watchdog@644e0000; do
    [ -e "$n" ] || continue
    echo "node: $n"
    ls "$n"
    [ -e "$n/status" ] && echo "status: $(cat "$n/status" | tr -d '\0')"
    [ -e "$n/compatible" ] && echo "compatible: $(cat "$n/compatible" | tr -d '\0')"
done
echo
echo "=== dmesg: the wdt probes in full ==="
dmesg 2>/dev/null | grep -i -E 'wdt|watchdog' | head -20