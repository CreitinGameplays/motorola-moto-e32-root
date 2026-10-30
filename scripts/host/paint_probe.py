"""Paint-band reach probe: patch any address with "paint band K, then hang".

Used to bisect code that runs before the C stage hooks can: the arm64 entry
path (`stext`, `__create_page_tables`, `__primary_switch`, ...).  The probe is
destructive on purpose - it overwrites 36 bytes and then spins forever - so it
only answers one question: "was this address reached?"  If the band appears on
the panel, yes; if not, no.

Bands are the same 256000-byte strips as DIAG_PAINT (scripts/host/
prepare_stage_panics.py) and the entry stub (scripts/host/entry_paint.py):
physical base 0x9e000000 + band * 256000, well inside the bootloader's
1600x720 framebuffer and below the next reserved region at 0x9f000000.

Usage:
    # file offset of a function inside the Image = VA - 0xffffff8008080000
    python scripts/host/paint_probe.py Image.p0a0s1 Image.probe.bin \
           --at 0xe1f2b0 --band 3
    # then pack the patched Image as usual
"""
import pathlib
import struct
import sys

PAINT_BASE = 0x9E000000
PAINT_BAND = 0x3E800  # 256000


def words(band):
    addr = PAINT_BASE + band * PAINT_BAND
    hi = (addr >> 16) & 0xFFFF
    lo = addr & 0xFFFF
    return [
        0xD2A00009 | (hi << 5),          # movz x9, #hi, lsl #16
        0xF2800009 | (lo << 5),          # movk x9, #lo
        0x9280000B,                      # movn x11, #0        (white)
        0xD287D00A,                      # movz x10, #16000    (256000 bytes)
        0xA8812D2B,                      # stp  x11, x11, [x9], #16
        0xF100054A,                      # subs x10, x10, #1
        0x54FFFFC1,                      # b.ne -2
        0x14000000,                      # b .                 (hang here)
    ]


def main():
    args = [a for a in sys.argv[1:]]
    at = band = None
    out_args = []
    i = 0
    while i < len(args):
        if args[i] == "--at":
            at = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--band":
            band = int(args[i + 1], 0)
            i += 2
        else:
            out_args.append(args[i])
            i += 1
    if at is None or band is None or len(out_args) != 2:
        raise SystemExit(__doc__)
    src, dst = pathlib.Path(out_args[0]), pathlib.Path(out_args[1])
    img = bytearray(src.read_bytes())
    blob = b"".join(struct.pack("<I", w) for w in words(band))
    if at < 0x40 or at + len(blob) > len(img):
        raise SystemExit("address out of range")
    before = bytes(img[at:at + len(blob)])
    img[at:at + len(blob)] = blob
    dst.write_bytes(bytes(img))
    print("probe at file offset 0x%x, band %d (phys 0x%x), %d bytes"
          % (at, band, PAINT_BASE + band * PAINT_BAND, len(blob)))
    print("  was: %s" % before.hex())
    print("  now: %s" % blob.hex())
    print("wrote %s" % dst)


if __name__ == "__main__":
    main()