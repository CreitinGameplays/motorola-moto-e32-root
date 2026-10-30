#!/system/bin/sh
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
echo "--- config.gz ---"
zcat /proc/config.gz 2>/dev/null | grep -E 'CONFIG_EXT4_FS=|CONFIG_DEVTMPFS|CONFIG_BLK_DEV_INITRD|CONFIG_F2FS_FS=|CONFIG_RD_GZIP=|CONFIG_TMPFS='
echo "--- /proc/filesystems ---"
cat /proc/filesystems
echo "--- modules dir ---"
ls /vendor/lib/modules 2>/dev/null | head -20