#!/system/bin/sh
# Test A: force a DVFS engine re-init (module_eb toggle) AFTER the slot
# rewrite, so if the FSM caches the slot files at init it will now pick
# up slot3 = N70 (1820).  Everything is volatile; reboot reverts.
P=/sys/kernel/gpu_gpll_poker
DV=/sys/devices/system/cpu/cpufreq/cpudvfs/cpu0

echo 5 > $P/base
EB=$(echo 0x4 > $P/rd; cat $P/rd | cut -d' ' -f2)
echo "aon_apb+4 before: $EB"

# module off (clear bit 7), wait, back on
OFF=$((EB & 0xffffff7f))
printf "0x4 0x%08x\n" "$OFF" > $P/wr
sleep 1
printf "0x4 0x%08x\n" "$EB" > $P/wr
sleep 1
echo "aon_apb+4 after: $(echo 0x4 > $P/rd; cat $P/rd)"

# did the re-init touch our rewritten registers?
echo 3 > $P/base
echo "slot3 after re-init: $(echo 0xb4 > $P/rd; cat $P/rd)"
echo 2 > $P/base
echo "row8 after re-init: $(echo 0x80 > $P/rd; cat $P/rd)"

# state after the toggle
echo "state: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"

# force a full transition through XTL to the top row
echo 0 > $DV/target; sleep 1
echo 8 > $DV/target; sleep 1
echo "parked8: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"

# measure
taskset 1 /data/local/tmp/cpu_freq_probe20
taskset 1 /data/local/tmp/cpu_freq_probe20
taskset 1 /data/local/tmp/cpu_freq_probe20
taskset 1 /data/local/tmp/cpu_freq_probe
