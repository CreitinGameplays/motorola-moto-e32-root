#!/system/bin/sh
# What did the slot-a / slot_suffix=_b experiment leave behind?
set -u
for i in 1 2 3 4 5 6; do
    /data/local/tmp/mali_kroot >/dev/null 2>&1
    [ "$(id -u)" = "0" ] && break
    sleep 2
done
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }

echo "=== current state ==="
getprop ro.boot.slot_suffix
getprop sys.boot_completed
cat /proc/version
cat /proc/uptime
echo

echo "=== boot reasons (did the bootloader give up on slot a?) ==="
getprop persist.sys.boot.reason.history
echo "sys.rescue_boot_count = $(getprop sys.rescue_boot_count)"
echo "ro.boot.bootreason    = $(getprop ro.boot.bootreason)"
echo

echo "=== boot_a / boot_b hashes ==="
for p in boot_a boot_b; do
    l=$(readlink -f /dev/block/by-name/$p)
    printf '%s ' "$p"
    dd if="$l" bs=4096 2>/dev/null | sha256sum
done
echo "expected boot_suffixb : 9ae277c0dde0aba1071d431123e1b2c76721225a206debacdea92395c0914f58"
echo "expected stock boot_b : ccd0faff51ab24d921b2671c562f0fe08e7a1ba2b7f19bb93a5f2650eb4f7b18"
echo "expected stock boot_a : 55ddec277b4ce01d2514a46b19ebf0b271fc30572ad4373ef197a0d73246db77"
echo

echo "=== pstore ==="
ls -la /sys/fs/pstore/ 2>&1
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    echo "--- $f ($(wc -c < "$f") bytes)"
    head -c 1500 "$f" | tr -d '\000'
    echo
done
echo

echo "=== did our cmdline token ever reach the kernel? ==="
tr ' ' '\n' < /proc/cmdline | grep -c 'androidboot.slot_suffix'
tr ' ' '\n' < /proc/cmdline | grep 'slot_suffix'
tr ' ' '\n' < /proc/cmdline | grep -c 'diagmarker'
echo "(counts above: slot_suffix occurrences, the values, diagmarker occurrences)"