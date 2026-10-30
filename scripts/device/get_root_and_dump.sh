#!/system/bin/sh
# Retry mali_kroot until it lands, then dump the slot-decision partitions.
# Usage: sh get_root_and_dump.sh [label]
label="${1:-after}"
out=/data/local/tmp

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >"$out/kroot_$i.log" 2>&1
    u=$(id -u)
    echo "attempt $i -> uid $u"
    [ "$u" = "0" ] && break
    i=$((i + 1))
    sleep 2
done

if [ "$(id -u)" != "0" ]; then
    echo "root failed; tail of last log:"
    tail -n 20 "$out/kroot_$i.log"
    exit 1
fi

id

for p in misc miscdata; do
    dd if="/dev/block/by-name/$p" of="$out/${p}_${label}.img" bs=4096 count=2 2>/dev/null
    echo "$p $(sha256sum "$out/${p}_${label}.img" | awk '{print $1}') $(wc -c < "$out/${p}_${label}.img")"
done

echo "slot_suffix=$(getprop ro.boot.slot_suffix)"
echo "--- misc 0x000 ---"
od -An -tx1 -N64 "$out/misc_${label}.img"
echo "--- misc 0x800 ---"
od -An -tx1 -j 2048 -N48 "$out/misc_${label}.img"