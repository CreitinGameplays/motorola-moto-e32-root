#!/usr/bin/env python3
"""Check that Clang CFI jump tables land inside accepted kernel text.

Usage:
    python3 scripts/host/check_cfi_notifier_layout.py Image System.map

The shipping config enables CONFIG_DEBUG_NOTIFIERS.  Its function-pointer
check accepts core text [_stext, _etext), and accepts init text only before
SYSTEM_RUNNING.  A notifier's CFI jump-table entry outside those bounds is
therefore rejected even if the real callback body is in .text.
"""
import argparse
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path


MAP_LINE = re.compile(r"^([0-9a-fA-F]+)\s+\S\s+(.*)$")
R_AARCH64_RELATIVE = 1027


def read_map(path):
    symbols = defaultdict(list)
    by_address = defaultdict(list)
    for line in Path(path).read_text(errors="replace").splitlines():
        match = MAP_LINE.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        name = match.group(2)
        symbols[name].append(address)
        by_address[address].append(name)
    return symbols, by_address


def one(symbols, name):
    values = symbols.get(name)
    if not values:
        raise ValueError("System.map is missing required symbol " + name)
    return values[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="raw arm64 Image")
    parser.add_argument("system_map", help="matching System.map")
    args = parser.parse_args()

    image = Path(args.image).read_bytes()
    symbols, by_address = read_map(args.system_map)
    text_start = one(symbols, "_stext")
    text_end = one(symbols, "_etext")
    text_base = one(symbols, "_text")
    text_offset = struct.unpack_from("<Q", image, 8)[0]

    jump_tables_by_address = defaultdict(list)
    for name, addresses in symbols.items():
        if name.endswith(".cfi_jt"):
            jump_tables_by_address[addresses[0]].append(name)
    jump_tables = sorted((address, name)
                         for address, names in jump_tables_by_address.items()
                         for name in names)
    outside = [(address, name) for address, name in jump_tables
               if not text_start <= address < text_end]

    print("Image:", args.image, "bytes=", len(image))
    print("core text: %#x..%#x; CFI jump-table symbols: %d" %
          (text_start, text_end, len(jump_tables)))
    print("CFI jump tables outside core text:", len(outside))
    for address, name in outside[:30]:
        print("  OUTSIDE %#x %s" % (address, name))

    # __rela_offset is relative to KIMAGE_VADDR, while the raw Image starts at
    # _text = KIMAGE_VADDR + text_offset.
    if "__rela_offset" in symbols and "__rela_size" in symbols:
        rela_offset = one(symbols, "__rela_offset") - text_offset
        rela_size = one(symbols, "__rela_size")
        if rela_offset < 0 or rela_offset + rela_size > len(image):
            raise ValueError("relocation table lies outside Image")
        if rela_size % 24:
            raise ValueError("relocation table size is not a multiple of 24")

        table_targets = defaultdict(list)
        relative_count = 0
        for offset in range(rela_offset, rela_offset + rela_size, 24):
            target, info, addend = struct.unpack_from("<QQq", image, offset)
            if info & 0xffffffff != R_AARCH64_RELATIVE:
                continue
            relative_count += 1
            table_targets[addend & 0xffffffffffffffff].append(target)

        notifier_relocations = []
        for callback, targets in table_targets.items():
            callback_names = jump_tables_by_address.get(callback)
            if not callback_names:
                continue
            for target in targets:
                owners = by_address.get(target, [])
                notifier_owners = [name for name in owners
                                   if ("notifier_block" in name.lower()
                                       or "cpu_pm" in name.lower()
                                       or name.lower().endswith("_nb"))
                                   and not name.startswith("__ksymtab_")]
                if notifier_owners:
                    notifier_relocations.append(
                        (target, callback, notifier_owners, callback_names))

        print("R_AARCH64_RELATIVE entries:", relative_count)
        print("notifier-like data relocations to CFI jump tables:",
              len(notifier_relocations))
        for target, callback, owners, callback_names in sorted(notifier_relocations):
            print("  %#x %-48s -> %#x %s" %
                  (target, ",".join(owners), callback,
                   ",".join(callback_names)))
    else:
        print("relocation audit: skipped (__rela_offset/__rela_size absent from map)")

    if outside:
        return 1
    if text_start < text_base or text_end <= text_start:
        raise ValueError("invalid _text/_stext/_etext ordering")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, struct.error, ValueError) as exc:
        print("error:", exc, file=sys.stderr)
        sys.exit(2)
