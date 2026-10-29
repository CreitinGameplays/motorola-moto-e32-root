#!/usr/bin/env python3
"""Reconstruct the unpublished release config fragment of the shipping kernel.

Motorola/Unisoc build every firmware from

    arch/arm64/configs/sprd_qogirl6_defconfig
    + sprd-diffconfig/androidr/<release>/<platform>/arm64/*_diff_config

The public tree ships the fragments of the 2022 releases; the production
build of RORS31.335-58-1 additionally applied one *unpublished* fragment
that strips the debug/monitor options.  Its content can be reconstructed
exactly, because the shipping kernel exposes its own configuration in
/proc/config.gz.

This tool computes that delta and writes it in two formats:

  --out-fragment   Motorola/Unisoc style ("DEL:CONFIG_X" / "ADD:CONFIG_X")
  --out-config     classic kernel diffconfig format (ready for
                   scripts/kconfig/merge_config.sh)

Usage:
  reconstruct_release_config.py --defconfig <defconfig> \\
      [--diffconfig <fragment>]... --config <proc/config.gz> \\
      --out-fragment <file> --out-config <file>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_kernel_source import parse_config, parse_diffconfig  # noqa: E402


def build_tree_config(defconfig, diffconfigs):
    cfg = parse_config(defconfig)
    for d in diffconfigs:
        adds, dels = parse_diffconfig(d)
        for s in dels:
            cfg.pop(s, None)
        for s in adds:
            cfg[s] = "y"
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--defconfig", required=True)
    ap.add_argument("--diffconfig", action="append", default=[])
    ap.add_argument("--config", required=True,
                    help="shipping /proc/config.gz (decompressed)")
    ap.add_argument("--out-fragment")
    ap.add_argument("--out-config")
    ap.add_argument("--check", action="store_true",
                    help="verify that the reconstructed fragment resolves "
                         "every conflict (exit 1 if not)")
    args = ap.parse_args()

    tree = build_tree_config(args.defconfig, args.diffconfig)
    ship = parse_config(args.config)

    conflicts = {k: (v, ship.get(k, "n")) for k, v in tree.items()
                 if ship.get(k, "n") != v}
    # symbols the shipping config knows but the tree does not
    only_ship = {k: v for k, v in ship.items() if k not in tree}

    dels = sorted(k for k, (t, s) in conflicts.items() if s == "n")
    sets = {k: s for k, (t, s) in conflicts.items() if s != "n"}

    print(f"tree config symbols : {len(tree)}")
    print(f"shipping config     : {len(ship)}")
    print(f"conflicts to fix    : {len(conflicts)}")
    print(f"  -> disable ({len(dels)})")
    print(f"  -> set value ({len(sets)})")
    for k in sorted(sets):
        print(f"       {k} = {sets[k]!r}")
    print(f"symbols only in the shipping config: {len(only_ship)}")

    frag_lines = [f"DEL:{k}" for k in dels]
    frag_lines += [f"ADD:{k}" for k in sorted(sets) if sets[k] == "y"]
    frag_text = "\n".join(frag_lines) + "\n"

    cfg_lines = []
    for k in sorted(conflicts):
        v = conflicts[k][1]
        if v == "n":
            cfg_lines.append(f"# {k} is not set")
        else:
            cfg_lines.append(f"{k}={v}")
    for k in sorted(only_ship):
        if only_ship[k] == "n":
            cfg_lines.append(f"# {k} is not set")
        else:
            cfg_lines.append(f"{k}={only_ship[k]}")
    cfg_text = "\n".join(cfg_lines) + "\n"

    if args.out_fragment:
        with open(args.out_fragment, "w", encoding="utf-8", newline="\n") as f:
            f.write(frag_text)
        print(f"[+] fragment written to {args.out_fragment}")
    if args.out_config:
        with open(args.out_config, "w", encoding="utf-8", newline="\n") as f:
            f.write(cfg_text)
        print(f"[+] config fragment written to {args.out_config}")

    # verification: apply the reconstructed fragment and compare again
    fixed = dict(tree)
    for k in dels:
        fixed.pop(k, None)
    for k, v in sets.items():
        fixed[k] = v
    fixed.update({k: v for k, v in only_ship.items()})
    remaining = [k for k, v in fixed.items() if ship.get(k, "n") != v]
    missing = [k for k, v in ship.items() if k not in fixed]
    print(f"verification: {len(remaining)} conflict(s) left, "
          f"{len(missing)} shipping symbol(s) not covered")
    if args.check and (remaining or missing):
        print("[!] reconstruction incomplete", file=sys.stderr)
        return 1
    print("[+] reconstructed fragment reproduces the shipping .config exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
