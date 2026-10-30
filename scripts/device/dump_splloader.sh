#!/system/bin/sh
# Read-only: dump splloader (the first stage after BootROM) for offline analysis.
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
p=/dev/block/by-name/splloader
if [ ! -e "$p" ]; then echo "no splloader node"; exit 1; fi
dev=$(basename "$(readlink -f "$p")")
sec=$(cat "/sys/class/block/$dev/size" 2>/dev/null)
echo "splloader: $dev  $sec sectors = $((sec / 2048)) MiB  devnum=$(cat /sys/class/block/$dev/dev)"
dd if="$p" of=/data/local/tmp/splloader.img bs=4096 2>/dev/null
echo "sha256=$(sha256sum /data/local/tmp/splloader.img | awk '{print $1}')"
echo "bytes=$(wc -c < /data/local/tmp/splloader.img)"
echo "--- first 32 bytes ---"
od -An -tx1 -N32 /data/local/tmp/splloader.img