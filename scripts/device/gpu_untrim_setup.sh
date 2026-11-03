#!/system/bin/sh
# GPU DVFS untrim helper: feeds the vendor gpu_dvfs_ctx address to the
# gpu_dvfs_untrim module and dumps its state.
# Usage: sh gpu_untrim_setup.sh <set|state|apply|revert|freqs>

KO=/sys/kernel/gpu_dvfs_untrim

case "$1" in
set)
	ADDR=$(grep gpu_dvfs_ctx /proc/kallsyms | awk '{print $1}')
	if [ -z "$ADDR" ]; then
		echo "gpu_dvfs_ctx not in kallsyms (kptr_restrict?)"
		exit 1
	fi
	echo 0 > /proc/sys/kernel/kptr_restrict
	echo 0x$ADDR > $KO/ctx
	echo "ctx set to 0x$ADDR"
	;;
state)
	cat $KO/state
	;;
apply)
	echo 1 > $KO/untrim
	cat $KO/untrim
	;;
revert)
	echo 0 > $KO/untrim
	cat $KO/untrim
	;;
freqs)
	cat /sys/class/devfreq/23100000.gpu/available_frequencies
	echo "cur: $(cat /sys/class/devfreq/23100000.gpu/cur_freq)"
	;;
*)
	echo "usage: $0 <set|state|apply|revert|freqs>"
	exit 1
	;;
esac
