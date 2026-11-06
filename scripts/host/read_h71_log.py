#!/usr/bin/env python3
"""Read the 7.1 test-kernel boot logs that logsave/the rescue wrote to
sysdumpdb.

Two independent zones live in the sysdumpdb partition (10 MiB):

    +0x100000  H71LOG01  logsave /init dump of the whole kernel ring
              +0x200000          (backup copy)   - scripts/host/logsave.c
    +0x400000  H71RING1  the rescue's copy of the PREVIOUS kernel's
                          pstore console ring   - scripts/rescue/
                          rescue_init.c save_pstore_ring()
    +0x800000  H71DTB01  the merged DTB exactly as the kernel consumed
                          it (LK dtbo merge output, read back from
                          /sys/firmware/fdt)   - scripts/host/logsave.c

All headers: [ 8-byte magic ][ u32 big-endian size ][ payload ].

Usage:
    python scripts/host/read_h71_log.py [outdir]

    outdir defaults to docs/evidence; files are written as
    <date>-7.1-boot-log.txt (H71LOG01) and <date>-7.1-ring.txt (H71RING1).

The adb binary is taken from $ADB, then PATH (same convention as
kexec_test.py). Needs the phone in Android with root (su).
"""
import datetime
import os
import pathlib
import subprocess
import sys

ADB = os.environ.get("ADB", "adb")
OFF_PRIMARY = 0x100000          # H71LOG01 (logsave)
OFF_BACKUP = 0x200000           # H71LOG01 backup copy
OFF_RING = 0x400000            # H71RING1 (rescue pstore capture)
OFF_DTB = 0x800000             # H71DTB01 (merged DTB capture)
CHUNK = 1 << 20


def su_read(cmd):
    """Run a root read command via adb exec-out and return raw bytes."""
    env = dict(os.environ)
    env["MSYS2_ARG_CONV_EXCL"] = "*"
    p = subprocess.run([ADB, "exec-out", "su -c '%s'" % cmd],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env=env)
    return p.stdout, p.stderr.decode("utf-8", "replace"), p.returncode


def parse(blob, off, magic):
    """Return the payload at `off` inside `blob`, or None."""
    hdr = blob[off:off + 16]
    if len(hdr) < 16 or hdr[:8] != magic:
        return None
    length = int.from_bytes(hdr[8:12], "big")
    if length <= 0 or off + 16 + length > len(blob):
        return None
    return blob[off + 16:off + 16 + length]


def main():
    outdir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        pathlib.Path(__file__).resolve().parents[2] / "docs" / "evidence")
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today()
    found = 0

    # 4 MiB from +1 MiB covers every zone (+1M .. +5M)
    data, err, rc = su_read(
        "dd if=/dev/block/by-name/sysdumpdb bs=%d skip=%d count=4"
        % (CHUNK, OFF_PRIMARY // CHUNK))
    if rc != 0 or len(data) < CHUNK:
        raise SystemExit("sysdumpdb read failed (rc=%d, %d bytes): %s"
                         % (rc, len(data), err.strip()))

    # the merged-DTB zone sits at +8 MiB (outside the window above)
    dtbdata, derr, drc = su_read(
        "dd if=/dev/block/by-name/sysdumpdb bs=%d skip=%d count=2"
        % (CHUNK, OFF_DTB // CHUNK))

    for name, magic, off in (
            ("7.1-boot-log", b"H71LOG01", 0),
            ("7.1-boot-log-backup", b"H71LOG01", OFF_BACKUP - OFF_PRIMARY),
            ("7.1-ring", b"H71RING1", OFF_RING - OFF_PRIMARY)):
        ring = parse(data, off, magic)
        if ring is None:
            continue
        found += 1
        out = outdir / ("%s-%s.txt" % (stamp, name))
        out.write_text(ring.decode("utf-8", "replace"),
                       encoding="utf-8", errors="replace")
        print("wrote %s (%d bytes)" % (out, len(ring)))
        lines = [ln for ln in ring.decode("utf-8", "replace").splitlines()
                 if ln.strip()]
        print("===== %s: last 30 lines =====" % name)
        for ln in lines[-30:]:
            print(ln)
        print()

    if not found:
        # show what IS there so wrong magic/format is diagnosable
        preview = data[:64].hex()
        raise SystemExit("no H71LOG01/H71RING1 marker at +0x%x, +0x%x "
                         "or +0x%x\nfirst 64 bytes at +0x%x: %s"
                         % (OFF_PRIMARY, OFF_BACKUP, OFF_RING,
                            OFF_PRIMARY, preview))

    # the merged DTB: raw blob for dtb_surgery.py / dtc analysis
    if drc == 0 and len(dtbdata) >= CHUNK:
        dtb = parse(dtbdata, 0, b"H71DTB01")
        if dtb is not None:
            out = outdir / ("%s-7.1-merged.dtb" % stamp)
            out.write_bytes(dtb)
            print("wrote %s (%d bytes) - analyze with "
                  "scripts/host/dtb_surgery.py info/get" % (out, len(dtb)))
        else:
            print("no H71DTB01 marker at +0x%x (old logsave build?)"
                  % OFF_DTB)

    print("%d log zone(s) recovered" % found)


if __name__ == "__main__":
    main()
