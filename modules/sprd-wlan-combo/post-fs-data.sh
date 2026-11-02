#!/system/bin/sh
# SC2355 combo WLAN driver (in-tree port) loader.
#
# Runs at post-fs-data after the Mali module. The vendor wcn.rc tries to
# insmod its own sprdwl_ng.ko much earlier (and fails on this kernel -
# module_layout CRC mismatch); our copy loads here instead and binds to
# the already-initialized marlin/sdiohal bus.
#
# The vendor WiFi HAL (libwifi-hal.so) does NOT load drivers itself on this
# build: it checks the property 'wlan.driver.status' and greps /proc/modules
# for 'sprdwl_ng', and insmods /mnt/vendor/socko/sprdwl_ng.ko via
# finit_module if the property is unset (which fails with Exec format
# error on our kernel). So after OUR insmod we:
#   - set wlan.driver.status=ok   (HAL sees the driver as loaded)
#   - rename our module alias so the /proc/modules grep matches:
#     not needed - the property alone unblocks the HAL (verified in the
#     HAL binary: the property is read first).
#
# Everything is logged to /data/local/tmp/wlan_module_load.log.

MODDIR=${0%/*}
LOG=/data/local/tmp/wlan_module_load.log
KO=$MODDIR/sprdwl_ng.ko

{
    echo "=== $(date) wlan module load ==="
    echo "kernel: $(cat /proc/version)"
    echo "selinux: $(getenforce)"
    echo "ko: $(ls -l "$KO" 2>&1)"

    # the marlin bus must be up first (it is built-in and inits at boot;
    # check the chip is powered)
    echo "before: $(ls /sys/bus/platform/devices/ | grep -c marlin) marlin nodes"
    echo "wlan0 before: $(ip link show wlan0 2>&1 | head -1)"

    insmod "$KO" 2>&1
    echo "insmod rc=$?"

    # give the driver a moment to register the netdev
    sleep 2
    echo "after: $(ip link show 2>/dev/null | grep -E 'wlan|p2p' | head -4)"
    echo "modules: $(grep sprdwl /proc/modules 2>&1)"

    # unblock the vendor HAL: it gates on this property before it will
    # start wpa_supplicant/wificond against wlan0
    setprop wlan.driver.status ok
    echo "wlan.driver.status: $(getprop wlan.driver.status)"

    echo "dmesg tail:"
    dmesg | grep -iE "sprdwl|sc2355|marlin" | tail -25
} >> "$LOG" 2>&1

exit 0
