#!/system/bin/sh
# Copy the small bootloader/unlock-relevant partitions into /data/local/tmp/dumps.
# Run as root (after mali_kroot). Read-only: never writes back to the device.
set -u
OUT=/data/local/tmp/dumps
mkdir -p "$OUT"
for p in misc elabel persist metadata teecfg_a factory sysdumpdb miscdata prodnv; do
    src="/dev/block/by-name/$p"
    [ -e "$src" ] || { echo "MISSING $p"; continue; }
    if dd if="$src" of="$OUT/$p.img" bs=1048576 2>/dev/null; then
        echo "OK $p $(stat -c %s "$OUT/$p.img" 2>/dev/null)"
    else
        echo "FAIL $p"
    fi
done
