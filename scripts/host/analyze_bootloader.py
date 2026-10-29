#!/usr/bin/env python3
"""Extract RSA public keys from Motorola/Unisoc bootloader dumps.

Analyses an unlocked-device dump directory (uboot_a.img, vbmeta_a.img, ...) and
prints the fingerprints of every embedded public key, so they can be compared
with a candidate leaked key (e.g. the Unisoc "rsa4096_vbmeta.pem").

Usage:
    python analyze_bootloader.py <dump-dir> [--compare key.pem]

Key formats handled:
  * DER SubjectPublicKeyInfo (U-Boot / TrustOS / OpenSSL blobs)
  * AVB public key blobs (vbmeta auxiliary data: u32 bits, u32 n0inv, n, rr)
"""

import argparse
import base64
import hashlib
import pathlib
import struct
import sys

RSA_OID = bytes.fromhex("2a864886f70d010101")
SPKI_HEAD = bytes.fromhex("300d06092a864886f70d0101010500")
AVB_MAGIC = b"AVB0"


def der_length(buf, pos):
    """Read a DER length at pos, return (length, bytes_consumed)."""
    first = buf[pos]
    if first & 0x80:
        n = first & 0x7F
        return int.from_bytes(buf[pos + 1:pos + 1 + n], "big"), 1 + n
    return first, 1


def spki_modulus(blob):
    """Return the modulus of a DER SubjectPublicKeyInfo, or None."""
    try:
        pos = 0
        if blob[pos] != 0x30:              # outer SEQUENCE
            return None
        _, n = der_length(blob, pos + 1)
        pos += 1 + n
        if blob[pos] != 0x30:              # AlgorithmIdentifier SEQUENCE
            return None
        alg_len, n = der_length(blob, pos + 1)
        pos += 1 + n + alg_len             # skip the whole AlgorithmIdentifier
        if blob[pos] != 0x03:              # BIT STRING
            return None
        bit_len, n = der_length(blob, pos + 1)
        pos += 1 + n
        pos += 1                           # unused-bits byte
        if blob[pos] != 0x30:              # RSAPublicKey SEQUENCE
            return None
        _, n = der_length(blob, pos + 1)
        pos += 1 + n
        if blob[pos] != 0x02:              # INTEGER modulus
            return None
        mod_len, n = der_length(blob, pos + 1)
        pos += 1 + n
        mod = blob[pos:pos + mod_len]
        return mod.lstrip(b"\x00")
    except (IndexError, ValueError):
        return None


def iter_spki_keys(data):
    off = 0
    while True:
        i = data.find(SPKI_HEAD, off)
        if i < 0:
            return
        # The outer SEQUENCE header sits 2-5 bytes before the inner one
        # (30 xx / 30 81 xx / 30 82 xx xx / 30 83 xx xx xx).
        for delta in (2, 3, 4, 5):
            start = i - delta
            if start < 0 or data[start] != 0x30:
                continue
            try:
                length, ln_size = der_length(data, start + 1)
            except (IndexError, ValueError):
                continue
            total = 1 + ln_size + length
            if start + total < i + 20 or start + total > len(data):
                continue
            blob = data[start:start + total]
            mod = spki_modulus(blob)
            if mod and len(mod) in (128, 256, 384, 512, 1024):
                yield start, len(mod) * 8, mod
            break
        off = i + 1


def iter_avb_keys(data):
    if not data.startswith(AVB_MAGIC):
        return
    auth_size, aux_size = struct.unpack(">QQ", data[12:28])
    pk_off, pk_size = struct.unpack(">QQ", data[64:80])
    if not pk_size:
        return
    start = 256 + auth_size + pk_off
    blob = data[start:start + pk_size]
    if len(blob) < 8:
        return
    bits = int.from_bytes(blob[0:4], "big")
    if bits not in (2048, 4096, 8192):
        return
    n = blob[8:8 + bits // 8]
    yield start, bits, n


def load_pem_modulus(path):
    text = pathlib.Path(path).read_text()
    der = base64.b64decode("".join(l for l in text.splitlines()
                                   if not l.startswith("-----")))
    # RSAPrivateKey: version INTEGER, modulus INTEGER
    i = der.find(b"\x02\x82")
    while i >= 0:
        ln = int.from_bytes(der[i + 2:i + 4], "big")
        body = der[i + 4:i + 4 + ln]
        if body[:1] == b"\x00" and ln - 1 in (256, 512, 1024):
            return body[1:]
        i = der.find(b"\x02\x82", i + 1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dumpdir")
    ap.add_argument("--compare", help="PEM key to compare against")
    args = ap.parse_args()

    root = pathlib.Path(args.dumpdir)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        print("no files in %s" % root, file=sys.stderr)
        return 1

    wanted = load_pem_modulus(args.compare) if args.compare else None
    if args.compare and wanted is None:
        print("could not parse %s" % args.compare, file=sys.stderr)
        return 1
    if wanted:
        print("candidate key: %d bits sha256=%s"
              % (len(wanted) * 8, hashlib.sha256(wanted).hexdigest()))

    found = 0
    for path in files:
        data = path.read_bytes()
        keys = []
        for off, bits, mod in iter_spki_keys(data):
            keys.append(("DER", off, bits, mod))
        for off, bits, mod in iter_avb_keys(data):
            keys.append(("AVB", off, bits, mod))
        if not keys:
            continue
        print("== %s (%d bytes)" % (path.name, len(data)))
        for kind, off, bits, mod in keys:
            fp = hashlib.sha256(mod).hexdigest()
            tag = ""
            if wanted and mod == wanted:
                tag = "  *** MATCHES CANDIDATE ***"
                found += 1
            print("   %s key @%08x %4d bits sha256=%s%s"
                  % (kind, off, bits, fp, tag))

    if args.compare:
        print("\ncandidate matches: %d" % found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
