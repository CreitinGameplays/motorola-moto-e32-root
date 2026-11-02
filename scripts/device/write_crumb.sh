#!/system/bin/sh
# Persistent-crumb writer for kernel probes (v2).
#
# The Mali module probe hangs the CPU so hard that no in-RAM log survives
# (no console output, no pstore panic, page cache lost on the cold reset).
# This writes a small marker DIRECTLY to flash - a fixed scratch offset in
# the miscdata partition (sda2, 1 MiB) - where it survives any reset.
#
# Probed on-device 2026-11-02:
#   miscdata+0x0000   production data (serial, DOWNLOAD/WRITESN/CFT/BBAT/
#                     WCN/ANTENNA/IMEI blocks) - DO NOT TOUCH
#   miscdata+0x1000.. 0xff padding, then more production blobs near 0x2000
#   miscdata+0x2000+  zero-filled for the rest of the partition (verified
#                     at 0x4000/0x8000/0x10000...0xF4240)
#   UFS, not NAND: writing zeros erases; writes need no erase block
#   a write+read-back test at 0xA0000 worked (then zeroed again)
#
# Chosen scratch: miscdata+0xA0000 (640 KiB). Magic 'CRUMB01'.
# Steps are single hex bytes written after the magic, in order.
#
# Usage (root):
#   sh /data/local/tmp/write_crumb.sh 0      clear all crumbs
#   sh /data/local/tmp/write_crumb.sh <1..n> record step n
MISC=/dev/block/by-name/miscdata
OFF=655360   # 0xA0000
step="$1"

case "$step" in
  ''|*[!0-9]*) echo "usage: $0 <step 0..255>"; exit 1;;
esac

if [ "$step" = "0" ]; then
    # zero the whole 64-byte scratch region
    dd if=/dev/zero of="$MISC" bs=1 seek=$OFF count=64 conv=notrunc 2>/dev/null
    sync
    echo "crumbs cleared"
else
    printf 'CRUMB%02x' "$step" | dd of="$MISC" bs=1 seek=$OFF conv=notrunc 2>/dev/null
    sync
fi

# read back and print
dd if="$MISC" bs=1 skip=$OFF count=16 2>/dev/null | od -An -c | head -2
