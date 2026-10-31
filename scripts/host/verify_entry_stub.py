#!/usr/bin/env python3
"""Verify a packed boot image whose entry stub fills the panel.

Simulates the branch chain the bootloader will follow:

    payload+0  --b-->  appended stub  --b-->  stext (or `b .` in halt mode)

and checks that the arm64 Image header is still valid, that the stub sits
inside the loaded `kernel_size`, and that the fill really covers the panel.

Usage: python scripts/host/verify_entry_stub.py <boot.img> [...]
"""
import pathlib
import struct
import sys

PANEL_BYTES = 1600 * 720 * 32 // 8          # 4,608,000 bytes
LCD_BASE = 0x9E000000
PAGE = 2048
MAX_STUB_WORDS = 12


def decode_b(word):
    imm = word & 0x3FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return imm * 4


def fill_bytes(words):
    """Bytes the stub writes: movz/movk build x10, each `stp` writes 16."""
    counter = None
    for w in words:
        op = w & 0xFF800000
        if op not in (0xD2800000, 0xF2800000):     # movz / movk
            continue
        if (w & 0x1F) != 10:                       # Rd must be x10
            continue
        part = ((w >> 5) & 0xFFFF) << (((w >> 21) & 0x3) * 16)
        if op == 0xD2800000:
            counter = part
        elif counter is not None:
            counter |= part
    return None if not counter else counter * 16


def check(path):
    d = pathlib.Path(path).read_bytes()
    ksize = struct.unpack("<I", d[0x08:0x0C])[0]
    k = d[PAGE:PAGE + ksize]
    print("== %s" % path)

    text_off, img_size = struct.unpack("<2Q", k[0x08:0x18])
    magic = k[0x38:0x3C]
    print("   kernel_size 0x%-8x text_offset 0x%-6x image_size 0x%-8x magic %r"
          % (ksize, text_off, img_size, magic))
    if magic != b"ARMd":
        print("   FAIL: arm64 header damaged")
        return False

    code0 = struct.unpack("<I", k[0:4])[0]
    if code0 & 0xFC000000 != 0x14000000:
        print("   FAIL: code0 is not a `b` (0x%08x)" % code0)
        return False
    stub = decode_b(code0)
    if not 0 < stub or stub + 8 > ksize:
        print("   FAIL: stub 0x%x outside the loaded kernel_size" % stub)
        return False
    print("   code0 0x%08x -> stub at payload+0x%x" % (code0, stub))

    words = list(struct.unpack("<%dI" % ((ksize - stub) // 4),
                               k[stub:stub + 4 * ((ksize - stub) // 4)]))
    if len(words) > MAX_STUB_WORDS:
        words = words[:MAX_STUB_WORDS]
    body = words[:words.index(0x14000000) + 1] if 0x14000000 in words[:6] else None
    print("   %s" % " ".join("%08x" % w for w in (body or words[:8])))

    fill = fill_bytes(body or words)
    if fill == PANEL_BYTES:
        print("   fill %d bytes at 0x%08x = whole 1600x720 panel"
              % (fill, LCD_BASE))
    else:
        print("   WARN: fill is %s bytes, expected %d" % (fill, PANEL_BYTES))

    # the stub's last word is its branch: find the first `b` after the loop
    branch_idx = next((i for i, w in enumerate(words)
                       if i >= 5 and w & 0xFC000000 == 0x14000000
                       and w != 0x14000000 or (i >= 5 and w == 0x14000000)), None)
    if branch_idx is None:
        print("   FAIL: no branch word found in the stub")
        return False
    slot = stub + 4 * branch_idx
    last = words[branch_idx]
    if last == 0x14000000:
        print("   stub tail at +0x%x is `b .` -> HALT (calibration image)"
              % slot)
        return fill == PANEL_BYTES
    target = slot + decode_b(last)
    print("   stub tail at +0x%x 0x%08x -> payload+0x%x"
          % (slot, last, target))
    if not 0 <= target < ksize:
        print("   FAIL: tail branch leaves the image")
        return False
    return fill == PANEL_BYTES


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if not all(check(p) for p in sys.argv[1:]):
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()