#!/system/bin/sh
# Absolute frequency calibration of a CPU cluster via the DVFS XTL row.
# usage: calibrate.sh <cpudvfs-dir-suffix> <cpulist-mask> <top-index>
#   e.g. sh calibrate.sh cpu0 1 8    (lit: probe cpu0, top index 8)
#        sh calibrate.sh cpu6 64 6   (big: probe cpu6, top index 6)
DV=/sys/devices/system/cpu/cpufreq/cpudvfs/$1
MASK=$2
TOP=$3
GOV=/sys/devices/system/cpu/$1/cpufreq/scaling_governor

echo "state: governor=$(cat $GOV) target=$(cat $DV/target) freq=$(cat /sys/devices/system/cpu/$1/cpufreq/cpuinfo_cur_freq)"

echo userspace > $GOV
echo "--- XTL row (26 MHz) ---"
echo 0 > $DV/target
sleep 1
echo "parked: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"
taskset $MASK /data/local/tmp/cpu_freq_probe20
taskset $MASK /data/local/tmp/cpu_freq_probe20
taskset $MASK /data/local/tmp/cpu_freq_probe20

echo "--- top row ---"
echo $TOP > $DV/target
sleep 1
echo "parked: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"
taskset $MASK /data/local/tmp/cpu_freq_probe20
taskset $MASK /data/local/tmp/cpu_freq_probe20
taskset $MASK /data/local/tmp/cpu_freq_probe20

echo "--- restoring ---"
echo schedutil > $GOV 2>/dev/null || echo interactive > $GOV
echo "done: governor=$(cat $GOV) target=$(cat $DV/target)"
