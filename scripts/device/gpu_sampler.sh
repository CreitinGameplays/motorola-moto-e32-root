#!/system/bin/sh
# GPU DVFS sampler - run on the device as root:
#   sh /data/local/tmp/gpu_sampler.sh <tag> &
# Records uptime, devfreq cur/max/target freq and the GPU thermal-zone
# temperature once per second to /data/local/tmp/gpubench_<tag>.log
TAG="${1:-tag}"
LOG="/data/local/tmp/gpubench_${TAG}.log"

ZONE=""
for z in /sys/class/thermal/thermal_zone*; do
    t=$(cat "$z/type" 2>/dev/null)
    case "$t" in
        *gpu*) ZONE="$z" ;;
    esac
done

: > "$LOG"
echo "# sampler start: tag=$TAG zone=$ZONE" >> "$LOG"
while :; do
    up=$(cut -d ' ' -f1 /proc/uptime)
    freq=$(cat /sys/class/devfreq/23100000.gpu/cur_freq 2>/dev/null)
    max=$(cat /sys/class/devfreq/23100000.gpu/max_freq 2>/dev/null)
    tgt=$(cat /sys/class/devfreq/23100000.gpu/target_freq 2>/dev/null)
    temp=$(cat "$ZONE/temp" 2>/dev/null)
    echo "$up freq=$freq max=$max tgt=$tgt temp=$temp" >> "$LOG"
    sleep 1
done
