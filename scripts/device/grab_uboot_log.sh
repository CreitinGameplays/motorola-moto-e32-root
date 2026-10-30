#!/system/bin/sh
# Grab the bootloader log after a failed slot-a boot, so the failure reason
# (image load / kernel start / reset) can be read offline.
set -u

i=1
while [ "$i" -le 6 ]; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    i=$((i + 1))
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "slot=$(getprop ro.boot.slot_suffix) boot_completed=$(getprop sys.boot_completed)"
echo "kernel=$(cat /proc/version | cut -c1-60)"

for p in uboot_log misc; do
    src="/dev/block/by-name/$p"
    if [ -e "$src" ]; then
        dd if="$src" of="/data/local/tmp/${p}_now.img" bs=1048576 2>/dev/null
        echo "$p $(sha256sum /data/local/tmp/${p}_now.img | awk '{print $1}') $(wc -c < /data/local/tmp/${p}_now.img) bytes"
    else
        echo "$p missing"
    fi
done