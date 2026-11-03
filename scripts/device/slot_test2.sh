#!/system/bin/sh
# exercise the rewritten slot 3 (N=70 = 1820): let schedutil request the
# top row (8) under probe load and watch what actually happens.
P=/sys/kernel/gpu_gpll_poker
GOV=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
DV=/sys/devices/system/cpu/cpufreq/cpudvfs/cpu0

echo schedutil > $GOV
echo "state: gov=$(cat $GOV) target=$(cat $DV/target) sel=$(cat $DV/sel) volt=$(cat $DV/voted_volt)"
echo 3 > $P/base; echo "slot3: $(echo 0xb4 > $P/rd; cat $P/rd)"
echo 2 > $P/base; echo "row8:  $(echo 0x80 > $P/rd; cat $P/rd)"

# sustained load on the lit cluster (400M probe) while sampling 2s
taskset 1 /data/local/tmp/cpu_freq_probe > /data/local/tmp/p1 &
BGPID=$!
echo "0 0 2000" > $P/mon
wait $BGPID
echo "probe(400M): $(cat /data/local/tmp/p1) ms"

echo "landed: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"
echo 3 > $P/base
echo "live0: $(echo 0x84 > $P/rd; cat $P/rd)"
echo "live1: $(echo 0x88 > $P/rd; cat $P/rd)"
echo "=== mon capture (regid t_ns val) ==="
cat $P/mon
