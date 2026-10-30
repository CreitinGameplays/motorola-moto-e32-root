#!/usr/bin/env python3
"""Validate the arm64 Image relocation table used by __relocate_kernel.

Each Elf64_Rela is {r_offset u64, r_info u64, r_addend i64} = 24 bytes.
__relocate_kernel adds the KASLR/misalignment displacement to r_offset and
writes there, so every r_offset MUST be inside the kernel image; otherwise the
store lands on an unmapped address, faults before the vectors exist, and the
board dies silently - exactly the symptom under investigation.

Usage:
    python3 scan_relocs.py <Image> <rela_offset> <rela_size> [image_size]
"""
import struct
import sys

KIMAGE_VADDR = 0xFFFFFF8008080000
R_AARCH64_RELATIVE = 1027


def main():
    path = sys.argv[1]
    off = int(sys.argv[2], 0)
    size = int(sys.argv[3], 0)
    image_size = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0x1BB1000
    d = open(path, "rb").read()
    n = size // 24
    print("%s: rela at file 0x%x, size 0x%x (%d full entries, %d trailing bytes)"
          % (path, off, size, n, size % 24))
    print("  image VA range: 0x%x .. 0x%x"
          % (KIMAGE_VADDR, KIMAGE_VADDR + image_size))
    bad = 0
    types = {}
    lo, hi = None, None
    for i in range(n):
        e = d[off + i * 24: off + (i + 1) * 24]
        r_off, r_info, r_add = struct.unpack("<QQq", e)
        t = r_info & 0xFFFFFFFF
        types[t] = types.get(t, 0) + 1
        if lo is None or r_off < lo:
            lo = r_off
        if hi is None or r_off > hi:
            hi = r_off
        if not (KIMAGE_VADDR <= r_off < KIMAGE_VADDR + image_size):
            if bad < 5:
                print("  BAD entry %d: r_offset 0x%x info 0x%x addend 0x%x"
                      % (i, r_off, r_info, r_add))
            bad += 1
    print("  entry types: %s" % sorted(types.items())[:6])
    print("  r_offset range: 0x%x .. 0x%x" % (lo, hi))
    print("  out-of-image entries: %d" % bad)


if __name__ == "__main__":
    main()