#!/system/bin/sh
# Mali kbase (in-tree, r28p0-01eac0 + qogirl6 glue) loader.
#
# Runs at post-fs-data, i.e. after every driver initcall has completed and
# before zygote/surfaceflinger start - the same window in which the stock
# vendor rc (init.md.rc: `insmod .../socko/mali_kbase.ko` at post-fs) loads
# its own copy of this driver.
#
# Everything is logged to /data/local/tmp/mali_module_load.log so a hang here
# can be attributed without a serial console.

MODDIR=${0%/*}
LOG=/data/local/tmp/mali_module_load.log
KO=$MODDIR/mali_kbase.ko

{
    echo "=== $(date) mali module load ==="
    echo "kernel: $(cat /proc/version)"
    echo "selinux: $(getenforce)"
    echo "ko: $(ls -l "$KO" 2>&1)"
    echo "before: $(ls -l /dev/mali0 2>&1)"

    insmod "$KO" 2>&1
    echo "insmod rc=$?"

    sleep 1
    echo "after: $(ls -l /dev/mali0 2>&1)"
    echo "modules: $(grep -i mali /proc/modules 2>&1)"
    echo "dmesg:"
    dmesg | grep -iE "mali|kbase|midgard" | tail -40
} >> "$LOG" 2>&1

exit 0
