#!/usr/bin/env python3
"""Disassemble a U-Boot image to text for grepping.

Output lines are ``<file offset>  <mnemonic> <operands>`` so that ``grep`` on
an immediate or a branch target works directly.  Kept in scripts/host because
the bootloader strings/handlers are the main evidence for the unlock analysis.

Usage:
    python scripts/host/uboot_disasm.py artifacts/bootloader/bl/uboot_a.img > out.txt
"""

import pathlib
import sys

import capstone


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                        "artifacts/bootloader/bl/uboot_a.img")
    data = path.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = False
    md.skipdata = True
    out = sys.stdout
    for ins in md.disasm(data[0x200:], 0x200):
        if ins.mnemonic == ".byte":
            continue
        out.write("%06x  %-8s %s\n" % (ins.address, ins.mnemonic, ins.op_str))


if __name__ == "__main__":
    main()
