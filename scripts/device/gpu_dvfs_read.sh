#!/system/bin/sh
# THE definitive GPU DVFS hardware-map experiment, inside one
# also-present camera viewfinder session (continuous preview = constant
# GPU composition, which keeps the kbase power/clock on).
#   Phase 1: dump topdvfs + remaining gpu-dvfs-apb regs at the stock
#            top level (INDEX_CFG=4, 650 MHz)
#   Phase 2: apply the runtime untrim (freq_list[3] -> true 768 entry
#            + OPP) and raise max_freq -> governor lands on INDEX_CFG=3
#   Phase 3: re-read the live CGM/voltage/state regs at index 3
#   Phase 4: revert everything
# Safety: the experiment ABORTS (no reads) if the camera app does not
# reach the foreground.  Every MMIO read happens while the preview is
# definitely running.

P=/sys/kernel/gpu_gpll_poker
U=/sys/kernel/gpu_dvfs_untrim
DF=/sys/class/devfreq/23100000.gpu
OUT=/data/local/tmp/gpu_dvfs_regs.txt

log() { echo "$1" >> $OUT; }

rd1() {	# rd1 <base> <off>
	echo $1 > $P/base
	echo "$2" > $P/rd
	log "$(cat $P/rd)"
}

echo "--- $(date) cur_freq=$(cat $DF/cur_freq)" > $OUT

# launch the camera; the viewfinder = constant GPU load
am start -a android.media.action.STILL_IMAGE_CAMERA >/dev/null 2>&1
i=0
while :; do
	sleep 1
	FOCUS=$(dumpsys window | grep -m1 mCurrentFocus)
	echo "focus: $FOCUS" >> $OUT
	case "$FOCUS" in
		*camera*) echo "camera in foreground" >> $OUT; break;;
	esac
	i=$((i+1))
	if [ $i -ge 12 ]; then
		echo "ABORT: camera not in foreground - no reads performed" >> $OUT
		cat $OUT
		exit 1
	fi
done
sleep 2

# ---- phase 1: index 4 (650) register map ----
log "== phase 1: stock top level (index 4) =="
for off in 0x34 0x38 0x2c 0x8c 0x48 0x4c 0x50 0x54 0x58 0x5c 0x60 0x64 0x10 0x20 0x24 0x28 0x90 0x98 0xa4 0xc0 0xd0; do
	rd1 0 $off
done
log "== topdvfs controller =="
for off in 0x00 0x04 0x08 0x0c 0x10 0x14 0x18 0x1c 0xe0 0xe4 0xe8 0xec 0xf0 0xf4 0xf8 0xfc 0x100 0x104 0x108 0x10c 0x110 0x114; do
	rd1 1 $off
done

# ---- phase 2: apply the untrim, land on index 3 ----
log "== phase 2: untrim apply =="
sh /data/local/tmp/gpu_untrim_setup.sh set >> $OUT
echo 768000000 > $DF/max_freq
i=0
while [ $i -lt 12 ]; do
	sleep 0.5
	c=$(cat $DF/cur_freq)
	[ "$c" = "768000000" ] && break
	i=$((i+1))
done
log "cur_freq=$c after untrim"

# ---- phase 3: index 3 live state ----
log "== phase 3: untrimmed top level (index 3) =="
for off in 0x34 0x38 0x2c 0x8c; do
	rd1 0 $off
done

# ---- phase 4: revert ----
log "== phase 4: revert =="
echo 650000000 > $DF/max_freq
sh /data/local/tmp/gpu_untrim_setup.sh revert >> $OUT
log "done cur_freq=$(cat $DF/cur_freq)"

input keyevent KEYCODE_HOME
cat $OUT
