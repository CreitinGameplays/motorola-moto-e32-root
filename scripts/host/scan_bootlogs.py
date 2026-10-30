#!/usr/bin/env python3
"""Scan SPRD boot-log partitions for readable evidence.

Usage: python scan_bootlogs.py <file> [--tail N] [--head N]
Prints a header dump, the printable-string runs, and the last N of them.
"""

import argparse
import re
import sys

PRINTABLE = re.compile(rb"[\x20-\x7e\t]{5,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--tail", type=int, default=40)
    ap.add_argument("--head", type=int, default=12)
    ap.add_argument("--grep", action="append", default=[],
                    help="case-insensitive substring; only matching runs are shown")
    args = ap.parse_args()

    with open(args.path, "rb") as fh:
        data = fh.read()

    print("file  : %s (%d bytes, 0x%x)" % (args.path, len(data), len(data)))
    print("first 64 bytes: " + " ".join("%02x" % b for b in data[:64]))
    nonzero = sum(1 for b in data if b)
    print("nonzero bytes : %d (%.2f%%)" % (nonzero, 100.0 * nonzero / len(data)))

    hits = [(m.start(), m.group().decode("ascii", "replace")) for m in PRINTABLE.finditer(data)]
    print("string runs   : %d" % len(hits))

    if args.grep:
        pats = [p.lower() for p in args.grep]
        sel = [(o, t) for o, t in hits if any(p in t.lower() for p in pats)]
        print("--- grep matches: %d ---" % len(sel))
        for off, text in sel:
            print("0x%08x  %s" % (off, text[:200]))
        return 0

    print("--- first %d ---" % args.head)
    for off, text in hits[: args.head]:
        print("0x%08x  %s" % (off, text[:160]))

    print("--- last %d ---" % args.tail)
    for off, text in hits[-args.tail:]:
        print("0x%08x  %s" % (off, text[:160]))

    # Highest offset carrying data tells us how far the writer progressed.
    last = max((i for i, b in enumerate(data) if b), default=-1)
    print("highest nonzero offset: 0x%x" % last)
    return 0


if __name__ == "__main__":
    sys.exit(main())