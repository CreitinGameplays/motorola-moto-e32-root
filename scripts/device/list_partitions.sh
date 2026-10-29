#!/system/bin/sh
# List sizes of the partitions relevant to bootloader/unlock research.
# Intended to run as root (adb shell after mali_kroot).
for p in misc miscdata elabel persist prodnv metadata teecfg_a \
         sml_a sml_b uboot_a uboot_b trustos_a vbmeta_a sysdumpdb \
         factory cache fbootlogo logo; do
    d="/dev/block/by-name/$p"
    if [ -e "$d" ]; then
        s=$(blockdev --getsize64 "$d" 2>/dev/null)
        printf '%-12s %s\n' "$p" "$s"
    else
        printf '%-12s MISSING\n' "$p"
    fi
done
