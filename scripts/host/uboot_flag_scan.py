#!/usr/bin/env python3
"""Find every access to a set of absolute addresses in the U-Boot blob.

Used to prove claims like "only two instructions in the whole bootloader ever
write the flash-gate flag".  The image carries a 0x200-byte ``DHTB`` header, so
instructions are disassembled with base 0 on the raw file (addresses are file
offsets) and ``adrp page + add imm`` yields ``runtime VA - 0x9f000000``.

Usage:
    python scripts/host/uboot_flag_scan.py [--image IMG] [--page 0x70a000] ...

Default pages: 0x70a000 (fastboot licence flag), 0x70b000 (twin flag) and
0x70e000 (secure-world SIP mailbox).
"""

import argparse
import pathlib

import capstone
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG

DEFAULT_IMAGE = pathlib.Path("artifacts/bootloader/bl/uboot_b.img")
CODE_LO, CODE_HI = 0x1000, 0xA1000
WIN = 0x40  # bytes of a page considered interesting


def scan(data, pages):
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True

    vals = {}
    hits = []
    off = CODE_LO
    while off < CODE_HI:
        try:
            ins = next(md.disasm(data[off:off + 4], off))
        except StopIteration:
            vals.clear()
            off += 4
            continue
        off += 4
        ops = ins.operands
        m = ins.mnemonic

        if m == "adrp" and len(ops) == 2 and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_IMM:
            vals[ins.reg_name(ops[0].reg)] = ops[1].imm
            continue

        if m == "add" and len(ops) == 3 and ops[1].type == ARM64_OP_REG and ops[2].type == ARM64_OP_IMM:
            dst, src = ins.reg_name(ops[0].reg), ins.reg_name(ops[1].reg)
            if src in vals:
                vals[dst] = vals[src] + ops[2].imm
                continue

        mem = next((o for o in ops if o.type == ARM64_OP_MEM and hasattr(o, "mem")), None)
        if mem is not None and getattr(mem.mem, "base", 0):
            base = ins.reg_name(mem.mem.base)
            if base in vals:
                tgt = vals[base] + mem.mem.disp
                for page in pages:
                    if page <= tgt < page + WIN:
                        hits.append((ins.address, m, tgt, ins.op_str))

        for op in ops:
            if op.type == ARM64_OP_REG and op.access & capstone.CS_AC_WRITE:
                vals.pop(ins.reg_name(op.reg), None)

    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=pathlib.Path, default=DEFAULT_IMAGE)
    ap.add_argument("--page", action="append", type=lambda s: int(s, 0))
    args = ap.parse_args()

    pages = args.page or [0x70A000, 0x70B000, 0x70E000]
    data = args.image.read_bytes()

    hits = scan(data, pages)
    print("%d accesses into %s" % (len(hits), ", ".join("0x%x" % p for p in pages)))
    for file_off, m, tgt, opstr in hits:
        store = "STORE" if m.startswith("str") else "load "
        print("  %s  file 0x%06x  VA 0x%08x  %-7s %-12s -> 0x%08x  %s"
              % (store, file_off, file_off - 0x200 + 0x9F000000, m, "",
                 0x9F000000 + tgt, opstr))


if __name__ == "__main__":
    main()