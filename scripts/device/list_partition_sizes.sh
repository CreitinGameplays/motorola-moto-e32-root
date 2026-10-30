#!/system/bin/sh
# List the size of every interesting partition by resolving the by-name link
# and looking the device up in /proc/partitions (sizes are in 1 KiB blocks).
parts="boot_a boot_b dtbo_a dtbo_b vendor_boot_a vendor_boot_b \
vbmeta_a vbmeta_b vbmeta_system_a vbmeta_system_b \
vbmeta_vendor_a vbmeta_vendor_b vbmeta_product_a vbmeta_product_b \
misc miscdata uboot_a uboot_b sml_a sml_b trustos_a trustos_b \
prodnv logo persist nvdata"

total=0
for p in $parts; do
    link="/dev/block/by-name/$p"
    [ -e "$link" ] || { echo "$p missing"; continue; }
    dev=$(readlink -f "$link" 2>/dev/null)
    base=$(basename "$dev")
    kb=$(awk -v d="$base" '$4 == d { print $3 }' /proc/partitions)
    if [ -n "$kb" ]; then
        bytes=$((kb * 1024))
        total=$((total + bytes))
        printf '%-20s %-12s %10d bytes\n' "$p" "$base" "$bytes"
    else
        printf '%-20s %-12s %s\n' "$p" "$base" "(no size in /proc/partitions)"
    fi
done
echo "total $total bytes"