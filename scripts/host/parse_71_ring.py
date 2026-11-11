#!/usr/bin/env python3
"""Extract the kernel ring that the 7.1 test boots saved into sysdumpdb.

The 7.1 initramfs (logsave, and the hybrid variant that hands over to
the stock Android init) writes the kernel ring into the sysdumpdb
partition every second: a 16-byte header ("H71LOG01" + a big-endian
length) followed by the raw ring text, at 1 MiB and (as a backup) at
2 MiB into the partition.

Usage:
    adb exec-out su -c 'dd if=/dev/block/by-name/sysdumpdb bs=1M count=10' \\
        > sysdump.bin
    parse_71_ring.py sysdump.bin [--tail N] [--grep PATTERN]

Note: use `adb exec-out`, not `adb shell` - the shell pty converts LF to
CRLF and corrupts the binary blob.
"""

import argparse
import re
import struct
import sys

MAGIC = b"H71LOG01"
OFFSETS = (1 << 20, 2 << 20)


def extract(data):
    """Yield the ring snapshots found in the partition image."""
    for off in OFFSETS:
        if data[off:off + 8] != MAGIC:
            continue
        length = struct.unpack(">I", data[off + 8:off + 12])[0]
        yield off, data[off + 16:off + 16 + length].decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--tail", type=int, default=40, help="last N lines")
    ap.add_argument("--grep", help="only lines matching this regex")
    ap.add_argument("--all", action="store_true", help="print the whole ring")
    args = ap.parse_args()

    data = open(args.image, "rb").read()
    rings = list(extract(data))
    if not rings:
        sys.exit("no H71LOG01 snapshot in %s" % args.image)

    for off, ring in rings:
        lines = ring.splitlines()
        print("=== snapshot at 0x%x: %d lines, %d bytes" % (off, len(lines), len(ring)))
        if args.grep:
            pat = re.compile(args.grep, re.I)
            lines = [l for l in lines if pat.search(l)]
        if args.all:
            for l in lines:
                print(l)
        else:
            for l in lines[-args.tail:]:
                print(l)
        print()


if __name__ == "__main__":
    main()
