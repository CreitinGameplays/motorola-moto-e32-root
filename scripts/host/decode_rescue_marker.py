"""Decode the DRESCUE1 marker + A/B block collected by
scripts/device/rescue_forensics.sh (rescue-forensics/marker.bin, ab32.bin).

Usage: python scripts/host/decode_rescue_marker.py <marker.bin> [ab32.bin]
"""
import pathlib
import struct
import sys
import zlib

STATUS = {
    1: "restore started",
    2: "restore OK (blob written, footer written, slot patched)",
    3: "restore FAILED (something above, see extra/hashes)",
    10: "dry run: blob hashed OK",
    11: "dry run: A/B block written and read back OK",
    12: "dry run: A/B write FAILED (extra = negative errno)",
    90: "blob/boot_b not readable",
    91: "blob/footer not readable",
    92: "blob truncated or footer wrong size",
    93: "open(/dev/boot_b) for write failed",
    94: "copy of blob into boot_b mismatched",
    95: "zero padding write failed (extra = offset)",
    96: "footer write/read failed",
    99: "init started (nodes created)",
}
MODES = {0: "dry", 1: "restore"}
BLOB_EXPECT = 34724096


def slot_info(v):
    return "priority %d, tries %d, successful %d, verity %d" % (
        v & 0xF, (v >> 4) & 7, (v >> 7) & 1, (v >> 8) & 1)


def decode_ab(b: bytes, label):
    if len(b) < 32:
        print("%s: too short (%d B)" % (label, len(b)))
        return
    magic = b[4:8]
    v = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
    print("%s suffix=%r magic=%r version=%d nb_slot=%d"
          % (label, b[:4], magic, b[8], b[9]))
    print("    slot a: %s  (raw %#06x)" % (slot_info(b[12] | (b[13] << 8)), b[12] | (b[13] << 8)))
    print("    slot b: %s  (raw %#06x)" % (slot_info(b[14] | (b[15] << 8)), b[14] | (b[15] << 8)))
    crc = struct.unpack_from("<I", b, 28)[0]
    want = zlib.crc32(b[:28])
    print("    crc32  %#010x  computed %#010x  %s"
          % (crc, want, "OK" if crc == want else "MISMATCH"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    m = pathlib.Path(sys.argv[1]).read_bytes()[:128]
    if m[:8] != b"DRESCUE1":
        print("no DRESCUE1 marker (first 16 bytes: %s)" % m[:16].hex())
        print("-> the rescue /init never wrote a record: it most likely never ran")
        return
    ver, mode, status = struct.unpack_from("<III", m, 8)
    bsize, bhash, fhash, extra = struct.unpack_from("<QQQQ", m, 24)
    print("marker version %d, mode %s, status %d = %s"
          % (ver, MODES.get(mode, mode), status, STATUS.get(status, "unknown")))
    print("blob size  %d (expect %d) %s"
          % (bsize, BLOB_EXPECT, "OK" if bsize == BLOB_EXPECT else "MISMATCH"))
    print("blob fnv   %#018x" % bhash)
    print("footer fnv %#018x" % fhash)
    print("extra      %#x (%d)" % (extra, extra))
    decode_ab(m[64:96], "misc A/B before:")
    decode_ab(m[96:128], "misc A/B written:")
    if len(sys.argv) > 2:
        decode_ab(pathlib.Path(sys.argv[2]).read_bytes(), "misc A/B now:")


if __name__ == "__main__":
    main()