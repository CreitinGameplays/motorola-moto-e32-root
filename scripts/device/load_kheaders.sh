#!/system/bin/sh
# Load the vendor kheaders.ko module so the kernel exposes a tarball with the
# exact headers/Module.symvers used to build this kernel. Needs root.
# Nothing is modified on disk: the tarball is copied to /data for pulling.
set -u
OUT=/data/local/tmp/kheaders.tar.xz
echo "id: $(id)"
echo "--- loaded modules before ---"
cat /proc/modules 2>/dev/null | head -20

if [ -e /sys/kernel/kheaders.tar.xz ]; then
    echo "kheaders already available"
else
    insmod /vendor/lib/modules/kheaders.ko
    echo "insmod rc=$?"
fi

ls -l /sys/kernel/kheaders.tar.xz 2>&1
if [ -e /sys/kernel/kheaders.tar.xz ]; then
    cat /sys/kernel/kheaders.tar.xz > "$OUT"
    echo "copied $(stat -c %s "$OUT" 2>/dev/null) bytes to $OUT"
fi

echo "--- loaded modules after ---"
cat /proc/modules 2>/dev/null | head -20
echo "--- psci ---"
cat /proc/device-tree/psci/method 2>&1
echo
echo "--- kernel ---"
uname -a
