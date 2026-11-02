#!/bin/bash
# Observe one boot of the CFI-fixed baseline kernel from boot_b.
# Flash/arm must already be done and verified; this script only reboots,
# watches adb, and captures the classification data.
# Usage: observe_boot_test.sh [window-seconds]
set -u
ADB="D:/AndroidSDKTools/adb/adb.exe"
FASTBOOT="D:/AndroidSDKTools/platform-tools/fastboot.exe"
[ -x "$FASTBOOT" ] || FASTBOOT=$(dirname "$ADB")/fastboot.exe
WIN="${1:-900}"
PREFIX="${2:-cfibase}"
LOG="artifacts/kernel-build/${PREFIX}_boot_observation.log"
: > "$LOG"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "reboot issued (window ${WIN}s)"
"$ADB" reboot
start=$(date +%s)
first_seen=""
n=0
while [ $(( $(date +%s) - start )) -lt "$WIN" ]; do
    t=$(( $(date +%s) - start ))
    n=$((n+1))
    st=$("$ADB" get-state 2>/dev/null | tr -d '\r')
    if [ "$st" = "device" ]; then
        first_seen=$t
        log "t+${t}s adb FIRST SEEN"
        break
    fi
    if [ $((n % 10)) -eq 0 ]; then
        fb=$("$FASTBOOT" devices 2>/dev/null | tr -d '\r')
        [ -n "$fb" ] && log "t+${t}s fastboot device present: $fb"
    fi
    sleep 3
done

if [ -z "$first_seen" ]; then
    log "t+${WIN}s NO ADB within window => HANG (operator may power-cycle)"
    exit 0
fi

sleep 5
log "--- first-contact classification ---"
"$ADB" shell "cat /proc/version; getprop sys.boot_completed; getprop ro.boot.slot_suffix; getenforce" >> "$LOG" 2>&1
log "su check:"
"$ADB" shell "su -c id -u" >> "$LOG" 2>&1

# wait for boot_completed up to 180s
bc=""
bt=0
while [ $bt -lt 180 ]; do
    bc=$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n')
    [ "$bc" = "1" ] && break
    sleep 5
    bt=$((bt+5))
done
log "boot_completed=${bc:-0} after t+$((first_seen + bt))s"

if "$ADB" shell "su -c true" >/dev/null 2>&1; then
    log "--- root captures ---"
    "$ADB" shell "su -c 'ls /sys/fs/pstore/'" >> "$LOG" 2>&1
    "$ADB" shell "su -c 'cat /sys/fs/pstore/console-ramoops-0'" \
        > "artifacts/kernel-build/${PREFIX}_console-ramoops-0.txt" 2>&1
    "$ADB" shell "su -c 'cat /sys/fs/pstore/dmesg-ramoops-0'" \
        > "artifacts/kernel-build/${PREFIX}_dmesg-ramoops-0.txt" 2>&1
    "$ADB" shell "su -c dmesg" > "artifacts/kernel-build/${PREFIX}_dmesg.txt" 2>&1
    log "pstore + dmesg captured"
    log "notifier-WARN count in dmesg:"
    grep -c "Invalid notifier called" "artifacts/kernel-build/${PREFIX}_dmesg.txt" >> "$LOG" 2>&1
    log "smp/kvm lines:"
    grep -E "smp: Brought up|kvm|KVM" "artifacts/kernel-build/${PREFIX}_dmesg.txt" | head -8 >> "$LOG" 2>&1
else
    log "no su on this boot; pstore capture skipped"
fi
log "observation complete"
