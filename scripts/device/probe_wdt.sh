#!/system/bin/sh
# Read-only inventory of the watchdog / panic / reset infrastructure on stock.
# Establishes whether a watchdog can reset this SoC and whether Android arms it.
set -u

/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== /dev/watchdog* ==="
ls -l /dev/watchdog* 2>&1
echo
echo "=== watchdog class ==="
for w in /sys/class/watchdog/watchdog*; do
    [ -e "$w" ] || continue
    printf '%s\n' "$w"
    for p in identity timeout min_timeout max_timeout state nowayout pretimeout bootstatus; do
        [ -e "$w/$p" ] && printf '   %-11s %s\n' "$p" "$(cat "$w/$p" 2>/dev/null)"
    done
done
echo
echo "=== watchdog platform drivers ==="
for d in /sys/bus/platform/drivers/*wdt* /sys/bus/platform/drivers/*watchdog*; do
    [ -e "$d" ] || continue
    echo "$d"
    ls "$d" 2>/dev/null | grep -v '^bind$' | grep -v '^unbind$' | grep -v '^uevent$' | sed 's/^/   /'
done
echo
echo "=== cmdline ==="
cat /proc/cmdline
echo
echo "=== panic settings ==="
for f in panic panic_on_oops panic_on_warn softlockup_panic hung_task_panic hung_task_timeout_secs; do
    [ -e "/proc/sys/kernel/$f" ] && printf '%-26s %s\n' "$f" "$(cat /proc/sys/kernel/$f)"
done
echo
echo "=== dmesg: watchdog / kvm / EL2 / psci / sysdump ==="
dmesg 2>/dev/null | grep -i -E 'watchdog|wdt|kvm|EL2|psci|sysdump|hyp' | head -40
echo
echo "=== sysdump ==="
ls -l /proc/sprd_sysdump /dev/block/by-name/sysdumpdb 2>&1
cat /sys/module/sprd_sysdump/parameters/* 2>/dev/null | head
echo
echo "=== who arms a watchdog in userspace? ==="
ps -A 2>/dev/null | grep -i -E 'watchdog|wdt' | head