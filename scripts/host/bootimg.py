#!/usr/bin/env python3
"""Unpack and repack AOSP boot images (header versions 0-2).

The device's boot partition is an AOSP boot image, so a custom kernel has to be
packed into that container (for `fastboot flash boot_b`, or for archival).  No
mkbootimg is available here, and the stock image has to be reproduced
byte-for-byte apart from the kernel payload, so this tool parses and rewrites
the header itself.

Note: `fastboot boot` on this phone does not execute the payload (it ACKs and
reboots), so the packed image is only useful for a flash write.

Layout (page aligned, page_size from the header):

    page 0                     header
    kernel                     kernel_size bytes
    ramdisk                    ramdisk_size bytes
    second                     second_size bytes
    recovery_dtbo              recovery_dtbo_size bytes   (v2)
    dtb                        dtb_size bytes            (v2)

Usage:
    bootimg.py unpack <boot.img> <out-dir>
    bootimg.py pack   <boot.img> <out-dir> <boot.img> [--kernel new-image]

`pack` keeps the header fields (cmdline, page size, addresses, dtb, ...),
replaces the kernel payload and recomputes kernel_size plus the SHA-1 id.
The payload is written verbatim: if the stock kernel was gzip'ed, the
replacement has to be gzip'ed too.
"""
import argparse
import hashlib
import os
import pathlib
import struct
import sys

MAGIC = b"ANDROID!"
HEADER_V0_SIZE = 1632      # struct boot_img_hdr
HEADER_V2_SIZE = 1728      # struct boot_img_hdr_v2


def parse(buf):
    if buf[:8] != MAGIC:
        raise SystemExit("not an ANDROID! boot image")
    h = {
        "kernel_size": struct.unpack_from("<I", buf, 0x08)[0],
        "kernel_addr": struct.unpack_from("<I", buf, 0x0C)[0],
        "ramdisk_size": struct.unpack_from("<I", buf, 0x10)[0],
        "ramdisk_addr": struct.unpack_from("<I", buf, 0x14)[0],
        "second_size": struct.unpack_from("<I", buf, 0x18)[0],
        "second_addr": struct.unpack_from("<I", buf, 0x1C)[0],
        "tags_addr": struct.unpack_from("<I", buf, 0x20)[0],
        "page_size": struct.unpack_from("<I", buf, 0x24)[0],
        "header_version": struct.unpack_from("<I", buf, 0x28)[0],
        "os_version": struct.unpack_from("<I", buf, 0x2C)[0],
        "name": buf[0x30:0x40].split(b"\0")[0].decode("utf-8", "replace"),
        "cmdline": buf[0x40:0x240].split(b"\0")[0].decode("utf-8", "replace"),
        "extra_cmdline": buf[0x260:0x660].split(b"\0")[0].decode("utf-8", "replace"),
        "id": buf[0x240:0x260],
    }
    if h["header_version"] >= 2:
        h["recovery_dtbo_size"] = struct.unpack_from("<I", buf, 0x660)[0]
        h["recovery_dtbo_offset"] = struct.unpack_from("<Q", buf, 0x664)[0]
        h["dtb_size"] = struct.unpack_from("<I", buf, 0x670)[0]
        h["dtb_addr"] = struct.unpack_from("<Q", buf, 0x674)[0]
    return h


def offsets(h):
    """Return {component: (offset, size)} for the payload sections."""
    ps = h["page_size"]
    off = ps
    out = {}
    for name in ("kernel", "ramdisk", "second"):
        out[name] = (off, h[f"{name}_size"])
        off += (h[f"{name}_size"] + ps - 1) // ps * ps
    if h.get("recovery_dtbo_size"):
        out["recovery_dtbo"] = (off, h["recovery_dtbo_size"])
        off += (h["recovery_dtbo_size"] + ps - 1) // ps * ps
    if h.get("dtb_size"):
        out["dtb"] = (off, h["dtb_size"])
        off += (h["dtb_size"] + ps - 1) // ps * ps
    return out


def cmd_unpack(args):
    buf = pathlib.Path(args.image).read_bytes()
    h = parse(buf)
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "header.bin").write_bytes(buf[:h["page_size"]])

    print(f"magic         ANDROID!")
    print(f"header_version {h['header_version']}")
    print(f"page_size      {h['page_size']}")
    print(f"name           {h['name']!r}")
    print(f"os_version     0x{h['os_version']:08x}")
    print(f"cmdline        {h['cmdline']!r}")
    if h["extra_cmdline"]:
        print(f"extra_cmdline  {h['extra_cmdline']!r}")
    print(f"id             {h['id'].hex()}")
    for k in ("kernel_addr", "ramdisk_addr", "second_addr", "tags_addr"):
        print(f"{k:14} 0x{h[k]:08x}")
    if h.get("dtb_addr"):
        print(f"dtb_addr       0x{h['dtb_addr']:016x}")
    print()

    for name, (off, size) in offsets(h).items():
        data = buf[off:off + size]
        (out / f"{name}.bin").write_bytes(data)
        magic = ""
        if data[:2] == b"\x1f\x8b":
            magic = "gzip"
        elif data[:4] == b"\x27\x05\x19\x56":
            magic = "lz4"
        elif data[:4] == b"\x5d\x00\x00":
            magic = "lzma"
        elif data[:4] == b"\x02\x21\x4c\x18":
            magic = "lz4(old)"
        elif data[:4] == b"\x89PNG":
            magic = "png"
        elif data[:4] == b"ARM\x64":
            magic = "raw ARM64 Image"
        elif data[:4] == b"\xd0\x0d\xfe\xed":
            magic = "FDT"
        print(f"{name:15} offset=0x{off:08x} size={size:>10,}  {magic}")

    (out / "meta.txt").write_text(
        "\n".join(f"{k}={v!r}" for k, v in h.items() if isinstance(v, (int, str))) + "\n")
    print(f"\nunpacked into {out}")


def cmd_pack(args):
    out = pathlib.Path(args.outdir)
    buf = pathlib.Path(args.image).read_bytes()
    h = parse(buf)
    ps = h["page_size"]

    kernel = (out / "kernel.bin").read_bytes()
    if args.kernel:
        kernel = pathlib.Path(args.kernel).read_bytes()

    parts = []
    cur = ps
    new_kernel_size = len(kernel)

    def emit(data):
        parts.append(data)
        pad = (-len(data)) % ps
        if pad:
            parts.append(b"\0" * pad)

    emit(kernel)
    hashed = [kernel]
    for name in ("ramdisk", "second", "recovery_dtbo", "dtb"):
        p = out / f"{name}.bin"
        if not p.exists():
            continue
        data = p.read_bytes()
        emit(data)
        hashed.append(data)

    hdr = bytearray(buf[:ps])
    struct.pack_into("<I", hdr, 0x08, new_kernel_size)
    # the id is the SHA-1 of the kernel + ramdisk + second + recovery_dtbo + dtb
    sha = hashlib.sha1()
    for part in hashed:
        sha.update(part)
    # NB: the id field is 32 bytes (20 byte SHA-1 + 12 zero bytes); assigning a
    # shorter slice would *resize* the bytearray and shift every later field.
    digest = sha.digest()
    hdr[0x240:0x260] = digest + bytes(32 - len(digest))

    body = b"".join(parts)
    img = bytes(hdr) + body
    pathlib.Path(args.output).write_bytes(img)
    print(f"wrote {args.output}: {len(img):,} bytes")
    print(f"  kernel {new_kernel_size:,} bytes (was {parse(buf)['kernel_size']:,})")
    print(f"  id     {sha.hexdigest()}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("unpack")
    u.add_argument("image")
    u.add_argument("outdir")
    u.set_defaults(func=cmd_unpack)

    p = sub.add_parser("pack")
    p.add_argument("image", help="original boot image to take the header from")
    p.add_argument("outdir")
    p.add_argument("output")
    p.add_argument("--kernel", help="replace the kernel payload with this file")
    p.set_defaults(func=cmd_pack)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
