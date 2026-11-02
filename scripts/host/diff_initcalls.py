#!/usr/bin/env python3
"""Diff the ordered initcall tables of two System.map files (LTO builds).

With CONFIG_LTO_CLANG every initcall table entry carries a linker symbol
named __initcall_<a>_<b>_<func><level> placed at the entry's own address,
so the address order of those symbols in a System.map is the boot-time
execution order of the initcalls.  This script extracts that order from
two maps and reports:

  * per-level entry counts,
  * entries present only in one build (with level),
  * the first order divergences between the common entries.

Usage:
    python3 scripts/host/diff_initcalls.py STOCK_MAP CUSTOM_MAP
"""
import re
import sys
from pathlib import Path

MAP_LINE = re.compile(r"^([0-9a-fA-F]+)\s+\S\s+(.*)$")
ENTRY = re.compile(r"^__initcall_[0-9A-Za-z]+_[0-9A-Za-z]+_(.+)$")
BOUNDARIES = (
    "__initcall_start", "__initcall0_start", "__initcall1_start",
    "__initcall2_start", "__initcall3_start", "__initcall4_start",
    "__initcall5_start", "__initcallrootfs_start", "__initcall6_start",
    "__initcall7_start", "__initcall_end",
)
LEVEL_NAMES = (
    "early", "pure", "core", "postcore", "arch", "subsys", "fs",
    "rootfs", "device", "late",
)


def read_map(path):
    syms = []
    for line in Path(path).read_text(errors="replace").splitlines():
        m = MAP_LINE.match(line)
        if not m:
            continue
        syms.append((int(m.group(1), 16), m.group(2).strip()))
    return syms


def extract(path):
    syms = read_map(path)
    bounds = {}
    for addr, name in syms:
        if name in BOUNDARIES and name not in bounds:
            bounds[name] = addr
    missing = [b for b in BOUNDARIES if b not in bounds]
    if missing:
        raise SystemExit("%s: missing boundary symbols: %s" %
                         (path, ", ".join(missing)))

    edges = [
        bounds["__initcall_start"], bounds["__initcall0_start"],
        bounds["__initcall1_start"], bounds["__initcall2_start"],
        bounds["__initcall3_start"], bounds["__initcall4_start"],
        bounds["__initcall5_start"], bounds["__initcallrootfs_start"],
        bounds["__initcall6_start"], bounds["__initcall7_start"],
        bounds["__initcall_end"],
    ]

    entries = []
    for addr, name in syms:
        m = ENTRY.match(name)
        if not m:
            continue
        if name in BOUNDARIES:
            continue
        func_level = m.group(1)
        level = None
        for suffix, tag in (("rootfs", "rootfs"), ("early", "early")):
            if func_level.endswith(suffix):
                level, func = tag, func_level[: -len(suffix)]
                break
        if level is None and func_level and func_level[-1] in "01234567":
            level = "L" + func_level[-1]
            func = func_level[:-1]
        if level is None:
            level, func = "?", func_level
        # level by address range is authoritative; the suffix is a fallback
        for i in range(len(edges) - 1):
            if edges[i] <= addr < edges[i + 1]:
                level = LEVEL_NAMES[i]
                break
        entries.append((addr, func, level, name))

    entries.sort(key=lambda e: e[0])
    return entries, bounds


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    stock, _ = extract(sys.argv[1])
    custom, _ = extract(sys.argv[2])

    print("stock  entries: %d" % len(stock))
    print("custom entries: %d" % len(custom))

    def by_level(entries):
        counts = {}
        for _, _, level, _ in entries:
            counts[level] = counts.get(level, 0) + 1
        return counts

    ls, lc = by_level(stock), by_level(custom)
    print("\nper-level counts (level: stock / custom):")
    for level in LEVEL_NAMES + ("?",):
        if ls.get(level) or lc.get(level):
            print("  %-12s %5d / %5d" % (level, ls.get(level, 0),
                                         lc.get(level, 0)))

    stock_keys = {}
    for addr, func, level, _ in stock:
        stock_keys.setdefault(func, []).append((addr, level))
    custom_keys = {}
    for addr, func, level, _ in custom:
        custom_keys.setdefault(func, []).append((addr, level))

    only_stock = sorted(set(stock_keys) - set(custom_keys))
    only_custom = sorted(set(custom_keys) - set(stock_keys))
    print("\ninitcalls only in STOCK (%d):" % len(only_stock))
    for func in only_stock:
        for addr, level in stock_keys[func]:
            print("  - %-12s %#x %s" % (level, addr, func))
    print("\ninitcalls only in CUSTOM (%d):" % len(only_custom))
    for func in only_custom:
        for addr, level in custom_keys[func]:
            print("  + %-12s %#x %s" % (level, addr, func))

    # order divergence among the common entries, in execution order
    common_stock = [f for _, f, _, _ in stock if f in custom_keys]
    common_custom = [f for _, f, _, _ in custom if f in stock_keys]
    if common_stock == common_custom:
        print("\ncommon-entry order: IDENTICAL")
    else:
        # longest common subsequence to find the first real divergence
        n, mlen = len(common_stock), len(common_custom)
        lcs = [[0] * (mlen + 1) for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            for j in range(mlen - 1, -1, -1):
                lcs[i][j] = (lcs[i + 1][j + 1] + 1
                             if common_stock[i] == common_custom[j]
                             else max(lcs[i + 1][j], lcs[i][j + 1]))
        i = j = 0
        shown = 0
        print("\nfirst order divergences (stock order vs custom order):")
        while i < n and j < mlen and shown < 25:
            if common_stock[i] == common_custom[j]:
                i, j = i + 1, j + 1
                continue
            print("  stock[%d]=%s   vs   custom[%d]=%s" %
                  (i, common_stock[i], j, common_custom[j]))
            shown += 1
            # advance on the side whose next symbol re-syncs sooner
            if common_stock[i] in common_custom[j:j + 40]:
                j += 1
            else:
                i += 1
        if shown == 0:
            print("  (only length differs)")
        print("  lcs=%d of stock=%d custom=%d" %
              (lcs[0][0], n, mlen))


if __name__ == "__main__":
    main()
