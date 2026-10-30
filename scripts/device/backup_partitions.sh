#!/system/bin/sh
# Dump the boot-critical partitions to a staging directory and hash them.
# Usage: sh backup_partitions.sh /data/local/tmp/backup
# Needs root (run mali_kroot in the same shell first).
set -u

out="${1:-/data/local/tmp/backup}"
mkdir -p "$out"

parts="boot_a boot_b dtbo_a dtbo_b vendor_boot_a vendor_boot_b \
vbmeta_a vbmeta_b vbmeta_system_a vbmeta_system_b \
vbmeta_vendor_a vbmeta_vendor_b vbmeta_product_a vbmeta_product_b \
misc miscdata uboot_a uboot_b sml_a sml_b trustos_a trustos_b \
prodnv logo persist"

manifest="$out/SHA256SUMS"
: > "$manifest"

for p in $parts; do
    src="/dev/block/by-name/$p"
    dst="$out/$p.img"
    if [ ! -e "$src" ]; then
        echo "$p missing" | tee -a "$manifest"
        continue
    fi
    if [ ! -r "$src" ]; then
        echo "$p unreadable (no root?)" | tee -a "$manifest"
        continue
    fi
    echo "dumping $p ..."
    dd if="$src" of="$dst" bs=1048576 2>/dev/null
    sum=$(sha256sum "$dst" | awk '{print $1}')
    bytes=$(wc -c < "$dst")
    echo "$sum  $bytes  $p" >> "$manifest"
    echo "  $p  $bytes bytes  $sum"
done

echo
echo "--- device identity ---" | tee -a "$manifest"
{
    echo "serial:      $(getprop ro.serialno)"
    echo "fingerprint: $(getprop ro.build.fingerprint)"
    echo "build.id:    $(getprop ro.build.id)"
    echo "slot:        $(getprop ro.boot.slot_suffix)"
    echo "flash.locked:$(getprop ro.boot.flash.locked)"
    echo "vbstate:     $(getprop ro.boot.verifiedbootstate)"
    echo "date:        $(date)"
} | tee -a "$manifest"

echo
echo "--- files ---"
ls -l "$out"
echo "total: $(du -sk "$out" | awk '{print $1}') KiB"