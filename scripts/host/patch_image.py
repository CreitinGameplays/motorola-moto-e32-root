"""Named binary patches for the arm64 Image: cheap boot experiments, no rebuild.

The kernel now dies between the entry stub (band 0, MMU off) and the first
statement of start_kernel() (band 1).  Everything in between is head.S:
__create_page_tables -> __enable_mmu -> relocation -> __primary_switched
(includes the BSS clear) -> optional KASLR -> start_kernel().  Each patch below
removes one candidate so the next boot tells us whether it was the culprit.

    --kaslr-off   kaslr_early_init() becomes `mov x0,#0 ; ret`, i.e. return 0
                  ("no KASLR"), the same result as the `nokaslr` command line.
    --bss-skip    the BSS clear's length is forced to 0 (memset(x,0,0)), so the
                  3 MB memset is skipped.  If band 1 appears afterwards, the
                  memset was where the kernel died.

Both are keyed to the addresses in Image.p0a0s0q2 (the 20-band trace build) and
refuse to patch if the bytes are not what is expected.

Usage:
    python scripts/host/patch_image.py <in> <out> --kaslr-off [--bss-skip]
"""
import pathlib
import struct
import sys

# file offset -> (expected word, replacement word, description)
PATCHES = {
    "--kaslr-off": [
        (0x13F0954, 0xD10183FF, 0xD2800000, "kaslr_early_init: sub sp -> mov x0,#0"),
        (0x13F0958, 0xA9017BFD, 0xD65F03C0, "kaslr_early_init: stp   -> ret"),
    ],
    "--bss-skip": [
        (0x13E01EC, 0xCB000042, 0xAA1F03E2, "bss clear: sub x2,x2,x0 -> mov x2,xzr"),
    ],
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) != 2 or not names:
        raise SystemExit(__doc__)
    src, dst = pathlib.Path(args[0]), pathlib.Path(args[1])
    img = bytearray(src.read_bytes())
    for name in names:
        if name not in PATCHES:
            raise SystemExit("unknown patch %s" % name)
        for off, want, new, what in PATCHES[name]:
            got = struct.unpack("<I", img[off:off + 4])[0]
            if got != want:
                raise SystemExit("%s: 0x%x has 0x%08x, expected 0x%08x (%s)"
                                 % (dst, off, got, want, what))
            struct.pack_into("<I", img, off, new)
        print("%s: %d words patched" % (name, len(PATCHES[name])))
    dst.write_bytes(bytes(img))
    print("wrote %s" % dst)


if __name__ == "__main__":
    main()