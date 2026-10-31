"""Build the framebuffer entry stub and attach it to a kernel Image.

Two generations live here:

* `build_stub()` - the legacy 64-byte stub that *overwrote the arm64 Image
  header* (file offsets 0x00..0x3f).  It still works on this bootloader, but it
  destroys `text_offset`, `image_size`, `flags` and the `ARMd` magic, so the
  loaded copy is no longer a valid arm64 Image.  Kept only to inspect old
  images.

* `attach()` - the current one.  The stub is **appended after the Image** and
  only the single `b stext` word at offset 0 is retargeted to it.  The header
  stays byte-identical (`text_offset`, `image_size`, flags, magic all intact),
  the boot-image `kernel_size`/SHA-1 are recomputed by the packer, and the stub
  sits inside the region the kernel already reserves for BSS - it runs with the
  MMU off before anything can clear it, then branches to the original entry.

The stub fills the *whole* panel (1600x720x32 = 4,608,000 bytes at physical
0x9e000000 = the bootloader's `lcd_base`) with 0xffffffff.  A full white screen
cannot be confused with a bootloader logo, a charging indicator or a progress
bar, which is the point: it calibrates the observation channel itself before any
result is trusted.

Usage:
    python scripts/host/entry_paint.py inspect  <boot.img>
    python scripts/host/entry_paint.py stub     <Image.orig> <out.bin>
    python scripts/host/entry_paint.py attach   <Image.orig> <out-Image> [halt]
"""
import pathlib
import struct
import sys

LCD_BASE = 0x9E000000
PANEL_W, PANEL_H, BPP = 1600, 720, 32
PAINT_BYTES_FULL = PANEL_W * PANEL_H * BPP // 8      # 4,608,000

# Legacy 64-byte header-replacing stub (14 instructions, nop, branch word).
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

# Appended stub: verified against `aarch64-linux-gnu-as` on
# scripts/host/paint_entry.S.  It touches only x9/x10/x11, so the boot
# arguments in x0..x3 reach stext untouched.
LCD_MOVZ = 0xD2B3C009        # movz x9, #0x9e00, lsl #16   ; x9 = lcd_base
STP = 0xA8812D2B             # stp  x11, x11, [x9], #16
SUBS = 0xF100054A            # subs x10, x10, #1
BNE = 0x54FFFFC1             # b.ne -2
COUNT = [0xD2A0008A, 0xF28CA00A]   # x10 = 0x46500 steps = 4,608,000 bytes
WHITE = 0xFFFFFFFF
HALT_WORD = 0x14000000                               # b .


def movz(rd, imm, shift=0):
    """MOVZ Xd, #imm16, LSL #shift (shift must be a multiple of 16)."""
    return 0xD2800000 | ((shift // 16) << 21) | ((imm & 0xFFFF) << 5) | rd


def movk(rd, imm, shift=0):
    """MOVK Xd, #imm16, LSL #shift."""
    return 0xF2800000 | ((shift // 16) << 21) | ((imm & 0xFFFF) << 5) | rd


def colour_words(reg, value):
    """Shortest movz/movk sequence that loads a 64-bit constant."""
    if value == 0xFFFFFFFFFFFFFFFF:
        return [0x92800000 | reg]        # movn Xd, #0
    chunks = [(value >> s) & 0xFFFF for s in range(0, 64, 16)]
    first = next(i for i, c in enumerate(chunks) if c)
    out = [movz(reg, chunks[first], first * 16)]
    out += [movk(reg, c, i * 16) for i, c in enumerate(chunks)
            if c and i != first]
    return out


def build_stub(image_first_word):
    """Legacy 64-byte stub: paint 128 KB, then branch to the original entry."""
    if isinstance(image_first_word, (bytes, bytearray)):
        image_first_word = struct.unpack("<I", bytes(image_first_word))[0]
    words = WORDS + [image_first_word]
    blob = b"".join(struct.pack("<I", w) for w in words)
    assert len(blob) == STUB_SIZE, len(blob)
    return blob


def tail_words(colour=WHITE):
    """The stub body: fill the whole panel with `colour`, then branch."""
    return ([LCD_MOVZ] + colour_words(11, colour) + COUNT +
            [STP, SUBS, BNE])


def build_tail_stub(branch_word, colour=WHITE):
    """Appended stub: fill the panel, then branch (or halt) with `branch_word`.

    `branch_word` must already be encoded for the stub's own location - a `b`
    is PC-relative, so reusing the Image's original code0 word here would jump
    far past stext.
    """
    words = tail_words(colour) + [branch_word]
    blob = b"".join(struct.pack("<I", w) for w in words)
    return blob


def stub_size(colour=WHITE):
    return len(tail_words(colour)) * 4 + 4


def decode_b(from_off, word):
    """Decode a `b`/`bl` word and return the absolute target offset."""
    op = word & 0xFC000000
    if op not in (0x14000000, 0x94000000):
        raise ValueError("word 0x%08x is not a b/bl" % word)
    imm = word & 0x3FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return from_off + imm * 4


def branch(from_off, to_off):
    """Encode `b` from file offset `from_off` to `to_off` (same image)."""
    delta = to_off - from_off
    if delta % 4:
        raise ValueError("branch target not 4-byte aligned")
    imm = delta // 4
    if not (-(1 << 25) <= imm < (1 << 25)):
        raise ValueError("branch out of range: %d bytes" % delta)
    return 0x14000000 | (imm & 0x3FFFFFF)


def attach(kernel, halt=False, colour=WHITE):
    """Return (new_kernel, info) with the stub appended and code0 retargeted.

    The arm64 Image header is left untouched apart from the `b stext` word at
    offset 0, which now branches to the appended stub.  The stub ends with a
    *re-encoded* branch to the original target, because it executes at a
    different address than code0 did.
    """
    if kernel[0x38:0x3c] != b"ARMd":
        raise ValueError("not an arm64 Image (no ARMd magic)")
    if len(kernel) % 4:
        raise ValueError("kernel length is not 4-byte aligned")
    original_code0 = struct.unpack("<I", kernel[:4])[0]
    stext = decode_b(0, original_code0)
    if not 0 <= stext < len(kernel):
        raise ValueError("code0 target 0x%x outside the Image" % stext)

    stub_at = len(kernel)
    size = stub_size(colour)
    branch_slot = stub_at + size - 4
    tail_branch = HALT_WORD if halt else branch(branch_slot, stext)
    stub = build_tail_stub(tail_branch, colour)
    assert len(stub) == size, (len(stub), size)
    new_code0 = branch(0, stub_at)
    out = struct.pack("<I", new_code0) + kernel[4:] + stub
    info = dict(stub_at=stub_at, stub_size=size, code0=new_code0,
                original_code0=original_code0, stext=stext,
                tail_branch=tail_branch, stub=stub, colour=colour,
                paint_bytes=PAINT_BYTES_FULL)
    return out, info


def describe(boot, page=2048):
    first = struct.unpack("<I", boot[page:page + 4])[0]
    print("payload at 0x%x, first word 0x%08x" % (page, first))
    if first == WORDS[0]:
        print("  -> legacy header-replacing stub present (header destroyed)")
        print("  stub: %s" % boot[page:page + STUB_SIZE].hex())
        return
    print("  -> no legacy stub at the payload start")
    if boot[page + 0x38:page + 0x3c] == b"ARMd":
        print("  -> arm64 header intact (ARMd magic at 0x38)")
    else:
        print("  -> WARNING: arm64 header damaged")


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
        print("patched %s -> %s (LEGACY header-replacing stub)" % (sys.argv[2], out))
        print("  stub: %s" % stub.hex())
    elif cmd == "attach":
        img = pathlib.Path(sys.argv[2]).read_bytes()
        out = pathlib.Path(sys.argv[3])
        halt = len(sys.argv) > 4 and sys.argv[4].lower() in ("halt", "hang", "1")
        colour = int(sys.argv[5], 0) if len(sys.argv) > 5 else WHITE
        new, info = attach(img, halt, colour)
        out.write_bytes(new)
        print("wrote %s: %d -> %d bytes (%s)"
              % (out, len(img), len(new), "halt" if halt else "continue"))
        print("  stub at 0x%x (%d bytes), code0 0x%08x (was 0x%08x)"
              % (info["stub_at"], info["stub_size"], info["code0"],
                 info["original_code0"]))
        print("  stext at 0x%x, stub tail branch 0x%08x"
              % (info["stext"], info["tail_branch"]))
        print("  fills %d bytes (%dx%d at 0x%08x) with 0x%08x"
              % (info["paint_bytes"], PANEL_W, PANEL_H, LCD_BASE, colour))
        print("  header magic still %r" % new[0x38:0x3c])
    elif cmd == "inspect":
        describe(pathlib.Path(sys.argv[2]).read_bytes())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()