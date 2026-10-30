#!/system/bin/sh
# Partition sizes + live USB gadget layout (which functions are bound, is ACM free).
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"

echo "=== partition size (MiB) ==="
for n in boot_a boot_b vendor_boot_a vendor_boot_b dtb_a dtb_b dtbo_a dtbo_b \
         misc miscdata metadata cache super userdata sysdumpdb factory prodnv \
         elabel persist uboot_log logo; do
    p="/dev/block/by-name/$n"
    if [ -e "$p" ]; then
        dev=$(basename "$(readlink -f "$p")")
        sec=$(cat "/sys/class/block/$dev/size" 2>/dev/null)
        [ -n "$sec" ] && printf "%-16s %s sectors = %s MiB\n" "$n" "$sec" "$((sec / 2048))"
    fi
done

echo "=== live usb gadget config ==="
for g in /sys/kernel/config/usb_gadget/*; do
    [ -d "$g" ] || continue
    echo "gadget: $g"
    echo "  idVendor=$(cat "$g/idVendor" 2>/dev/null) idProduct=$(cat "$g/idProduct" 2>/dev/null)"
    echo "  UDC=$(cat "$g/UDC" 2>/dev/null)"
    for c in "$g"/configs/*; do
        [ -d "$c" ] || continue
        echo "  config $(basename "$c")"
        for f in "$c"/*; do
            [ -L "$f" ] || [ -d "$f" ] || continue
            echo "    fn: $(basename "$f")"
        done
    done
done

echo "=== usb function dirs available ==="
ls /sys/kernel/config/usb_gadget 2>/dev/null
echo "=== udc state ==="
cat /sys/class/udc/*/state 2>/dev/null
echo "=== acm usage by adb/config ==="
getprop sys.usb.config
getprop sys.usb.state
getprop persist.sys.usb.config
echo "=== free space on /data ==="
df -h /data 2>/dev/null | tail -2