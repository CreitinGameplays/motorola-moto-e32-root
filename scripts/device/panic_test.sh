#!/system/bin/sh
# Measure the panic path on the STOCK kernel, from userspace root.
#
# Why: the custom kernel appears to hang with no panic and no reboot. Before
# blaming the kernel, prove that a panic can reboot this phone at all and that
# SPRD sysdump really captures the kernel log buffer into sysdumpdb.
#
#   * if the phone reboots within ~10 s, machine_restart() has a working
#     restart handler on stock -> a panic IS observable -> our custom kernel
#     never reached panic().
#   * if the phone does not reboot, panic() only prints and stalls in
#     "Reboot failed -- System halted", which is exactly what "no reboot"
#     looked like in the diagnostic boot.
#
# This is a deliberate panic. The device recovers by itself (or by pressing
# power), and nothing is written to any boot partition.
set -u

/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== panic prerequisites on stock ==="
echo "--- restart handlers registered ---"
ls /sys/kernel/reboot* 2>/dev/null
echo "--- watchdog devices ---"
for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w" ] || continue
    echo "$w: $(cat "$w/identity" 2>/dev/null) timeout=$(cat "$w/timeout" 2>/dev/null) state=$(cat "$w/state" 2>/dev/null)"
done
echo "--- panic settings ---"
for f in panic panic_on_oops panic_on_warn; do
    [ -e "/proc/sys/kernel/$f" ] && echo "$f = $(cat /proc/sys/kernel/$f)"
done
echo "--- sysdump state ---"
ls -l /proc/sprd_sysdump 2>/dev/null
cat /sys/module/sprd_sysdump/parameters/* 2>/dev/null | head -5

echo
echo "=== panic in 3 s (sysrq c) ==="
echo "watch the device: it should reboot if a restart handler works"
sleep 3
echo c > /proc/sysrq-trigger
echo "sysrq c returned (unexpected - the phone should have reset)"