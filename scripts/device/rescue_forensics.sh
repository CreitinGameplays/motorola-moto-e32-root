#!/system/bin/sh
# Collect the boot_a rescue's forensic trail: the DRESCUE1 marker in
# sysdumpdb, the A/B block and BCB in misc, and pstore (warm-reset panic log).
# Run: adb shell sh /data/local/tmp/rescue_forensics.sh
set -u
OUT=/data/local/tmp/rescue-forensics
D=/dev/block/by-name

for i in 1 2 3 4 5 6; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

mkdir -p "$OUT"
echo "=== slot / state ==="
getprop ro.boot.slot_suffix
getprop ro.boot.verifiedbootstate
getprop ro.boot.bootreason
cat /proc/uptime

# marker: sysdumpdb + 0x900000, 128 bytes (4096 * 2304)
echo
echo "=== DRESCUE1 marker (sysdumpdb+0x900000, 128 B) ==="
dd if="$D/sysdumpdb" of="$OUT/marker.bin" bs=1 skip=9437184 count=128 2>&1 | tail -1
ls -l "$OUT/marker.bin"
od -An -tx1 -v "$OUT/marker.bin"
echo "--- ascii ---"
strings -n 1 "$OUT/marker.bin" | head -3

# A/B block at misc+0x800 (32 B) and the BCB at misc+0 (64 B)
echo
echo "=== misc A/B block (+0x800, 32 B) ==="
dd if="$D/misc" of="$OUT/misc8k.bin" bs=4096 count=2 2>&1 | tail -1
dd if="$OUT/misc8k.bin" of="$OUT/ab32.bin" bs=1 skip=2048 count=32 2>&1 | tail -1
od -An -tx1 -v "$OUT/ab32.bin"
echo "=== misc BCB (+0, 64 B) ==="
dd if="$D/misc" of="$OUT/bcb.bin" bs=1 count=64 2>&1 | tail -1
strings -n 3 "$OUT/bcb.bin"

# pstore: only survives a *warm* reset
echo
echo "=== pstore ==="
ls -l /sys/fs/pstore/ 2>&1
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    echo "--- $f ---"
    grep -a -m 20 -e 'Panic' -e 'Kernel panic' -e 'Call trace' -e 'Linux version' "$f" 2>/dev/null
done

echo
echo "collected into $OUT"