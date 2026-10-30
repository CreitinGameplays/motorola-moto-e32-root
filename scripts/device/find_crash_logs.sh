#!/system/bin/sh
# Locate any saved crash/dontpanic logs from the loop, and read boot reasons.
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== boot reason properties ==="
for p in sys.boot.reason sys.boot.reason.last ro.boot.bootreason persist.sys.boot.reason persist.sys.boot.reason.history sys.rescue_boot_count ro.boot.verifiedbootstate; do
    echo "$p = $(getprop $p)"
done

echo
echo "=== dontpanic / ramdump / last-kmsg locations ==="
for d in /data/vendor/dontpanic /data/dontpanic /data/vendor/ramdump /data/vendor/rdbg /data/vendor/ssr /data/tombstones /data/vendor/tombstones /mnt/vendor/persist/dontpanic; do
    [ -e "$d" ] || continue
    echo "--- $d"
    ls -lt "$d" 2>/dev/null | head -8
done

echo
echo "=== anything named *dontpanic* / *console*ramoops* / *last_kmsg* on /data ==="
find /data -maxdepth 4 \( -iname '*dontpanic*' -o -iname '*ramoops*' -o -iname '*last_kmsg*' -o -iname '*pstore*' \) 2>/dev/null | head -20

echo
echo "=== fstab: what mounts /system (slot a vs b) ==="
ls -l /vendor/etc/fstab* /etc/fstab* 2>/dev/null
grep -h -E 'system|super|logical' /vendor/etc/fstab.qcom 2>/dev/null | head -5

echo
echo "=== is lpdump available (super metadata reader)? ==="
command -v lpdump; ls -l /system/bin/lpdump /system_ext/bin/lpdump 2>/dev/null
echo
echo "=== active dm devices ==="
ls /dev/block/mapper/ 2>/dev/null
cat /proc/partitions 2>/dev/null | head -20