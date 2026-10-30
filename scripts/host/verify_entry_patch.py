#!/usr/bin/env python3
"""Verify that patch_entry_smc.py really wrote the SMC stub at `stext`.

    python3 verify_entry_patch.py Image.orig Image.patched

It decodes `_head`'s `b stext`, re-assembles the stub with the same source
patch_entry_smc.py uses, and checks the patched bytes are byte-identical to
it, that nothing else in the image changed, and that the first word really is
`mov x19, x0`.  Finally it disassembles the region so the log shows the
instructions.

The stub (11 instructions, 44 bytes):
    mov  x19, x0 / mov x20, x1 / mov x21, x2 / mov x22, x3
    movz x0, #0x0009 / movk x0, #0x8400, lsl #16   -> 0x84000009
    smc  #0
    mov  x0, x19 / mov x1, x20 / mov x2, x21 / mov x3, x22
"""
import pathlib
import struct
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import patch_entry_smc as pes  # noqa: E402


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    a = src.read_bytes()
    b = dst.read_bytes()
    off = pes.entry_offset(a)
    tmp = pathlib.Path("/tmp/entryprobe_verify")
    tmp.mkdir(exist_ok=True)
    stub = pes.assemble(tmp)
    got = b[off:off + len(stub)]

    print("%s -> %s" % (src, dst))
    print("  size %d -> %d" % (len(a), len(b)))
    print("  stext offset 0x%x" % off)
    print("  expected stub %s (%d bytes)" % (stub.hex(), len(stub)))
    print("  patched  bytes %s" % got.hex())
    print("  stub matches   : %s" % (got == stub))
    print("  everything else identical: %s"
          % (a[:off] == b[:off] and a[off + len(stub):] == b[off + len(stub):]))
    words = struct.unpack("<%dI" % (len(stub) // 4), stub)
    print("  words: %s" % " ".join("%08x" % w for w in words))
    print("  first word %08x (mov x19,x0)" % words[0])

    # NOTE: no --adjust-vma here.  With -b binary objdump's addresses ARE file
    # offsets, so --start-address=off selects the stub only if the VMA is not
    # shifted; adding --adjust-vma=off makes objdump read file offset 0, which
    # misleadingly shows the Image header.
    r = subprocess.run(
        ["aarch64-linux-gnu-objdump", "-D", "-b", "binary", "-m", "aarch64",
         "--start-address=0x%x" % off,
         "--stop-address=0x%x" % (off + len(stub)), str(dst)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(r.stdout)

    if got != stub:
        raise SystemExit("FAIL: patched bytes are not the stub")
    if a[:off] != b[:off] or a[off + len(stub):] != b[off + len(stub):]:
        raise SystemExit("FAIL: bytes outside the stub changed")
    if words[0] != 0xaa0003f3:
        raise SystemExit("FAIL: first instruction is not mov x19, x0")
    print("OK")


if __name__ == "__main__":
    main()