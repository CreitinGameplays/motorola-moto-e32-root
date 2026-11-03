#!/system/bin/sh
# T606 CPU overclock experiment - phase 1: big cluster (A75, cpu6-7)
# 1612 -> 1820 MHz using the T612-2 map-table row (same die family,
# shipped config for this binning; see docs/21-cpu-dvfs-hwdvfs.md).
# Writes the OC row into the unused big rows 7/8/9, flips the work index
# through the driver's own target sysfs (voltage-first FSM handshake),
# benchmarks, and reverts.  Log: /data/local/tmp/cpu_oc.log

P=/sys/kernel/gpu_gpll_poker
B=/sys/devices/system/cpu/cpufreq/cpudvfs
DF6=/sys/devices/system/cpu/cpu6/cpufreq
LOG=/data/local/tmp/cpu_oc.log

LIVE_TOP=0x00a1a903		# big row 6 (T606-2 top: 1612 MHz, grade 3)
OC_ROW=0x00a24943		# c2 3->4 (grade 4 = 950 mV), c3 8->10,
				# c6 2->4 (prometheus slot 4 = 1820 MHz)

log() { echo "$1" | tee -a $LOG; }

bench() {
	i=0
	while [ $i -lt 3 ]; do
		S=$(date +%s%N)
		taskset -c 6 sh -c 'X=0; j=0; while [ $j -lt 200000 ]; do X=$((X+j)); j=$((j+1)); done'
		E=$(date +%s%N)
		log "iter$i: $(( (E - S) / 1000000 )) ms"
		i=$((i+1))
	done
}

state() {
	log "target=$(cat $B/cpu6/target) sel=$(cat $B/cpu6/sel) div=$(cat $B/cpu6/div) volt=$(cat $B/cpu6/voted_volt) cpuinfo=$(cat $DF6/cpuinfo_cur_freq)"
}

thermal() {
	for z in /sys/class/thermal/thermal_zone*; do
		t=$(cat $z/type 2>/dev/null)
		case "$t" in
			*cpu*|*soc*) log "temp $t: $(cat $z/temp)";;
		esac
	done
}

echo "=== $(date) ===" > $LOG
echo 2 > $P/base

log "-- stock state --"
state
log "-- stock bench (3x) --"
bench
thermal

log "-- writing OC row 0x$OC_ROW into big rows 7/8/9 (0xbc/0xc0/0xc4) --"
echo "0xbc $OC_ROW" > $P/wr
echo "0xc0 $OC_ROW" > $P/wr
echo "0xc4 $OC_ROW" > $P/wr
for off in 0xbc 0xc0 0xc4; do
	echo $off > $P/rd
	log "readback $(cat $P/rd)"
done

log "-- flipping big work index to 7 --"
echo 7 > $B/cpu6/target
sleep 1
state
log "-- OC bench (3x) --"
bench
state
thermal
log "-- drift check (5s) --"
sleep 5
state

log "-- revert --"
echo 6 > $B/cpu6/target
sleep 1
echo "0xbc $LIVE_TOP" > $P/wr
echo "0xc0 $LIVE_TOP" > $P/wr
echo "0xc4 $LIVE_TOP" > $P/wr
sleep 1
state
log "done"
cat $LOG
