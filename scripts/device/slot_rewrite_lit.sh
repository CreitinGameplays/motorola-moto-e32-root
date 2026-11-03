#!/system/bin/sh
# lit cluster SLOT-REWRITE OC test:
#   ananke slot 3 (N=62 = 1612, loaded by lit row 8 = the top row)
#   -> rewritten to slot 5's config (N=70 = 1820 MHz, icp=4)
#   lit row 8 voltage grade 5 -> 7 (1.0 V, the T612 lit-1820 grade)
# Everything is volatile: a reboot fully reverts.
P=/sys/kernel/gpu_gpll_poker
DV=/sys/devices/system/cpu/cpufreq/cpudvfs/cpu0
GOV=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

echo userspace > $GOV

# 1. park the cluster on the safe XTL source (row 0)
echo 0 > $DV/target
sleep 1
echo "parked XTL: target=$(cat $DV/target) sel=$(cat $DV/sel) volt=$(cat $DV/voted_volt)"

# 2. snapshot current slot 3 + row 8 for the revert line
echo 3 > $P/base
S3=$(echo 0xb4 > $P/rd; cat $P/rd | cut -d' ' -f2)
echo 2 > $P/base
R8=$(echo 0x80 > $P/rd; cat $P/rd | cut -d' ' -f2)
echo "stock: slot3=$S3 row8=$R8"

# 3. rewrite slot 3 = slot 5 config (0x464: N=70, icp=4, postdiv=0)
echo 3 > $P/base
echo "0xb4 0x00000464" > $P/wr
echo "slot3 now: $(echo 0xb4 > $P/rd; cat $P/rd)"

# 4. lit row 8: voltage grade -> 7 (bits 15-17)
echo 2 > $P/base
NEW=$(( (R8 & 0xfffc7fff) | 0x38000 ))
printf "0x80 0x%08x\n" "$NEW" > $P/wr
echo "row8 now: $(echo 0x80 > $P/rd; cat $P/rd)"

# 5. force the full transition with the monitor recording it
echo "0x214 8 2000" > $P/mon
echo "landed: target=$(cat $DV/target) sel=$(cat $DV/sel) div=$(cat $DV/div) volt=$(cat $DV/voted_volt)"

# 6. measure
taskset 1 /data/local/tmp/cpu_freq_probe20
taskset 1 /data/local/tmp/cpu_freq_probe20
taskset 1 /data/local/tmp/cpu_freq_probe20

echo "=== mon capture (regid t_ns val) ==="
cat $P/mon
