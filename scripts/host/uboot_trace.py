#!/usr/bin/env python3
"""Annotate a code range of a U-Boot image with resolved string references.

The image is linked for a load base whose low 12 bits are 0xe00, so a raw
``adrp page + add imm`` resolves to the string's *virtual* address while the
file offset differs by a page-dependent constant.  Empirically the mapping is
``file_off = target + 0x200`` for instructions whose low 12 bits are >= 0x200
and ``file_off = target - 0xe00`` for instructions in the first 0x200 bytes of
a page.  This script applies that correction and prints, in address order, every
resolved reference next to the string it points at.  Reading the messages in
order is enough to reconstruct the unlock/lock checks.

Usage:
    python scripts/host/uboot_trace.py 0x29be4 0x2a100
"""

import pathlib
import sys

import capstone

IMAGE = pathlib.Path("artifacts/bootloader/bl/uboot_a.img")


def cstr(data, off, maxlen=100):
    if off < 0 or off >= len(data):
        return "<out of image>"
    end = off
    while end < len(data) and end - off < maxlen and data[end] not in (0,):
        ch = data[end]
        if not (32 <= ch < 127 or ch in (9, 10, 13)):
            break
        end += 1
    return data[off:end].decode("ascii", "replace")


def main():
    lo = int(sys.argv[1], 0)
    hi = int(sys.argv[2], 0)
    data = IMAGE.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    md.skipdata = True

    pages = {}
    for ins in md.disasm(data[lo:hi], lo):
        if ins.mnemonic == ".byte":
            continue
        try:
            ops = ins.operands
        except capstone.CsError:
            continue

        if ins.mnemonic == "adrp" and len(ops) == 2 and ops[0].type == capstone.arm64.ARM64_OP_REG:
            pages[ops[0].reg] = ops[1].imm
            print("%06x  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))
            continue

        if ins.mnemonic == "add" and len(ops) == 3:
            dst, src, imm = ops
            if (src.type == capstone.arm64.ARM64_OP_REG
                    and imm.type == capstone.arm64.ARM64_OP_IMM
                    and src.reg in pages):
                tgt = pages[src.reg] + imm.imm
                corr = 0x200 if (ins.address & 0xFFF) >= 0x200 else -0xE00
                fo = tgt + corr
                if 0xB0000 <= fo < 0xF0000:
                    s = cstr(data, fo)
                    if s and any(32 <= ord(ch) < 127 for ch in s):
                        print("%06x  %-8s %-24s ; -> %06x %r"
                              % (ins.address, ins.mnemonic, ins.op_str, fo, s))
                        if dst.type == capstone.arm64.ARM64_OP_REG:
                            pages.pop(dst.reg, None)
                        continue
            if dst.type == capstone.arm64.ARM64_OP_REG:
                pages.pop(dst.reg, None)
            print("%06x  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))
            continue

        for op in ops:
            if (op.type == capstone.arm64.ARM64_OP_REG
                    and op.access & capstone.CS_AC_WRITE):
                pages.pop(op.reg, None)
        print("%06x  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
