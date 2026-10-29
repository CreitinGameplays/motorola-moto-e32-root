#!/system/bin/sh
# Re-dump the small partitions into /data/local/tmp/dumps2 so the host can diff
# them against an earlier snapshot (used to see whether fastboot oem unlock/lock
# touched any persistent storage, even though both commands reported failure).
set -u
OUT=/data/local/tmp/dumps2
mkdir -p "$OUT"
for p in misc miscdata persist prodnv elabel metadata uboot_log teecfg_a factory sysdumpdb; do
    src="/dev/block/by-name/$p"
    [ -e "$src" ] || { echo "MISSING $p"; continue; }
    if dd if="$src" of="$OUT/$p.img" bs=1048576 2>/dev/null; then
        echo "OK $p $(stat -c %s "$OUT/$p.img" 2>/dev/null)"
    else
        echo "FAIL $p"
    fi
done
md5sum "$OUT"/*.img
