#!/system/bin/sh
# READ-ONLY: prove the AON watchdog is armed and counting on stock Android.
# CTRL bit0=INT_EN, bit1=CNT_EN, bit3=RST_EN. Never writes.
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== toolbox ==="
command -v devmem; devmem 2>&1 | head -3

rd() {
    # toybox devmem: ADDRESS [WIDTH [VALUE]] with WIDTH in 8/16/32/64 bits
    devmem "$1" 2>&1 || true
}

echo
echo "=== AON wdt @ 0x644e0000 ==="
echo "LOAD_LOW   $(rd 0x644e0000)"
echo "LOAD_HIGH  $(rd 0x644e0004)"
echo "CTRL       $(rd 0x644e0008)"
echo "INT_CLR    $(rd 0x644e000c)"
echo "INT_RAW    $(rd 0x644e0010)"
echo "CNT_LOW t0 $(rd 0x644e0018)"
sleep 1
echo "CNT_LOW t1 $(rd 0x644e0018)"
echo "CNT_STEP   $(rd 0x644e0020)"
echo "LOCK(20)   $(rd 0x644e0020)"
echo "IRQ_LOAD_L $(rd 0x644e0030)"
echo "IRQ_LOAD_H $(rd 0x644e0034)"