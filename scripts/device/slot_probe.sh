#!/system/bin/sh
# Snapshot the slot-decision records that `fastboot set_active` touches.
#
# Usage: sh slot_probe.sh <label>
#   e.g. sh slot_probe.sh before | sh slot_probe.sh after
#
# Needs root: run mali_kroot in the same shell first.
#
# What is dumped:
#   misc   first 8 KiB -> BCB command[32] at 0x00, A/B metadata at 0x800
#   miscdata         -> the secure-world unlock marker (lock state source)
# The A/B block layout (Bootloader Control Block, Android 11):
#   0x800  char slot_suffix[4]
#   0x804  uint32 magic   "BCAB" (0x42414342 little endian)
#   0x808  uint32 version
#   0x80c  uint32 recovery_tries_remaining
#   0x810  uint32 slot_info[4] {priority, tries_remaining, successful, verity}
#   0x820  uint32 crc32
set -u

label="${1:-snap}"
out="/data/local/tmp/slot_${label}"

mkdir -p "$out" 2>/dev/null

for p in misc miscdata; do
    src="/dev/block/by-name/$p"
    if [ -e "$src" ]; then
        dd if="$src" of="$out/$p.img" bs=4096 count=2 2>/dev/null
        echo "$p $(sha256sum "$out/$p.img" | awk '{print $1}') $(wc -c < "$out/$p.img")"
    else
        echo "$p missing"
    fi
done

echo "slot_suffix=$(getprop ro.boot.slot_suffix)"
echo "--- misc 0x000 (BCB command) ---"
od -An -tx1 -N64 "$out/misc.img"
echo "--- misc 0x800 (A/B metadata) ---"
od -An -tx1 -j 2048 -N48 "$out/misc.img"