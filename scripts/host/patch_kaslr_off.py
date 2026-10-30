"""Disable KASLR in an arm64 Image by making kaslr_early_init() return 0.

Why: the kernel dies between the entry stub (band 0) and the first statement
of start_kernel() (band 1).  That window is head.S only, and its instructions
are identical to the vendor kernel's, so the difference must be in data it
consumes.  The relocation table is valid (scripts/host/scan_relocs.py), which
leaves the KASLR path: kaslr_early_init() is called from __primary_switch() and
returns the virtual displacement to apply; 0 means "no KASLR".

The patch replaces the function prologue with

    mov x0, #0
    ret

which is the same as the upstream `nokaslr` handling (`kaslr_early_init`
returns 0 before touching the FDT), while keeping the Image header and the
entry stub intact.

Addresses are per Image.p0a0s0q2; the tool refuses to patch if the bytes at
the address are not the expected prologue.

Usage:
    python scripts/host/patch_kaslr_off.py <in.img> <out.img>
"""
import pathlib
import struct
import sys

KASLR_EARLY_INIT = 0x13F0954      # kaslr_early_init, Image file offset
EXPECTED_PROLOGUE = 0xD10183FF    # sub sp, sp, #0x60
PATCH = b"".join(struct.pack("<I", w) for w in (0xD2800000, 0xD65F03C0))


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    img = bytearray(src.read_bytes())
    at = KASLR_EARLY_INIT
    orig = struct.unpack("<I", img[at:at + 4])[0]
    if orig != EXPECTED_PROLOGUE:
        raise SystemExit("unexpected prologue 0x%08x at 0x%x - wrong image or "
                         "offset (expected 0x%08x)"
                         % (orig, at, EXPECTED_PROLOGUE))
    img[at:at + len(PATCH)] = PATCH
    dst.write_bytes(bytes(img))
    print("patched %s -> %s" % (src, dst))
    print("  kaslr_early_init @0x%x: %s -> %s"
          % (at, src.read_bytes()[at:at + 8].hex(), PATCH.hex()))
    print("  (mov x0,#0 ; ret  =>  kaslr_early_init() returns 0, no KASLR)")


if __name__ == "__main__":
    main()