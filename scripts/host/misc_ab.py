#!/usr/bin/env python3
"""Decode and validate the Android A/B slot metadata inside a `misc` image.

Layout (AOSP bootloader_control, 32 bytes at misc + 2048):

    0  char     slot_suffix[4]
    4  u32      magic       0x42414342  ("BCAB")
    8  u8       version
    9  u8       nb_slot
   10  u8[2]    reserved1
   12  u16[2]   slot_info[0..1]   (this device: 2 slots)
   20  u8[8]    reserved2
   28  u32      crc32_le over bytes 0..27

slot_info bitfield (little endian u16):
    bits 0-3   priority        (0 = unbootable)
    bits 4-6   tries_remaining
    bit  7     successful_boot
    bit  8     verity_corrupted

Usage:
    python misc_ab.py <misc.image> [--offset 2048]
    python misc_ab.py --make-slot-a <out.img> <template.image>

Only reads unless --make-slot-a is used, and that variant writes to a NEW
file path that must not exist yet.
"""

import argparse
import os
import struct
import sys
import zlib

AB_OFFSET = 2048
MAGIC = 0x42414342  # "BCAB" as stored little endian


def describe(word):
    return "prio={0} tries={1} succ={2} verity={3}".format(
        word & 0xF,
        (word >> 4) & 0x7,
        (word >> 7) & 0x1,
        (word >> 8) & 0x1,
    )


def decode(image, offset):
    if len(image) < offset + 32:
        raise SystemExit("image too small for a slot block at 0x%x" % offset)
    block = image[offset:offset + 32]
    suffix = block[0:4].split(b"\x00")[0].decode("ascii", "replace")
    magic, = struct.unpack_from("<I", block, 4)
    version = block[8]
    nb_slot = block[9]
    slots = [struct.unpack_from("<H", block, 12 + 2 * i)[0] for i in range(2)]
    stored = struct.unpack_from("<I", block, 28)[0]
    computed = zlib.crc32(block[0:28]) & 0xFFFFFFFF

    print("raw            : " + " ".join("%02x" % b for b in block))
    print("slot_suffix    : %r" % suffix)
    print("magic          : 0x%08x %s" % (magic, "OK" if magic == MAGIC else "BAD"))
    print("version/nb_slot: %d / %d" % (version, nb_slot))
    for i, w in enumerate(slots):
        print("slot %s         : 0x%04x  %s" % ("ab"[i], w, describe(w)))
    print("crc stored     : 0x%08x" % stored)
    print("crc computed   : 0x%08x" % computed)
    print("crc verdict    : %s" % ("VALID" if stored == computed else "MISMATCH"))
    active = [("ab"[i], w) for i, w in enumerate(slots) if (w & 0xF) > 0]
    active.sort(key=lambda kv: kv[1] & 0xF, reverse=True)
    print("boot order     : %s" % (", ".join(k for k, _ in active) or "(none bootable)"))
    return stored == computed


def make_slot_a(template, out_path):
    image = bytearray(template)
    block = bytearray(image[AB_OFFSET:AB_OFFSET + 32])
    if struct.unpack_from("<I", block, 4)[0] != MAGIC:
        raise SystemExit("template has no BCAB block at 0x%x" % AB_OFFSET)
    # slot a: priority 15, tries 1, successful 1  -> 0x009f
    # slot b: priority 14, tries 0, successful 0  -> 0x000e
    struct.pack_into("<H", block, 12, 0x009F)
    struct.pack_into("<H", block, 14, 0x000E)
    block[0:4] = b"_a\x00\x00"
    struct.pack_into("<I", block, 28, zlib.crc32(bytes(block[0:28])) & 0xFFFFFFFF)
    image[AB_OFFSET:AB_OFFSET + 32] = block
    with open(out_path, "wb") as fh:
        fh.write(image)
    print("wrote %s" % out_path)
    decode(bytes(image), AB_OFFSET)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--offset", type=lambda s: int(s, 0), default=AB_OFFSET)
    ap.add_argument("--make-slot-a", metavar="TEMPLATE")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.make_slot_a:
        if not args.image:
            raise SystemExit("--make-slot-a needs an output path as the positional argument")
        if os.path.exists(args.image):
            raise SystemExit("refusing to overwrite existing file: %s" % args.image)
        with open(args.make_slot_a, "rb") as fh:
            make_slot_a(fh.read(), args.image)
        return 0

    if not args.image:
        raise SystemExit("need a misc image path")
    with open(args.image, "rb") as fh:
        image = fh.read()
    print("file           : %s (%d bytes)" % (args.image, len(image)))
    print("offset         : 0x%x" % args.offset)
    return 0 if decode(image, args.offset) else 2


if __name__ == "__main__":
    sys.exit(main())