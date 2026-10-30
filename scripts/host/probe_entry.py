#!/usr/bin/env python3
"""Decode the arm64 Image entry point and (optionally) verify it.

An arm64 `Image` starts at `_head`, whose first instruction is `b stext`.
With LTO/CFI in this tree `stext` is *not* near the header (both the vendor
kernel and our build branch ~19-20 MB into the image), so the offset must be
computed from the branch encoding rather than assumed.

Usage:
    python scripts/host/probe_entry.py Image [Image2 ...]
"""
import struct
import sys


def decode(path):
    with open(path, "rb") as f:
        head = f.read(0x40)
    word = struct.unpack("<I", head[:4])[0]
    if (word >> 26) != 0x05:          # B / BL opcode
        return {"path": path, "error": "first instruction is not a B: 0x%08x" % word}
    imm = word & 0x03FFFFFF
    if imm & (1 << 25):               # sign-extend imm26
        imm -= 1 << 26
    stext = imm * 4
    return {
        "path": path,
        "first_word": word,
        "stext": stext,
        "text_offset": struct.unpack("<Q", head[8:16])[0],
        "image_size": struct.unpack("<Q", head[16:24])[0],
        "flags": struct.unpack("<Q", head[24:32])[0],
        "magic": head[0x38:0x3C],
    }


def main():
    for p in sys.argv[1:]:
        d = decode(p)
        if "error" in d:
            print("%s: %s" % (p, d["error"]))
            continue
        print("%s" % p)
        print("  first instruction 0x%08x (b)" % d["first_word"])
        print("  stext file offset 0x%x (%d)" % (d["stext"], d["stext"]))
        print("  text_offset 0x%x  image_size 0x%x  flags 0x%x  magic %s"
              % (d["text_offset"], d["image_size"], d["flags"], d["magic"]))


if __name__ == "__main__":
    main()