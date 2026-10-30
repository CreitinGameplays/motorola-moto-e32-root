#!/usr/bin/env python3
"""Compare a freshly built System.map against the phone's shipped one.

The shipping `System.map` (artifacts/System.map, 119,878 symbols) is the
ground truth for "did we rebuild the same kernel".  Addresses will not match
unless the link order, toolchain and config are identical, so the useful
signal is the *set* of symbols:

  * symbols present in the shipped kernel but not in ours  -> code we are
    missing (unpublished vendor patches, or config we did not reproduce)
  * symbols present in ours but not in the shipped kernel  -> config we added
    (this build enables KVM/vhost/vsock on purpose) or code the vendor did not
    compile

Usage:
    compare_symbols.py --shipped artifacts/System.map --built /path/System.map
    compare_symbols.py --shipped ... --built ... --md out.md

Exit code is 0 whenever both files parse; the comparison is informational.
"""
import argparse
import collections
import re
import sys

LINE = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.*)$")

# Symbols that differ by design between any two builds.
IGNORE_PREFIXES = (
    "__crc_",        # modversions CRCs depend on the compiler's type hashing
    "__ksymtab_",    # generated
    "__kstrtab",
    "$",
    ".",             # assembler-local: .L*, .compoundliteral.*, .str.*, ...
)

# Compiler-cloned/partial functions change suffix between builds.
SUFFIX = re.compile(r"\.(isra|constprop|part|cold|llvm)\.\d+$")


def parse(path):
    """Return {name: type} plus a list of (addr, type, name)."""
    out = {}
    dups = collections.Counter()
    for line in open(path, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m:
            continue
        addr, typ, name = m.groups()
        if any(name.startswith(p) for p in IGNORE_PREFIXES):
            continue
        name = SUFFIX.sub("", name)
        if name in out:
            dups[name] += 1
            continue
        out[name] = typ
    return out, dups


def group(names, types):
    by = collections.Counter(types[n] for n in names)
    return ", ".join(f"{t}:{c}" for t, c in sorted(by.items(), key=lambda kv: -kv[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shipped", required=True)
    ap.add_argument("--built", required=True)
    ap.add_argument("--md", default=None, help="also write a markdown report here")
    ap.add_argument("--top", type=int, default=40,
                    help="how many example symbols to list per direction")
    ap.add_argument("--retyped", action="store_true",
                    help="also list common symbols whose type letter differs "
                         "(mostly rodata-vs-data placement noise)")
    args = ap.parse_args()

    ship, ship_dup = parse(args.shipped)
    ours, ours_dup = parse(args.built)

    missing = sorted(set(ship) - set(ours))
    extra = sorted(set(ours) - set(ship))
    common = set(ship) & set(ours)

    lines = []
    w = lines.append
    w("# Built kernel vs shipped `System.map`\n")
    w(f"shipped: `{args.shipped}` - {len(ship):,} symbols")
    w(f"built:   `{args.built}` - {len(ours):,} symbols\n")
    w("| | count |")
    w("|---|---|")
    w(f"| common | {len(common):,} |")
    w(f"| only in shipped | {len(missing):,} |")
    w(f"| only in built | {len(extra):,} |")
    if ship_dup:
        w(f"| duplicate names in shipped | {len(ship_dup)} |")
    if ours_dup:
        w(f"| duplicate names in built | {len(ours_dup)} |")
    w("")

    if missing:
        w(f"## Only in the shipped kernel ({len(missing):,})\n")
        w(f"by type: {group(missing, ship)}\n")
        w("```")
        for n in missing[:args.top]:
            w(f"{ship[n]} {n}")
        if len(missing) > args.top:
            w(f"... {len(missing) - args.top:,} more")
        w("```\n")

    if extra:
        w(f"## Only in the built kernel ({len(extra):,})\n")
        w(f"by type: {group(extra, ours)}\n")
        w("```")
        for n in extra[:args.top]:
            w(f"{ours[n]} {n}")
        if len(extra) > args.top:
            w(f"... {len(extra) - args.top:,} more")
        w("```\n")

    # A symbol that changed linkage (t vs T, d vs D) is a real difference too.
    # rodata vs data placement differs with the compiler version, so it is
    # only reported on request.
    retyped = [(n, ship[n], ours[n]) for n in common if ship[n] != ours[n]]
    if retyped and args.retyped:
        w(f"## Same name, different type ({len(retyped):,})\n")
        w("```")
        for n, a, b in sorted(retyped)[:args.top]:
            w(f"{n}: shipped {a}, built {b}")
        if len(retyped) > args.top:
            w(f"... {len(retyped) - args.top:,} more")
        w("```\n")

    text = "\n".join(lines)
    print(text)
    if args.md:
        with open(args.md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"written: {args.md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
