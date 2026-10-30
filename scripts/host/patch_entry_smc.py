#!/usr/bin/env python3
"""Patch the arm64 Image entry (`stext`) with a PSCI SYSTEM_RESET probe.

Why: the stage hooks live in C code, i.e. inside start_kernel().  If a stage-1
hook does not reset the SoC, either the kernel never gets there or the reset
path is broken.  This patch removes the ambiguity by doing the SMC at `stext`,
the first arm64 instruction the bootloader's branch reaches.

The stub preserves x0..x3 (the boot protocol arguments, x0 = DTB) so that an
unsupported SMC simply returns and the boot continues unchanged.

Usage (on the VPS, where aarch64-linux-gnu-as lives):
    python3 patch_entry_smc.py <in.img> <out.img>
    python3 patch_entry_smc.py <in.img> <out.img> --at=0xADDR

`--at` overwrites 11 instructions at an arbitrary file offset (e.g. the
`__primary_switch` target the entry branch reaches) with the same stub, which
turns it into a reach probe for that address.

The patched entry is verified with objdump before anything is packaged.
"""
import pathlib
import struct
import subprocess
import sys

STUB = """
	.section .text
	.global probe
probe:
	mov	x19, x0
	mov	x20, x1
	mov	x21, x2
	mov	x22, x3
	movz	x0, #0x0009
	movk	x0, #0x8400, lsl #16
	smc	#0
	mov	x0, x19
	mov	x1, x20
	mov	x2, x21
	mov	x3, x22
"""


def entry_offset(img):
    word = struct.unpack("<I", img[:4])[0]
    if (word >> 26) != 0x05:
        raise SystemExit("first word 0x%08x is not a B instruction" % word)
    imm = word & 0x03FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return imm * 4


def assemble(tmpdir):
    src = tmpdir / "stub.S"
    obj = tmpdir / "stub.o"
    bin_ = tmpdir / "stub.bin"
    src.write_text(STUB)
    subprocess.run(["aarch64-linux-gnu-as", "-o", str(obj), str(src)], check=True)
    subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", "--only-section=.text",
                    str(obj), str(bin_)], check=True)
    return bin_.read_bytes()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    at = None
    for a in sys.argv[1:]:
        if a.startswith("--at="):
            at = int(a.split("=", 1)[1], 0)
        elif a == "--at":
            raise SystemExit("use --at=0xADDR")
    if len(args) != 2:
        raise SystemExit(__doc__)
    src = pathlib.Path(args[0])
    dst = pathlib.Path(args[1])
    img = bytearray(src.read_bytes())
    stext = entry_offset(img)
    # An explicit address lets the same stub probe any instruction, e.g. the
    # __primary_switch target, to bisect inside head.S.  The stub overwrites
    # 11 instructions from there: if the address is never reached nothing is
    # corrupted, so "reset vs hang" stays a valid reach probe.
    off = stext if at is None else at
    tmpdir = pathlib.Path("/tmp/entryprobe")
    tmpdir.mkdir(exist_ok=True)
    stub = assemble(tmpdir)
    if len(stub) != 44:
        raise SystemExit("unexpected stub size %d (want 44 = 11 insns)" % len(stub))
    print("stext file offset 0x%x, probing 0x%x, stub %d bytes"
          % (stext, off, len(stub)))
    if off < 0x1000 or off + len(stub) > len(img):
        raise SystemExit("address out of range")
    # -b binary: objdump addresses are plain file offsets, so do NOT pass
    # --adjust-vma (that would make --start-address select file offset 0, the
    # Image header, and print a misleading disassembly).
    def dump(path, start, stop, ctx=0):
        r = subprocess.run(
            ["aarch64-linux-gnu-objdump", "-D", "-b", "binary", "-m", "aarch64",
             "--start-address=0x%x" % max(0, start - ctx),
             "--stop-address=0x%x" % stop, str(path)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = [ln for ln in r.stdout.split("\n") if ln.strip()]
        return "\n".join(lines[-ctx and -20 or -14:])

    print("--- before (context) ---")
    print(dump(src, off, off + 44, 16))
    img[off:off + len(stub)] = stub
    dst.write_bytes(img)
    print("--- after (patched) ---")
    print(dump(dst, off, off + 44))
    print("wrote %s" % dst)


if __name__ == "__main__":
    main()