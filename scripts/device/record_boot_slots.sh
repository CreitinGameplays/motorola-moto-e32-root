#!/system/bin/sh
# Record the current boot_a (test slot) sha256 so a write can be reverted.
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
echo "boot_a $(sha256sum /dev/block/by-name/boot_a | awk '{print $1}')"
echo "boot_b $(sha256sum /dev/block/by-name/boot_b | awk '{print $1}')"
echo "size  $(cat /sys/class/block/sda40/size) sectors"