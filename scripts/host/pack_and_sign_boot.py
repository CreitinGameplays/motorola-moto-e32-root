"""Pack a kernel Image into the stock boot-image container and AVB-sign it.

Same layout as stock:
    [ ANDROID! header+kernel+ramdisk+dtb ][ vbmeta AVB0 ][ zero pad ][ AVBf ]

The header (cmdline, addresses, page size, dtb, ...) is copied from the stock
image verbatim; only kernel_size and the SHA-1 id are recomputed, so the only
variable in a boot experiment is the kernel payload.

Usage:
    python scripts/host/pack_and_sign_boot.py <kernel-Image> <out.img>
           [--base <stock boot img>] [--key <pem>] [--no-sign]

Default base is the stock boot_b backup (the kernel/ramdisk that the installed
system actually boots).
"""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bootimg  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = ROOT / "artifacts" / "kernel-build"
DEFAULT_BASE = pathlib.Path(
    r"D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\boot_b.img")
DEFAULT_KEY = BUILD / "avb-test-key.pem"
AVBTOOL = pathlib.Path(r"D:\AndroidSDKTools\avb\avbtool.py")

PARTITION_SIZE = 67108864
SALT = "f83b993601311bca149a573c1e737666ff011f6cf2aa2a5ae822f91b97af0991"
ALGORITHM = "SHA256_RSA4096"
ROLLBACK_INDEX = 2


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def build(base, kernel, cmdline_extra=None, ramdisk=None):
    buf = base.read_bytes()
    h = bootimg.parse(buf)
    ps = h["page_size"]

    parts = []
    hashed = []

    def emit(data):
        parts.append(data)
        pad = (-len(data)) % ps
        if pad:
            parts.append(b"\0" * pad)

    emit(kernel)
    hashed.append(kernel)

    for name in ("ramdisk", "second", "recovery_dtbo", "dtb"):
        if name == "ramdisk" and ramdisk is not None:
            emit(ramdisk)
            hashed.append(ramdisk)
            print("  %-14s %10d bytes (override)" % (name, len(ramdisk)))
            continue
        size = h.get(f"{name}_size")
        if not size:
            continue
        off = bootimg.offsets(h)[name][0]
        data = buf[off:off + size]
        emit(data)
        hashed.append(data)
        print("  %-14s %10d bytes from base at 0x%x" % (name, size, off))

    hdr = bytearray(buf[:ps])
    struct.pack_into("<I", hdr, 0x08, len(kernel))
    if ramdisk is not None:
        struct.pack_into("<I", hdr, 0x10, len(ramdisk))
        h["ramdisk_size"] = len(ramdisk)
    if cmdline_extra:
        cur = hdr[0x40:0x40 + 512].split(b"\0", 1)[0]
        new = (cur + b" " + cmdline_extra.encode()).ljust(512, b"\0")
        if len(cur) + 1 + len(cmdline_extra) > 512:
            sys.exit("cmdline would exceed the 512-byte header field")
        hdr[0x40:0x40 + 512] = new
        h["cmdline"] = new.split(b"\0", 1)[0].decode()
    digest = hashlib.sha1()
    for part in hashed:
        digest.update(part)
    hdr[0x240:0x260] = digest.digest() + bytes(12)

    return bytes(hdr) + b"".join(parts), h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("output")
    ap.add_argument("--base", default=str(DEFAULT_BASE))
    ap.add_argument("--key", default=str(DEFAULT_KEY))
    ap.add_argument("--no-sign", action="store_true")
    ap.add_argument("--cmdline-extra", default=None,
                    help="append this token to the boot image cmdline")
    ap.add_argument("--ramdisk", default=None,
                    help="replace the base ramdisk (e.g. rescue initramfs cpio)")
    ap.add_argument("--entry-paint", action="store_true",
                    help="replace the Image header in the loaded copy with the "
                         "framebuffer-paint stub (scripts/host/entry_paint.py); "
                         "paints a white band before head.S so a hang proves "
                         "the bootloader entered the Image")
    ap.add_argument("--entry-hang", action="store_true",
                    help="like --entry-paint, but the stub ends with `b .` "
                         "instead of `b stext`: paints one band and stops dead, "
                         "to calibrate how long the panel keeps that image")
    args = ap.parse_args()

    kernel = pathlib.Path(args.kernel).read_bytes()
    ramdisk = pathlib.Path(args.ramdisk).read_bytes() if args.ramdisk else None
    base = pathlib.Path(args.base)
    out = pathlib.Path(args.output)

    if kernel[0x38:0x3c] != b"ARMd":
        sys.exit("%s is not an arm64 Image" % args.kernel)

    img, h = build(base, kernel, args.cmdline_extra, ramdisk)
    ps = h["page_size"]
    if args.entry_paint or args.entry_hang:
        import entry_paint  # noqa: E402  (sibling module)
        first = 0x14000000 if args.entry_hang else kernel[:4]
        stub = entry_paint.build_stub(first)
        img = bytearray(img)
        img[ps:ps + len(stub)] = stub
        img = bytes(img)
        print("\nentry-%s stub written at payload offset 0x%x:"
              % ("hang" if args.entry_hang else "paint", ps))
        print("  %s" % stub.hex())
    out.write_bytes(img)
    print("\nbase %s (%d bytes)" % (base.name, base.stat().st_size))
    print("wrote %s: %d bytes  sha256 %s" % (out.name, len(img), sha256(img)))
    print("  kernel_size %d (0x%x)  page_size %d  header_version %d"
          % (len(kernel), len(kernel), h["page_size"], h["header_version"]))
    print("  cmdline %r" % h["cmdline"])
    print("  dtb_size %s" % h.get("dtb_size"))

    # the payload prefix must be byte-identical to what we intended to write
    # (img = [header page][kernel][...], so compare from the first payload page)
    ps = h["page_size"]
    if args.entry_paint or args.entry_hang:
        print("  payload prefix matches kernel: %s (first %d bytes are the stub)"
              % (img[ps + entry_paint.STUB_SIZE:ps + len(kernel)] ==
                 kernel[entry_paint.STUB_SIZE:], entry_paint.STUB_SIZE))
    else:
        print("  payload prefix matches kernel: %s" % (img[ps:ps + len(kernel)] == kernel))

    if args.no_sign:
        print("\nunsigned (--no-sign); not bootable past TrustOS")
        return

    print("\nrunning avbtool add_hash_footer ...")
    subprocess.run([
        sys.executable, str(AVBTOOL), "add_hash_footer",
        "--image", str(out),
        "--partition_name", "boot",
        "--partition_size", str(PARTITION_SIZE),
        "--key", args.key,
        "--algorithm", ALGORITHM,
        "--rollback_index", str(ROLLBACK_INDEX),
        "--salt", SALT,
    ], check=True)

    signed = out.read_bytes()
    print("\nsigned %s: %d bytes  sha256 %s" % (out.name, len(signed), sha256(signed)))
    print("  payload prefix still matches: %s" % (signed[:len(img)] == img))


if __name__ == "__main__":
    main()