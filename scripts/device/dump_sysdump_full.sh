#!/system/bin/sh
# Dump the whole sysdumpdb partition (10 MiB) so the kernel log buffer that
# SPRD captured on panic can be recovered on the host.
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

dev=/dev/block/by-name/sysdumpdb
out=/data/local/tmp/sysdumpdb_full.img

size=$(cat /sys/class/block/$(basename "$(readlink -f "$dev")")/size)
echo "device  $(readlink -f "$dev")"
echo "sectors $size  bytes $((size * 512))"

dd if="$dev" of="$out" bs=4096 count=$((size / 8)) 2>/dev/null
echo "wrote   $(wc -c < "$out") bytes  sha256 $(sha256sum "$out" | cut -d' ' -f1)"
echo "nonzero $(tr -d '\000' < "$out" | wc -c) bytes"
echo "--- crash banner strings ---"
strings -n 6 "$out" | grep -m 20 -E 'kernel_crash|Native hang|panic|Sysdump enter|soft lockup|Call trace|Linux version'