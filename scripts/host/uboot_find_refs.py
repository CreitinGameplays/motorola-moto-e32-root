"""Find code that references a target file offset, tolerating:
 - adrp/add pairs separated by a few instructions
 - adrp printed as either a file offset or a full runtime VA (0x9f0xxxxx)
"""
import pathlib
import re
import sys

DIS = pathlib.Path(__file__).resolve().parents[2] / "artifacts" / "bootloader" / "uboot_disasm.txt"
LINE = re.compile(r"^([0-9a-f]{6})  (\S+)\s*(.*)$")
BASE = 0x9EFFFE00


def norm(p):
    """Candidate target -> file offset."""
    if 0x9E000000 <= p < 0x9F400000:
        return p - BASE + 0x200
    return p


def main():
    targets = {int(x, 16) for x in sys.argv[1:]}
    recent = {}  # reg -> (addr, page)
    hits = 0
    for line in DIS.read_text(encoding="utf-16", errors="replace").splitlines():
        g = LINE.match(line)
        if not g:
            continue
        addr = int(g.group(1), 16)
        ins = g.group(2)
        ops = g.group(3).strip()
        if ins == "adrp":
            m = re.match(r"x(\d+), #(-?0x[0-9a-f]+)", ops)
            if m:
                recent[int(m.group(1))] = (addr, norm(int(m.group(2), 16)))
        elif ins == "add":
            m = re.match(r"x(\d+), x(\d+), #(0x[0-9a-f]+)", ops)
            if m and int(m.group(1)) == int(m.group(2)) and int(m.group(1)) in recent:
                a, page = recent[int(m.group(1))]
                tgt = page + int(m.group(3), 16)
                if any(abs(tgt - t) <= 4 for t in targets):
                    print("%06x  adrp(0x%06x)+add -> 0x%06x" % (a, page, tgt))
                    hits += 1
        elif ins in ("b", "bl", "b.eq", "b.ne", "cbz", "cbnz", "mov", "movz", "movk", "str", "ldr"):
            pass
    if not hits:
        print("no references found")


main()