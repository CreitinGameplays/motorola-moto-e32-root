#!/usr/bin/env python3
"""dtb_surgery.py - inspect and patch Flattened Device Tree blobs (DTB).

Why: the 7.x bring-up flashes a *vendor* DTB with surgical edits (the LK
bootloader merges dtbo overlays onto the image DTB, so the vendor base
must be kept and edited, not replaced by a fork dtsi build).  A
decompile -> edit -> recompile round trip renumbers phandles and
re-emits the whole blob; this tool rewrites only what an operation
touches and keeps every other byte of the structure intact.

Pure Python 3, standard library only - runs on the Windows host or the
build VPS.  Handles FDT versions >= 16 (writes version 17).

Commands:

  info FILE
        Header fields and a one-line block layout.

  get FILE
        Full node path tree.
  get FILE NODE
        Node properties (decoded) and child names.
  get FILE NODE PROP
        One property, decoded.

  patch FILE OUT --op 'OP ARGS...' [--op ...]
        Apply operations in order and write the patched blob to OUT.
        Each --op value is split shell-like (shlex), so property names
        such as #reset-cells need no quoting tricks.  Operations:

          set-prop NODE NAME VAL [VAL...]
                add or replace a property.  VAL tokens (concatenated):
                  s:TEXT     - one string
                  S:A,B,C    - string list
                  u:1F,4     - u32 cells (decimal or 0x hex)
                  b:AABBCC   - raw bytes
                  p:/path    - phandle of NODE (auto-assigned if it has
                               none yet: max phandle in the tree + 1)
          del-prop NODE NAME
          add-compatible NODE COMPAT
                append COMPAT to the compatible list (no duplicates).
          create-node NODE
                create NODE (and any missing parents) as an empty node.

  selftest
        Build a small blob, patch it, reparse, assert - proves the
        serializer and the parser agree.

Examples (the 7.1 UFS bring-up):

  # give the apapb-gate clock/reset controller its reset cells
  python scripts/host/dtb_surgery.py patch \\
      artifacts/testimages/vendor_dtb_t38.bin \\
      artifacts/testimages/vendor_dtb_t41.bin \\
      --op 'set-prop /soc/apapb-gate #reset-cells u:1'

  # inspect the UFS node reshape (resets = <&apapb_gate 24 30>)
  python scripts/host/dtb_surgery.py get \\
      artifacts/testimages/vendor_dtb_t41.bin /soc/ap-apb/ufs@20200000

  # drop a regulator reference that has no driver (t38 surgery)
  # --op 'del-prop /soc/ap-apb/ufs@20200000 vcc-supply'
"""

import argparse
import hashlib
import shlex
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 0x1
FDT_END_NODE = 0x2
FDT_PROP = 0x3
FDT_NOP = 0x4
FDT_END = 0x9

FDT_HEADER_SIZE = 40  # version 17 header


class Node:
    def __init__(self, name):
        self.name = name
        self.props = []      # ordered [(name, bytes), ...]
        self.children = []   # ordered [Node, ...]

    def prop(self, name):
        for pname, value in self.props:
            if pname == name:
                return value
        return None

    def set_prop(self, name, value):
        for i, (pname, _) in enumerate(self.props):
            if pname == name:
                self.props[i] = (name, value)
                return
        self.props.append((name, value))

    def del_prop(self, name):
        self.props = [(n, v) for n, v in self.props if n != name]

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None


class Fdt:
    def __init__(self, root, memreserve, boot_cpuid):
        self.root = root
        self.memreserve = memreserve  # raw [(u64, u64), ...] incl. terminator
        self.boot_cpuid = boot_cpuid

    # ---- lookups -------------------------------------------------------
    def node_at(self, path):
        n = self.root
        for part in [p for p in path.split('/') if p]:
            n = n.child(part)
            if n is None:
                return None
        return n

    def all_phandles(self):
        found = {}

        def walk(n):
            ph = n.prop("phandle")
            if ph and len(ph) == 4:
                found[struct.unpack(">I", ph)[0]] = n
            for c in n.children:
                walk(c)

        walk(self.root)
        return found


def parse(data):
    if len(data) < FDT_HEADER_SIZE:
        raise ValueError("file too small to be a DTB")
    (magic, totalsize, off_struct, off_strings, off_rsv, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", data, 0)
    if magic != FDT_MAGIC:
        raise ValueError("bad magic 0x%08x (not a DTB)" % magic)
    if totalsize > len(data):
        raise ValueError("truncated DTB (totalsize %d > file %d)" % (totalsize, len(data)))
    if version < 16:
        raise ValueError("FDT version %d unsupported (need >= 16)" % version)

    # memory reservation block: raw u64 pairs until (0, 0)
    memreserve = []
    pos = off_rsv
    while True:
        pair = struct.unpack_from(">QQ", data, pos)
        memreserve.append(pair)
        pos += 16
        if pair == (0, 0):
            break

    def string_at(off):
        end = data.index(b"\x00", off_strings + off)
        return data[off_strings + off:end].decode()

    root = None
    stack = []
    pos = off_struct
    while True:
        (token,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = data.index(b"\x00", pos)
            name = data[pos:end].decode()
            pos = (end + 1 + 3) & ~3
            node = Node(name)
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("multiple roots in structure block")
            stack.append(node)
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            value = bytes(data[pos:pos + length])
            pos = (pos + length + 3) & ~3
            if not stack:
                raise ValueError("property outside a node")
            stack[-1].props.append((string_at(nameoff), value))
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            raise ValueError("bad structure token 0x%x at %d" % (token, pos - 4))
    if stack:
        raise ValueError("unbalanced BEGIN/END node")
    if root is None:
        raise ValueError("no root node")
    return Fdt(root, memreserve, boot_cpuid)


def serialize(fdt):
    # structure block; property names go to the strings block on the fly
    strings = bytearray()
    string_offsets = {}

    def name_off(name):
        if name not in string_offsets:
            string_offsets[name] = len(strings)
            strings.extend(name.encode() + b"\x00")
        return string_offsets[name]

    out = bytearray()

    def pad4():
        while len(out) & 3:
            out.append(0)

    def emit(n):
        out.extend(struct.pack(">I", FDT_BEGIN_NODE))
        out.extend(n.name.encode() + b"\x00")
        pad4()
        for pname, value in n.props:
            out.extend(struct.pack(">III", FDT_PROP, len(value), name_off(pname)))
            out.extend(value)
            pad4()
        for c in n.children:
            emit(c)
        out.extend(struct.pack(">I", FDT_END_NODE))

    emit(fdt.root)
    out.extend(struct.pack(">I", FDT_END))

    # file layout: header | pad to 8 | memreserve | struct | strings
    off_rsv = FDT_HEADER_SIZE
    rsv = b"".join(struct.pack(">QQ", a, b) for a, b in fdt.memreserve)
    off_struct = off_rsv + len(rsv)
    off_strings = off_struct + len(out)

    header = struct.pack(">10I", FDT_MAGIC, 0, off_struct, off_strings,
                         off_rsv, 17, 16, fdt.boot_cpuid,
                         len(strings), len(out))
    blob = bytearray(header)
    blob.extend(rsv)
    blob.extend(out)
    blob.extend(strings)
    struct.pack_into(">I", blob, 4, len(blob))  # totalsize
    while len(blob) & 3:
        blob.append(0)
        struct.pack_into(">I", blob, 4, len(blob))
    return bytes(blob)


# ---- value encoding / decoding -------------------------------------------

def parse_num(text):
    return int(text, 0)


def encode_value(tokens, fdt):
    value = bytearray()
    for tok in tokens:
        if tok.startswith("s:"):
            value.extend(tok[2:].encode() + b"\x00")
        elif tok.startswith("S:"):
            for part in tok[2:].split(","):
                value.extend(part.encode() + b"\x00")
        elif tok.startswith("u:"):
            for cell in tok[2:].split(","):
                value.extend(struct.pack(">I", parse_num(cell)))
        elif tok.startswith("b:"):
            value.extend(bytes.fromhex(tok[2:]))
        elif tok.startswith("p:"):
            target = fdt.node_at(tok[2:])
            if target is None:
                raise ValueError("p: target node does not exist: %s" % tok[2:])
            ph = target.prop("phandle")
            if ph and len(ph) == 4:
                value.extend(ph)
            else:
                new = max(fdt.all_phandles().keys(), default=0) + 1
                target.set_prop("phandle", struct.pack(">I", new))
                value.extend(struct.pack(">I", new))
        else:
            raise ValueError("bad value token %r "
                             "(use s: S: u: b: or p:)" % tok)
    return bytes(value)


def decode_value(value):
    if value and value[-1:] == b"\x00" and all(32 <= c < 127 or c == 0 for c in value):
        parts = value[:-1].split(b"\x00")
        if all(p for p in parts):  # no empty segments -> a real string list
            return "str: " + ", ".join(p.decode() for p in parts)
    if len(value) % 4 == 0:
        cells = struct.unpack(">%dI" % (len(value) // 4), value)
        return "u32: " + " ".join("0x%08x" % c for c in cells)
    return "hex: " + value.hex()


# ---- operations ------------------------------------------------------------

def need_node(fdt, path):
    n = fdt.node_at(path)
    if n is None:
        raise ValueError("node not found: %s" % path)
    return n


def op_set_prop(fdt, path, name, *vals):
    need_node(fdt, path).set_prop(name, encode_value(vals, fdt))


def op_del_prop(fdt, path, name):
    need_node(fdt, path).del_prop(name)


def op_add_compatible(fdt, path, compat, *more):
    node = need_node(fdt, path)
    for one in (compat,) + more:
        current = node.prop("compatible") or b""
        have = [s.decode() for s in current.split(b"\x00") if s]
        if one not in have:
            have.append(one)
        node.set_prop("compatible",
                      b"".join(s.encode() + b"\x00" for s in have))


def op_create_node(fdt, path):
    parts = [p for p in path.split("/") if p]
    n = fdt.root
    for part in parts:
        c = n.child(part)
        if c is None:
            c = Node(part)
            n.children.append(c)
        n = c


OPS = {
    "set-prop": op_set_prop,
    "del-prop": op_del_prop,
    "add-compatible": op_add_compatible,
    "create-node": op_create_node,
}


def apply_op(fdt, op_line):
    args = shlex.split(op_line)
    if not args or args[0] not in OPS:
        raise ValueError("unknown op: %r (ops: %s)"
                         % (op_line, ", ".join(OPS)))
    name, rest = args[0], args[1:]
    try:
        OPS[name](fdt, *rest)
    except TypeError:
        raise ValueError("bad argument count for %s: %r" % (name, op_line))


# ---- commands ----------------------------------------------------------------

def cmd_info(path):
    data = open(path, "rb").read()
    (magic, totalsize, off_struct, off_strings, off_rsv, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", data, 0)
    print("file        : %s" % path)
    print("sha256      : %s" % hashlib.sha256(data).hexdigest()[:16])
    print("magic       : 0x%08x  totalsize: %d" % (magic, totalsize))
    print("fdt version : %d (last compatible %d)  boot cpu: 0x%x"
          % (version, last_comp, boot_cpuid))
    print("struct      : @0x%x (%d bytes)" % (off_struct, size_struct))
    print("strings     : @0x%x (%d bytes)" % (off_strings, size_strings))
    print("memreserve  : @0x%x" % off_rsv)


def print_tree(node, prefix=""):
    print(prefix + ("/" if not node.name else node.name))
    for c in node.children:
        print_tree(c, prefix + "/" + node.name if node.name else "/")


def cmd_get(path, node_path=None, prop=None):
    fdt = parse(open(path, "rb").read())
    if node_path is None:
        print_tree(fdt.root)
        return
    node = need_node(fdt, node_path)
    if prop is not None:
        value = node.prop(prop)
        if value is None:
            raise ValueError("no property %r on %s" % (prop, node_path))
        print("%s: %s" % (prop, decode_value(value)))
        return
    print("%s (%d props, %d children)"
          % (node_path, len(node.props), len(node.children)))
    for pname, value in node.props:
        print("  %-24s %s" % (pname, decode_value(value)))
    for c in node.children:
        print("  child: %s" % c.name)


def cmd_patch(src, dst, ops):
    data = open(src, "rb").read()
    fdt = parse(data)
    for op in ops:
        apply_op(fdt, op)
        print("op: %s" % op)
    blob = serialize(fdt)
    with open(dst, "wb") as f:
        f.write(blob)
    # round-trip check: the patched blob must parse back
    reparsed = parse(blob)
    print("sha256  in : %s" % hashlib.sha256(data).hexdigest()[:16])
    print("sha256 out: %s" % hashlib.sha256(blob).hexdigest()[:16])
    print("size       : %d -> %d bytes (boot cpu 0x%x, nodes reparse OK)"
          % (len(data), len(blob), reparsed.boot_cpuid))


def cmd_selftest():
    root = Node("")
    soc = Node("soc")
    gate = Node("apapb-gate")
    gate.props.append(("compatible", b"sprd,ums9230-apapb-gate\x00"))
    gate.props.append(("phandle", struct.pack(">I", 0x02)))
    ufs = Node("ufs@20200000")
    ufs.props.append(("resets", struct.pack(">IIII", 0x02, 24, 0x02, 30)))
    soc.children.extend([gate, ufs])
    root.children.append(soc)
    fdt = Fdt(root, [(0, 0)], 0)
    blob = serialize(fdt)
    back = parse(blob)
    assert back.node_at("/soc/apapb-gate").prop("phandle") == struct.pack(">I", 2)
    assert back.node_at("/soc/ufs@20200000").prop("resets") == struct.pack(">IIII", 2, 24, 2, 30)
    apply_op(back, "set-prop /soc/apapb-gate #reset-cells u:1")
    blob2 = serialize(back)
    check = parse(blob2)
    assert check.node_at("/soc/apapb-gate").prop("#reset-cells") == struct.pack(">I", 1)
    # create-node + phandle resolution
    apply_op(check, "create-node /soc/ap-apb/phy@64100800")
    apply_op(check, "set-prop /soc/ap-apb/phy@64100800 reg u:0x64100800,0x1000")
    apply_op(check, "set-prop /soc/ap-apb/phy@64100800 resets p:/soc/apapb-gate u:9")
    final = parse(serialize(check))
    phy = final.node_at("/soc/ap-apb/phy@64100800")
    assert struct.unpack(">II", phy.prop("resets")) == (2, 9)
    assert struct.unpack(">II", phy.prop("reg")) == (0x64100800, 0x1000)
    assert final.node_at("/soc/apapb-gate").prop("#reset-cells") == struct.pack(">I", 1)
    print("selftest OK: serialize/parse/patch/phandle-assign all consistent")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="header and block layout")
    p.add_argument("file")

    p = sub.add_parser("get", help="inspect nodes/properties")
    p.add_argument("file")
    p.add_argument("node", nargs="?", default=None)
    p.add_argument("prop", nargs="?", default=None)

    p = sub.add_parser("patch", help="apply --op operations and write OUT")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--op", action="append", default=[],
                   help="operation, shell-quoted, e.g. "
                        "--op 'set-prop /soc/apapb-gate #reset-cells u:1'")

    sub.add_parser("selftest", help="prove serializer and parser agree")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "info":
            cmd_info(args.file)
        elif args.cmd == "get":
            cmd_get(args.file, args.node, args.prop)
        elif args.cmd == "patch":
            cmd_patch(args.src, args.dst, args.op)
        elif args.cmd == "selftest":
            cmd_selftest()
    except (ValueError, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
