#!/usr/bin/env python3
"""Compare the vendor modules' expected CRCs against a built kernel's Module.symvers.

Usage: compare_vendor_crcs.py /tmp/kbuild/Module.symvers vendor_crcs.tsv

vendor_crcs.tsv lines: symbol<TAB>0xCRC<TAB>modele[,module...]
Module.symvers lines: 0xCRC<TAB>symbol<TAB>module<TAB>export
"""
import sys

symvers_path, vendor_path = sys.argv[1], sys.argv[2]

kern = {}
for line in open(symvers_path):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 2:
        continue
    try:
        crc = int(parts[0], 0)
    except ValueError:
        continue
    name = parts[1]
    exported_by = parts[2] if len(parts) > 2 else ""
    kern[name] = (crc, exported_by)

ok = bad = missing = 0
bad_list, missing_list = [], []
for line in open(vendor_path):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        continue
    name, crc, mods = parts[0], int(parts[1], 0), parts[2]
    if name not in kern:
        missing += 1
        missing_list.append((name, mods))
        continue
    if kern[name][0] == crc:
        ok += 1
    else:
        bad += 1
        bad_list.append((name, crc, kern[name][0], mods))

print("== vendor symbols: matched %d, mismatched %d, missing %d" % (ok, bad, missing))
if bad_list:
    print("\n-- CRC mismatches (vendor vs kernel):")
    for name, v, k, mods in bad_list:
        print("  %-34s vendor 0x%08x kernel 0x%08x  [%s]" % (name, v, k, mods))
if missing_list:
    print("\n-- not exported by the kernel build (need checking):")
    for name, mods in missing_list:
        print("  %-34s [%s]" % (name, mods))
