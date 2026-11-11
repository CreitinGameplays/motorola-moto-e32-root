#!/usr/bin/env python3
"""Build the hybrid initramfs for the 7.1 Android-userspace test.

The stock Android ramdisk (recovery-in-boot layout: /init is a symlink
to /system/bin/init, plus first_stage_ramdisk/, ueventd rcs, sepolicy,
prop.default) is kept *verbatim* - only /init is replaced by our hybrid
binary, which mounts the pseudo filesystems, forks the ring-saver child
that keeps the kernel ring in the sysdumpdb partition and then execs
the stock init (which becomes PID 1).

Why: an Android boot that dies before adbd leaves no evidence at all
without this - the ring saver captures the kernel ring including the
first-stage init's own kmsg output, readable from Android after the
recovery.

Usage:
    build_71_hybridramfs.py --stock-boot <stock boot_b.img> \\
        --init <hybrid init binary> --out <out.cpio.gz>
"""

import argparse
import gzip
import io
import struct
import sys

# newc cpio field indices (13 hex fields after the magic)
C_INO, C_MODE, C_UID, C_GID, C_NLINK, C_MTIME, C_FILESIZE = 0, 1, 2, 3, 4, 5, 6
C_DEVMAJ, C_DEVMIN, C_RDEVMAJ, C_RDEVMIN, C_NAMESIZE, C_CHECK = 7, 8, 9, 10, 11, 12


def ramdisk_from_boot_image(path):
    """Return the (still compressed) ramdisk blob of an Android boot image."""
    with open(path, "rb") as f:
        hdr = f.read(4096)
        if hdr[:8] != b"ANDROID!":
            sys.exit("not an Android boot image: %s" % path)
        version = struct.unpack("<I", hdr[40:44])[0]
        if version < 2:
            sys.exit("boot header v%d not supported (need v2+)" % version)
        kernel_size = struct.unpack("<I", hdr[8:12])[0]
        ramdisk_size = struct.unpack("<I", hdr[16:20])[0]
        page_size = struct.unpack("<I", hdr[36:40])[0]
        if version >= 3:
            # v3: the ramdisk lives in vendor_boot, the boot image only has
            # the generic ramdisk
            sys.exit("boot header v3: the stock ramdisk is in vendor_boot, "
                     "pass the extracted ramdisk instead")
        offset = page_size * (1 + (kernel_size + page_size - 1) // page_size)
        f.seek(offset)
        return f.read(ramdisk_size)


def parse_cpio(data):
    """Yield (name, mode, uid, gid, nlink, mtime, content, devmajor, devminor)."""
    pos = 0
    while pos < len(data):
        if data[pos:pos + 6] != b"070701":
            break
        fields = [int(data[pos + 6 + 8 * i:pos + 6 + 8 * i + 8], 16) for i in range(13)]
        namesize = fields[C_NAMESIZE]
        name = data[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "replace")
        fpos = (pos + 110 + namesize + 3) & ~3
        size = fields[C_FILESIZE]
        content = data[fpos:fpos + size]
        if name == "TRAILER!!!":
            break
        yield (name, fields[C_MODE], fields[C_UID], fields[C_GID],
               fields[C_NLINK], fields[C_MTIME], content,
               fields[C_DEVMIN], fields[C_RDEVMIN])
        pos = fpos + ((size + 3) & ~3)


def write_cpio(entries, out):
    """Write a newc cpio archive."""
    ino = 1
    for (name, mode, uid, gid, nlink, mtime, content, rdev, _) in entries:
        n = name.encode() + b"\0"
        hdr = b"070701"
        fields = [ino, mode, uid, gid, nlink, mtime, len(content), 0, 0,
                  rdev >> 8, rdev & 0xff, len(n), 0]
        hdr += b"".join(b"%08X" % f for f in fields)
        out.write(hdr)
        out.write(n)
        out.write(b"\0" * ((-len(hdr) - len(n)) % 4))
        out.write(content)
        out.write(b"\0" * ((-len(content)) % 4))
        ino += 1
    # trailer
    fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    out.write(b"070701" + b"".join(b"%08X" % f for f in fields))
    out.write(b"TRAILER!!!\0")
    out.write(b"\0" * ((-110 - 10) % 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-boot", help="stock boot_b.img (header v2)")
    ap.add_argument("--stock-ramdisk", help="already extracted ramdisk blob")
    ap.add_argument("--init", required=True, help="our hybrid init binary")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-init-name", default="/system/bin/init",
                    help="where the stock init is expected (we exec it)")
    args = ap.parse_args()

    if args.stock_ramdisk:
        blob = open(args.stock_ramdisk, "rb").read()
    else:
        blob = ramdisk_from_boot_image(args.stock_boot)

    data = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob

    hybrid = open(args.init, "rb").read()

    entries = []
    replaced = False
    for e in parse_cpio(data):
        name, mode = e[0], e[1]
        if name == "init":
            # the stock /init is a symlink to /system/bin/init - we take
            # its place with the hybrid binary
            entries.append((name, 0o100755, e[2], e[3], e[4], e[5], hybrid, 0, 0))
            replaced = True
            continue
        entries.append(e)

    if not replaced:
        sys.exit("no /init entry in the stock ramdisk")

    buf = io.BytesIO()
    write_cpio(entries, buf)
    with gzip.GzipFile(args.out, "wb", compresslevel=9, mtime=0) as gz:
        gz.write(buf.getvalue())
    print("hybrid ramdisk: %s (%d bytes raw, %d entries)"
          % (args.out, len(buf.getvalue()), len(entries)))
    print("  /init is now the hybrid binary; the stock init stays at %s"
          % args.keep_init_name)


if __name__ == "__main__":
    main()
