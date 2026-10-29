#!/usr/bin/env python3
"""Dump the interesting parts of a vendor kernel module (.ko).

We need three things from a module built for the exact kernel on the device:

* ``sizeof(struct module)``   -> size of ``.gnu.linkonce.this_module``
* offset of the ``init`` field -> ``r_offset`` of the ``init_module`` reloc
* offset of the ``exit`` field -> ``r_offset`` of the ``cleanup_module`` reloc

Usage:
    python scripts/host/ko_info.py artifacts/incrementalfs.ko
"""

import struct
import sys

SHF_ALLOC = 0x2


def sections(data):
    e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
    e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
    raw = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name, typ, flags, addr, offset, size, link, info, align, entsize = \
            struct.unpack_from("<IIQQQQIIQQ", data, off)
        raw.append(dict(i=i, name_off=name, type=typ, flags=flags, addr=addr,
                        offset=offset, size=size, link=link, info=info,
                        align=align, entsize=entsize))
    strtab = raw[e_shstrndx]
    names = data[strtab["offset"]:strtab["offset"] + strtab["size"]]
    for s in raw:
        end = names.find(b"\0", s["name_off"])
        s["name"] = names[s["name_off"]:end].decode("latin1")
    return raw


def symtab(data, secs):
    for s in secs:
        if s["type"] != 2:  # SHT_SYMTAB
            continue
        strs = secs[s["link"]]
        strdata = data[strs["offset"]:strs["offset"] + strs["size"]]
        out = []
        for i in range(s["size"] // 24):
            off = s["offset"] + i * 24
            st_name, st_info, st_other, st_shndx, st_value, st_size = \
                struct.unpack_from("<IBBHQQ", data, off)
            end = strdata.find(b"\0", st_name)
            out.append(dict(name=strdata[st_name:end].decode("latin1"),
                            info=st_info, shndx=st_shndx, value=st_value,
                            size=st_size))
        return out
    return []


def main():
    data = open(sys.argv[1], "rb").read()
    secs = sections(data)
    syms = symtab(data, secs)
    by_name = {s["name"]: s for s in secs}

    print("%-34s %-6s %8s %8s %6s" % ("section", "flags", "off", "size", "align"))
    for s in secs:
        print("%-34s 0x%-4x %8x %8x %6d"
              % (s["name"], s["flags"], s["offset"], s["size"], s["align"]))

    info = data[by_name[".modinfo"]["offset"]:
                by_name[".modinfo"]["offset"] + by_name[".modinfo"]["size"]]
    print("\nmodinfo:")
    for line in info.decode("latin1").split("\0"):
        if line:
            print("  " + line)

    tm = by_name.get(".gnu.linkonce.this_module")
    if tm:
        print("\nthis_module: size=%d align=%d" % (tm["size"], tm["align"]))
        raw = data[tm["offset"]:tm["offset"] + tm["size"]]
        name = raw[24:24 + 64].split(b"\0")[0]
        print("  name@24 = %r" % name)
        for i in range(0, min(len(raw), 0x120), 8):
            val = struct.unpack_from("<Q", raw, i)[0]
            if val:
                print("  +0x%03x: 0x%016x" % (i, val))

    print("\nrelocations into .gnu.linkonce.this_module:")
    for s in secs:
        if s["type"] != 4:  # SHT_RELA
            continue
        target = secs[s["info"]]["name"]
        if target != ".gnu.linkonce.this_module":
            continue
        for i in range(s["size"] // 24):
            off = s["offset"] + i * 24
            r_off, r_info, r_add = struct.unpack_from("<QQq", data, off)
            sym = syms[r_info >> 32]
            print("  +0x%03x -> %-16s type=%d addend=%d"
                  % (r_off, sym["name"], r_info & 0xFFFFFFFF, r_add))

    print("\nundefined symbols:")
    for sym in syms:
        if sym["shndx"] == 0 and sym["name"]:
            print("  " + sym["name"])


if __name__ == "__main__":
    main()
