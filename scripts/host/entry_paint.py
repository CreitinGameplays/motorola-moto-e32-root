"""Build the 64-byte entry-paint stub and patch boot images with it.

The stub replaces the arm64 Image header (file offsets 0x00..0x3f) in the
*loaded copy*, which the bootloader no longer needs once it has parsed the
header and jumped to the image start.  It runs with the MMU off, paints a
white band at the bootloader's framebuffer base, restores the boot arguments
and branches to the real `stext` (the original first word of the Image is a
PC-relative `b stext`, so it is reused verbatim as the last instruction).

Result: a hang that shows a white bar on the panel proves the bootloader
entered our Image.  No reset, no ramoops, no console needed.

The words are the verified output of `aarch64-linux-gnu-as paint_entry.S`
(see scripts/host/paint_entry.S); tests/test_entry_paint.py re-checks them
against the assembler when run on a machine that has it.

Usage:
    python scripts/host/entry_paint.py inspect  <boot.img>
    python scripts/host/entry_paint.py stub     <Image.orig> <out.bin>
    python scripts/host/entry_paint.py patch    <boot.img> <in> <out>
"""
import pathlib
import struct
import sys

# 14 instructions, then NOP, then the image's own `b stext`.
WORDS = [
    0xAA0003F3,  # mov x19, x0        ; preserve boot args
    0xAA0103F4,  # mov x20, x1
    0xAA0203F5,  # mov x21, x2
    0xAA0303F6,  # mov x22, x3
    0xD2B3C009,  # movz x9, #0x9e00, lsl #16   ; x9 = 0x9e000000 (lcd_base)
    0x9280000B,  # movn x11, #0                 ; white
    0xD284000A,  # movz x10, #8192              ; 8192*16 = 131072 bytes (128 KB)
    0xA8812D2B,  # stp x11, x11, [x9], #16
    0xF100054A,  # subs x10, x10, #1
    0x54FFFFC1,  # b.ne -2
    0xAA1303E0,  # mov x0, x19
    0xAA1403E1,  # mov x1, x20
    0xAA1503E2,  # mov x2, x21
    0xAA1603E3,  # mov x3, x22
    0xD503201F,  # nop
]
STUB_SIZE = 64
PAINT_BYTES = 131072  # 128 KB, the band stride DIAG_PAINT_BAND


def build_stub(image_first_word):
    """64-byte stub: 14 paint instructions, a nop, then `b stext`.

    `image_first_word` may be the 4 raw bytes or the already-unpacked int.
    """
    if isinstance(image_first_word, (bytes, bytearray)):
        image_first_word = struct.unpack("<I", bytes(image_first_word))[0]
    words = WORDS + [image_first_word]
    blob = b"".join(struct.pack("<I", w) for w in words)
    assert len(blob) == STUB_SIZE, len(blob)
    return blob


def describe(boot, page=2048):
    first = struct.unpack("<I", boot[page:page + 4])[0]
    print("payload at 0x%x, first word 0x%08x" % (page, first))
    if first == WORDS[0]:
        print("  -> entry-paint stub already present")
        print("  stub: %s" % boot[page:page + STUB_SIZE].hex())
        return
    print("  -> original image (first word is the `b stext` branch)")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "stub":
        img = pathlib.Path(sys.argv[2]).read_bytes()
        out = pathlib.Path(sys.argv[3])
        stub = build_stub(struct.unpack("<I", img[:4])[0])
        out.write_bytes(stub)
        print("wrote %s (%d bytes)" % (out, len(stub)))
        print("  b stext word: 0x%08x" % struct.unpack("<I", img[:4])[0])
    elif cmd == "patch":
        boot = bytearray(pathlib.Path(sys.argv[2]).read_bytes())
        out = pathlib.Path(sys.argv[3])
        stub = build_stub(struct.unpack("<I", boot[2048:2052])[0])
        boot[2048:2048 + STUB_SIZE] = stub
        out.write_bytes(bytes(boot))
        print("patched %s -> %s" % (sys.argv[2], out))
        print("  stub: %s" % stub.hex())
    elif cmd == "inspect":
        describe(pathlib.Path(sys.argv[2]).read_bytes())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()