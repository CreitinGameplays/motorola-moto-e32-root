#!/usr/bin/env python3
"""Compare the live device tree of the running kernel with the public DTS.

Inputs
------
--dt     directory tree dumped from /proc/device-tree (scripts/device/dump_device_tree.sh)
--dts    one or more .dts/.dtsi files from the kernel tree
--out    optional markdown report

The live tree is the flattened DTB exported by the kernel as a directory
tree; every property is a file with the raw (big endian) value.  Strings are
NUL separated.

What it shows
-------------
Whether the board files in the public kernel tree are the ones that produced
the device tree the phone is actually running (node paths + "compatible"
strings).
"""
import argparse
import os
import re
import sys

COMPAT_RE = re.compile(r'(?:compatible|model)\s*=\s*((?:"[^"]*"\s*,?\s*)+);')
STR_RE = re.compile(r'"([^"]*)"')


def live_strings(dt_dir):
    """{node path: set(property names)}, {compatible string: node}."""
    compat = {}
    nodes = set()
    props = {}
    for dirpath, dirnames, filenames in os.walk(dt_dir):
        rel = os.path.relpath(dirpath, dt_dir).replace("\\", "/")
        node = "" if rel == "." else rel
        nodes.add(node)
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            with open(path, "rb") as f:
                data = f.read()
            props.setdefault(node, []).append(fn)
            if fn in ("compatible", "model"):
                for s in data.split(b"\x00"):
                    s = s.decode("utf-8", "replace").strip()
                    if s:
                        compat.setdefault(s, node)
    return nodes, props, compat


def dts_strings(paths):
    compat = {}
    for p in paths:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
        for m in COMPAT_RE.finditer(txt):
            for s in STR_RE.findall(m.group(1)):
                if s:
                    compat.setdefault(s, os.path.basename(p))
    return compat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dt", required=True)
    ap.add_argument("--dts", action="append", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()

    nodes, props, live = live_strings(args.dt)
    tree = dts_strings(args.dts)

    report = []
    report.append("# Live device tree vs public DTS\n")
    report.append(f"- live nodes: {len(nodes)}")
    report.append(f"- live property files: {sum(len(v) for v in props.values())}")
    report.append(f"- live 'compatible'/'model' strings: {len(live)}")
    report.append(f"- strings found in the public DTS: {len(tree)}")

    only_live = sorted(s for s in live if s not in tree)
    only_tree = sorted(s for s in tree if s not in live)
    matched = sorted(s for s in live if s in tree)
    report.append(f"- strings present in both: {len(matched)}")
    report.append(f"- only in the live tree: {len(only_live)}")
    for s in only_live:
        report.append(f"  - `{s}`  (node `{live[s]}`)")
    report.append(f"- only in the public DTS: {len(only_tree)}")
    for s in only_tree:
        report.append(f"  - `{s}`  ({tree[s]})")

    text = "\n".join(report) + "\n"
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[+] report written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
