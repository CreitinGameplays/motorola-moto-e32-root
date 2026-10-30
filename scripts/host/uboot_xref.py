#!/usr/bin/env python3
"""Cross-reference the U-Boot fastboot string pool.

``uboot_b.img`` starts with a 0x200-byte ``DHTB`` header, so the image is
mapped with

    runtime VA  = 0x9f000000 + file_offset - 0x200

The disassembly below runs with base 0 on the raw file, i.e. instruction
addresses *are* file offsets, and ``adrp page + add imm`` yields
``runtime VA - 0x9f000000``: the referenced C string therefore sits at
``target + 0x200`` in the file.  (An earlier version of this script used the
target as a file offset and was off by 0x200 for every string.)

This tracks ``adrp`` per register and resolves ``add reg, reg, #imm`` pairs,
then prints every reference whose target falls inside the string pool
(0xb0000-0xe0000).  The C string at the target is printed next to the xref.

This is how we locate the fastboot command handlers: the dispatch table loads
the command name string ("unlock", "unlock_bootloader", ...) and the handler
body loads its diagnostic strings, both of which show up here.

Usage:
    python scripts/host/uboot_xref.py [image]
"""

import pathlib
import sys

import capstone

DEFAULT = pathlib.Path("artifacts/bootloader/bl/uboot_a.img")
POOL_LO = 0xB0000
POOL_HI = 0xE0000
STRING_BIAS = 0x200  # DHTB header at the front of the image


def cstr(data, off, maxlen=72):
    if off < 0 or off >= len(data):
        return ""
    end = off
    while end < len(data) and end - off < maxlen and 32 <= data[end] < 127:
        end += 1
    return data[off:end].decode("ascii", "replace")


def main():
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    data = path.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    pages = {}  # reg -> page base from adrp
    hits = []

    for ins in md.disasm(data[0x200:], 0x200):
        m = ins.mnemonic
        if m == ".byte":  # SKIPDATA pseudo-instruction, operands unavailable
            continue
        try:
            ops = ins.operands
        except capstone.CsError:
            continue

        if m == "adrp" and len(ops) == 2 and ops[0].type == capstone.arm64.ARM64_OP_REG:
            try:
                pages[ops[0].reg] = ops[1].imm
            except Exception:
                pass
            continue

        if m == "add" and len(ops) == 3:
            dst, src, imm = ops
            if (src.type == capstone.arm64.ARM64_OP_REG
                    and imm.type == capstone.arm64.ARM64_OP_IMM
                    and src.reg in pages):
                tgt = pages[src.reg] + imm.imm
                if POOL_LO <= tgt < POOL_HI:
                    hits.append((ins.address, tgt, cstr(data, tgt + STRING_BIAS)))
            # add writes dst, invalidate stale page tracking
            if dst.type == capstone.arm64.ARM64_OP_REG:
                pages.pop(dst.reg, None)
            continue

        # Any other instruction that writes a register invalidates its page.
        for op in ops:
            if (op.type == capstone.arm64.ARM64_OP_REG
                    and op.access & capstone.CS_AC_WRITE):
                pages.pop(op.reg, None)

    hits.sort(key=lambda h: h[1])
    print("%d xrefs into the string pool" % len(hits))
    last = None
    for addr, tgt, s in hits:
        if tgt != last:
            print("\nVA 0x%08x (file 0x%06x)  %r"
                  % (0x9F000000 + tgt, tgt + STRING_BIAS, s))
            last = tgt
        print("   <- file 0x%06x (VA 0x%08x)" % (addr, addr - 0x200 + 0x9F000000))


if __name__ == "__main__":
    main()
