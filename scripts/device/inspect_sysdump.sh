#!/system/bin/sh
# Inspect the SPRD sysdump partition for a dump from the last (hung) boot.
set -u

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    i=$((i + 1))
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

dev=/dev/block/by-name/sysdumpdb
readlink -f "$dev"
sectors=$(cat /sys/class/block/$(basename "$(readlink -f "$dev")")/size)
echo "sectors=$sectors  bytes=$((sectors * 512))"

# first 1 MiB and last 1 MiB
dd if="$dev" of=/data/local/tmp/sysdump_head.img bs=4096 count=256 2>/dev/null
total=$((sectors * 512))
seek=$(( total > 1048576 ? total - 1048576 : 0 ))
dd if="$dev" of=/data/local/tmp/sysdump_tail.img bs=4096 skip=$((seek / 4096)) count=256 2>/dev/null

for f in head tail; do
    p=/data/local/tmp/sysdump_${f}.img
    echo "--- $f $(sha256sum "$p" | awk '{print $1}') $(wc -c < "$p") bytes ---"
    echo "non-zero bytes: $(tr -d '\000' < "$p" | wc -c)"
    echo "first 64:"; od -An -tx1 -N64 "$p"
done

echo "--- printable strings (head, up to 40) ---"
strings -n 8 /data/local/tmp/sysdump_head.img 2>/dev/null | head -40