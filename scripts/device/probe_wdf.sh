#!/system/bin/sh
# Is the stock hardware-watchdog feeder (sprd_wdf) alive? It arms the AON
# watchdog at late_initcall and pings it every 8 s from per-CPU RT threads.
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== /proc/sprd_hang_debug ==="
ls -la /proc/sprd_hang_debug/ 2>&1
for f in wdf_timeout wdt_disable; do
    [ -e "/proc/sprd_hang_debug/$f" ] && { echo "--- $f"; cat "/proc/sprd_hang_debug/$f" 2>&1; }
done
echo
echo "=== dmesg: feeder + wdt handler ==="
dmesg 2>/dev/null | grep -i -E 'sprd_wdf|sprd_wdh|hang_debug|wdt' | head -25
echo
echo "=== feeder threads alive? ==="
ps -A 2>/dev/null | grep -i -E 'hang_debug|wdf' | head -10
echo
echo "=== AON wdt raw register state (CNT_EN / INT_EN / RST_EN) ==="
cat /sys/kernel/debug/sprd_hang_debug/* 2>/dev/null | head
ls /sys/kernel/debug/ 2>/dev/null | head -20
echo
echo "=== does the AON wdt counter actually count? (two reads, 1 s apart) ==="
# 0x644e0000 CNT_LOW 0x18, read via devmem if available
if command -v devmem >/dev/null 2>&1; then
    echo "CNT_LOW t0: $(devmem 0x644e0018 32 2>&1)"
    sleep 1
    echo "CNT_LOW t1: $(devmem 0x644e0018 32 2>&1)"
    echo "CTRL      : $(devmem 0x644e0008 32 2>&1)"
    echo "INT_RAW   : $(devmem 0x644e0010 32 2>&1)"
    echo "LOAD_LOW  : $(devmem 0x644e0004 32 2>&1)"
    echo "IRQ_LOAD_L: $(devmem 0x644e0030 32 2>&1)"
else
    echo "no devmem"
fi