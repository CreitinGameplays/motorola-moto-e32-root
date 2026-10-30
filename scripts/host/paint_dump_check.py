#!/usr/bin/env python3
"""Report which paint bands of a physical-memory dump are filled with 0xff.

    python3 paint_dump_check.py <dump> [base] [band]

Used to validate the framebuffer stages offline: boot the instrumented
kernel in QEMU, dump physical 0x9e000000, and see which bands were painted.
"""
import sys

BASE = 0x9E000000
BAND = 0x20000


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/debian/paintcheck.bin"
    base = int(sys.argv[2], 0) if len(sys.argv) > 2 else BASE
    band = int(sys.argv[3], 0) if len(sys.argv) > 3 else BAND
    d = open(path, "rb").read()
    print("dump %s: %d bytes (0x%x), base 0x%x, band 0x%x"
          % (path, len(d), len(d), base, band))
    n = len(d) // band
    reached = 0
    for i in range(n):
        blk = d[i * band:(i + 1) * band]
        painted = blk.count(0xFF)
        frac = painted / float(len(blk))
        mark = "PAINTED" if frac > 0.99 else ("part" if frac > 0.01 else "-")
        print("  band %-2d  0xff %7.3f%%  %s" % (i, frac * 100, mark))
        if frac > 0.99:
            reached = i
    print("last painted band: %d" % reached)


if __name__ == "__main__":
    main()