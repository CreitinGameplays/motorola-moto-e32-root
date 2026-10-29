#!/usr/bin/env python3
"""Find ``adrp``/``add`` references to given virtual addresses in TrustOS.

The Spreadtrum TrustOS image (``trustos_a``) is a ``DHTB`` container whose
payload starts at file offset 0x200.  The payload is position independent; the
analysis below reports addresses relative to the payload start (the image is
linked at 0), which is enough to locate handlers and jump tables.

Usage:
    python scripts/host/trustos_xref.py 0x83200 0x83260 0x833c0

Each hit prints the instruction address and the target it resolves to, so a
string or table can be traced back to the code that uses it.
"""

import sys

import capstone

IMAGE = "artifacts/bootloader/bl/trustos_a.img"
PAYLOAD_OFF = 0x200


def main():
    targets = {}
    for arg in sys.argv[1:]:
        value = int(arg, 0)
        targets[value] = arg

    data = open(IMAGE, "rb").read()
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True

    adrp = {}
    hits = []
    for ins in md.disasm(data[PAYLOAD_OFF:], 0):
        if ins.mnemonic == "adrp":
            adrp[ins.operands[0].reg] = ins.operands[1].imm
        elif ins.mnemonic in ("add", "ldr", "str") and len(ins.operands) >= 3:
            mem = ins.operands[1] if ins.mnemonic != "add" else None
            try:
                base = ins.operands[1].reg
                imm = ins.operands[2].imm
            except (IndexError, AttributeError):
                continue
            if base in adrp:
                target = adrp[base] + imm
                if target in targets:
                    hits.append((ins.address, target))

    for addr, target in hits:
        print("0x%06x -> 0x%06x (%s)" % (addr, target, targets[target]))


if __name__ == "__main__":
    main()
