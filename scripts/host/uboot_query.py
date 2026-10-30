"""Query the U-Boot disassembly: windows, callers, strings.

Usage:
  python uboot_query.py win 0x7b7c
  python uboot_query.py callers 0x7b7c [0x7c60 ...]
  python uboot_query.py strings 0xc2e83 0xba322
  python uboot_query.py grep bootonce
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIS = ROOT / "artifacts" / "bootloader" / "uboot_disasm.txt"
IMG = ROOT / "artifacts" / "bootloader" / "bl" / "uboot_b.img"

LINE = re.compile(r"^([0-9a-f]{6})  (\S+)\s*(.*)$")


def read_dis():
    return DIS.read_text(encoding="utf-16", errors="replace")


def load():
    m = {}
    for line in read_dis().splitlines():
        g = LINE.match(line)
        if g:
            m[int(g.group(1), 16)] = (g.group(2), g.group(3).strip())
    return m


def main():
    m = load()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "win":
        a = int(sys.argv[2], 16)
        n = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x50
        print("=== window 0x%06x..0x%06x ===" % (a, a + n))
        for k in range(a, a + n, 4):
            if k in m:
                ins, ops = m[k]
                print("%06x  %-8s %s" % (k, ins, ops))

    elif cmd == "callers":
        want = {int(x, 16) for x in sys.argv[2:]}
        for addr, (ins, ops) in sorted(m.items()):
            if ins in ("bl", "b", "br", "blr"):
                g = re.search(r"#(0x[0-9a-f]+)", ops)
                if g and int(g.group(1), 16) in want:
                    print("%06x  %-8s %s" % (addr, ins, ops))

    elif cmd == "strings":
        d = IMG.read_bytes()
        for x in sys.argv[2:]:
            off = int(x, 16)
            s = d[off:off + 120].split(b"\0")[0]
            print("%06x  %r" % (off, s.decode("latin-1")))

    elif cmd == "grep":
        d = IMG.read_bytes()
        pat = sys.argv[2].encode()
        i = 0
        seen = set()
        while True:
            j = d.find(pat, i)
            if j < 0:
                break
            s = d[max(0, j - 60):j + 120].split(b"\0")
            for part in s:
                if pat in part and part not in seen and len(part) > 3:
                    seen.add(part)
                    print("%06x  %r" % (j, part.decode("latin-1")))
            i = j + 1
    else:
        print(__doc__)


main()