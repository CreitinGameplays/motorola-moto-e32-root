#!/system/bin/sh
# Park a cluster at a work index, keep it loaded, and capture the LIVE
# mpll register values during the load (tests the parked-reg theory).
# usage: live_probe.sh <dvfs-suffix> <probe-mask> <index> <mpll-base> <reg0>
DV=/sys/devices/system/cpu/cpufreq/cpudvfs/$1
MASK=$2
IDX=$3
BASE=$4
REG0=$5
P=/sys/kernel/gpu_gpll_poker

echo "before: target=$(cat $DV/target) sel=$(cat $DV/sel) volt=$(cat $DV/voted_volt)"
echo $BASE > $P/base
echo "live reg0 idle: $(echo $REG0 > $P/rd; cat $P/rd)"
echo "live reg1 idle: $(echo $(($REG0+4)) > $P/rd; cat $P/rd)"

echo $IDX > $DV/target
sleep 1
echo "parked idx $IDX: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"

# load the cluster with the probe, capture live regs mid-run
taskset $MASK /data/local/tmp/cpu_freq_probe20 &
BGPID=$!
sleep 0.3
echo "live reg0 loaded: $(echo $REG0 > $P/rd; cat $P/rd)"
echo "live reg1 loaded: $(echo $(($REG0+4)) > $P/rd; cat $P/rd)"
wait $BGPID

# and again after the load ended
sleep 0.5
echo "live reg0 after: $(echo $REG0 > $P/rd; cat $P/rd)"
echo "live reg1 after: $(echo $(($REG0+4)) > $P/rd; cat $P/rd)"
