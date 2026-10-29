#!/system/bin/sh
# Collect the kernel build/module information needed to build an unsigned
# kernel module for this device. Run as root (after mali_kroot).
uname -a
echo "--- vermagic ---"
for m in /vendor/lib/modules/*.ko; do
    echo "== $m"
    strings "$m" | grep -m2 -E 'vermagic|4\.14\.199'
    break
done
echo "--- all module vermagic ---"
for m in /vendor/lib/modules/*.ko; do
    v=$(strings "$m" | grep -m1 'vermagic')
    [ -n "$v" ] && echo "$(basename "$m"): $v"
done | head -20
echo "--- kheaders ---"
ls -l /sys/kernel/kheaders.tar.xz 2>&1
echo "--- loaded module count ---"
grep -c . /proc/modules
echo "--- module count on disk ---"
ls /vendor/lib/modules | wc -l
echo "--- config module opts ---"
(zcat /proc/config.gz 2>/dev/null || cat /proc/config.gz 2>/dev/null) | grep -iE 'CONFIG_MODULE|CONFIG_LOCALVERSION|CONFIG_ARM64_VA_BITS|CONFIG_ARM64_PAGE_SHIFT'
