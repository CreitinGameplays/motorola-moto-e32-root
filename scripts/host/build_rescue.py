"""Build the boot_a rescue boot image.

Layout produced (all offsets from the stock image, unchanged):
    [ANDROID! hdr][stock kernel][our gzip cpio ramdisk][stock dtb][vbmeta][pad][AVBf]

The cpio contains:
    /init            static aarch64 rescue init (dry or restore build)
    /blob/boot_b     stock boot_b bytes [0 .. original_image_size+vbmeta)
    /blob/footer     stock 64-byte AVB footer (from partition end)

Usage:
    python scripts/host/build_rescue.py dry|restore <out.img>
"""
import gzip
import hashlib
import io
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESCUE = ROOT / "artifacts" / "rescue"
STOCK = pathlib.Path(r"D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\boot_b.img")
PACKER = ROOT / "scripts" / "host" / "pack_and_sign_boot.py"
PART_SIZE = 0x4000000
FOOTER_OFF = PART_SIZE - 64


def be64(b, off):
    return struct.unpack_from(">Q", b, off)[0]


def pad_after(data):
    n = len(data)
    return ((n + 2047) // 2048) * 2048


def cpio_newc(entries):
    out = bytearray()
    ino = 1
    for name, mode, data in entries:
        nb = name.encode() + b"\0"
        fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(nb), 0)
        hdr = b"070701" + b"".join(b"%08x" % f for f in fields)
        out += hdr + nb
        out += b"\0" * ((4 - (len(hdr) + len(nb)) % 4) % 4)
        out += data
        out += b"\0" * ((4 - len(data) % 4) % 4)
        ino += 1
    nb = b"TRAILER!!!\0"
    hdr = b"070701" + b"".join(b"%08x" % f for f in (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(nb), 0))
    out += hdr + nb
    out += b"\0" * ((4 - (len(hdr) + len(nb)) % 4) % 4)
    return bytes(out)


def gz(data):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as f:
        f.write(data)
    return buf.getvalue()


def cpio_entries(data):
    """Parse a newc cpio archive; returns [(name, mode, data)]."""
    out = []
    i = 0
    while i + 110 <= len(data):
        if data[i:i + 6] != b"070701":
            sys.exit("bad cpio magic at %d" % i)
        f = [int(data[i + 6 + 8 * k:i + 14 + 8 * k], 16) for k in range(13)]
        mtime, namesize = f[5], f[11]
        name = data[i + 110:i + 110 + namesize - 1].decode()
        j = i + 110 + namesize
        j += (4 - j % 4) % 4
        size = f[6]
        body = data[j:j + size]
        j += size
        j += (4 - j % 4) % 4
        if name == "TRAILER!!!":
            break
        out.append((name, f[1], body))
        i = j
    return out


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("dry", "restore"):
        sys.exit(__doc__)
    mode, out_path = sys.argv[1], pathlib.Path(sys.argv[2])

    init = RESCUE / ("rescue_init_dry" if mode == "dry" else "rescue_init_restore")
    if not init.exists():
        sys.exit("missing %s (compile on test-vps first)" % init)

    d = STOCK.read_bytes()
    if len(d) != PART_SIZE or d[FOOTER_OFF:FOOTER_OFF + 4] != b"AVBf":
        sys.exit("stock boot_b is not the expected 64 MiB AVB image")
    if d[:8] != b"ANDROID!":
        sys.exit("stock boot_b has no ANDROID! header")

    orig = struct.unpack_from(">I", d, FOOTER_OFF + 16)[0]
    vbs = struct.unpack_from(">I", d, FOOTER_OFF + 32)[0]
    extent = orig + vbs
    if extent != 34724096:
        sys.exit("unexpected stock extent 0x%x (init expects 0x211d900)" % extent)
    tail = d[extent:FOOTER_OFF]
    if any(tail):
        sys.exit("non-zero bytes between payload end and footer; refusing")

    hdr = d[:2048]
    ksize = struct.unpack_from("<I", hdr, 0x08)[0]
    kernel = d[2048:2048 + ksize]
    if kernel[0x38:0x3c] != b"ARMd":
        sys.exit("extracted kernel is not an arm64 Image")

    blob = d[:extent]
    footer = d[FOOTER_OFF:FOOTER_OFF + 64]
    init_blob = init.read_bytes()
    if init_blob[:4] != b"\x7fELF":
        sys.exit("%s is not an ELF" % init)

    cpio = cpio_newc([
        ("dev", 0o040755, b""),
        ("blob", 0o040755, b""),
        ("init", 0o100755, init_blob),
        ("blob/boot_b", 0o100644, blob),
        ("blob/footer", 0o100644, footer),
    ])
    ramdisk = gz(cpio)

    RESCUE.mkdir(parents=True, exist_ok=True)
    (RESCUE / "kernel.stock").write_bytes(kernel)
    (RESCUE / ("ramdisk_%s.cpio.gz" % mode)).write_bytes(ramdisk)
    (RESCUE / ("blob_%s.bin" % mode)).write_bytes(blob + footer)

    out = pathlib.Path(out_path)
    if not out.is_absolute():
        out = ROOT / out
    cmd = [
        sys.executable, str(PACKER), str(RESCUE / "kernel.stock"), str(out),
        "--base", str(STOCK), "--ramdisk", str(RESCUE / ("ramdisk_%s.cpio.gz" % mode)),
    ]
    subprocess.run(cmd, check=True)

    img = out.read_bytes()
    print("\n=== rescue image (%s) ===" % mode)
    print("  size           %d (expect %d)" % (len(img), PART_SIZE))
    print("  ramdisk_size   %d" % struct.unpack_from("<I", img, 0x10)[0])
    print("  kernel_size    %d" % struct.unpack_from("<I", img, 0x08)[0])
    print("  footer at      %s (expect %s)"
          % (hex(len(img) - 64), hex(FOOTER_OFF)))
    print("  AVBf magic     %r" % img[-64:-60])
    print("  sha256         %s" % hashlib.sha256(img).hexdigest())
    print("  blob extent    %d bytes, footer %d bytes, init %d bytes"
          % (len(blob), len(footer), len(init_blob)))

    if len(img) != PART_SIZE:
        sys.exit("bad image size")
    # payload must still start with ANDROID! and contain our ramdisk
    if img[:8] != b"ANDROID!":
        sys.exit("bad magic")
    if img[2048 + pad_after(kernel):][:2] != b"\x1f\x8b":
        sys.exit("ramdisk did not land right after the kernel")

    # --- offline proof 1: the cpio carries exactly the stock blob ---
    ents = cpio_entries(gzip.decompress(ramdisk))
    by_name = {n: (m, b) for n, m, b in ents}
    print("\n=== cpio ===")
    for n, m, b in ents:
        print("  %-16s mode %06o  %10d bytes" % (n, m, len(b)))
    if by_name["blob/boot_b"][1] != blob:
        sys.exit("embedded blob != stock extent")
    if by_name["blob/footer"][1] != footer:
        sys.exit("embedded footer != stock footer")
    if by_name["init"][1] != init_blob or by_name["init"][0] != 0o100755:
        sys.exit("init entry is wrong")

    # --- offline proof 2: blob + zeros + footer reproduces the stock image ---
    rebuilt = blob + bytes(FOOTER_OFF - len(blob)) + footer
    print("  rebuild == stock image: %s (%d bytes)" % (rebuilt == d, len(rebuilt)))
    if rebuilt != d:
        sys.exit("reconstructed boot_b does not match the stock backup")


if __name__ == "__main__":
    main()