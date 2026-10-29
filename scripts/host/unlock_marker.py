#!/usr/bin/env python3
"""Mint and flash the ``VerifiedBoot-UNLOCK`` marker (see docs/06).

Pipeline (all inferred from the U-Boot/TrustOS reversing in docs/06):

1. root the device with the runtime exploit (``scripts/mali/mali_kroot.c``),
2. pin a scratch page below 4 GiB with ``scripts/device/sip_page``,
3. build a grafted module that calls SIP op ``0x31`` on that page,
4. read the 64-byte marker the secure world writes back,
5. verify it with op ``0x33`` (status byte at ``+0x40`` must be 1),
6. optionally write the 64 bytes to ``miscdata`` offset ``0x2000``.

Every ``adb shell`` is a fresh process and root is per-process, so the device
side of each step runs as one shell invocation that re-roots first.

Prerequisites (once):

    # host: build and push the helpers
    python scripts/host/build_sip_ko.py --help      # sanity check
    $NDK/toolchains/llvm/prebuilt/*/bin/clang \\
        --target=aarch64-linux-android21 -O2 \\
        -o artifacts/sip_page scripts/device/sip_page.c
    adb push artifacts/sip_page /data/local/tmp/sip_page
    adb push artifacts/mali_kroot /data/local/tmp/mali_kroot

Usage:

    python scripts/host/unlock_marker.py             # dry run, keeps marker.bin
    python scripts/host/unlock_marker.py --flash     # write miscdata + sync

``--flash`` is destructive only in the sense that it changes the boot policy of
the device: /data must then be wiped once (recovery is enough) because it was
created under the previous verified-boot state.
"""

import argparse
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADB = "adb"
PAGE_OFF = 0xFFFFFFC000000000      # arm64 39-bit linear map base
MEMSTART = 0x80000000              # memstart_addr, printed by mali_kroot
RAM_HI = 0x100000000               # SIP buffer field is 32-bit

ROOT_LOOP = (
    'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1; '
    '[ "$(id -u)" = 0 ] && break; done; '
    '[ "$(id -u)" = 0 ] || { echo NOROOT; exit 1; }; '
)


def sh(cmd, timeout=600):
    proc = subprocess.run([ADB, "shell", cmd], capture_output=True, text=True,
                          timeout=timeout)
    return (proc.stdout or "") + (proc.stderr or "")


def host(*args, **kwargs):
    proc = subprocess.run(list(args), capture_output=True, text=True, **kwargs)
    sys.stdout.write(proc.stdout or "")
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "")
        raise SystemExit("%s failed (%d)" % (args[0], proc.returncode))
    return proc


def pin_page(arena="/data/local/tmp/siparena.bin", log="/data/local/tmp/sippage.log"):
    sh("rm -f %s %s; pkill -f sip_page 2>/dev/null" % (arena, log))
    sh(ROOT_LOOP + "nohup /data/local/tmp/sip_page %s VerifiedBoot-UNLOCK "
                   "> %s 2>&1 &" % (arena, log))
    # sip_page maps 64 MB chunks until one contains a page below 4 GiB; that
    # takes a few seconds of memory pressure, so poll the log instead of
    # sleeping a fixed amount.
    for _ in range(60):
        out = sh(ROOT_LOOP + "tail -2 %s" % log)
        m = re.search(r"IDX=(\d+) CHUNK=\d+ VA=\S+ PA=(\w+)", out)
        if m:
            idx = int(m.group(1))
            pa = int(m.group(2), 16)
            break
        if "no page below 4 GiB" in out:
            raise SystemExit("sip_page found no low page: " + out)
        subprocess.run([sys.executable, "-c", "import time; time.sleep(1.5)"],
                       check=False)
    else:
        raise SystemExit("sip_page did not report a page: " + out)

    if pa % 4096 or not (MEMSTART <= pa < RAM_HI):
        raise SystemExit("bad PA 0x%x (must be aligned, below 4 GiB)" % pa)
    va = PAGE_OFF + (pa - MEMSTART)
    print("[+] scratch: IDX=%d PA=0x%x VA=0x%x" % (idx, pa, va))
    return arena, idx, pa, va


def build(op, pa, va, length, name, out, extra=()):
    host(sys.executable, str(ROOT / "scripts/host/build_sip_ko.py"),
         "--out", str(out), "--op", hex(op), "--pa", hex(pa),
         "--va", hex(va), "--len", hex(length), "--name", name, *extra)
    host(ADB, "push", str(out), "/data/local/tmp/%s.ko" % name)


def load_module(name, arena, idx, payload=None, count=64):
    """Load a module and return the scratch page it worked on.

    ``payload`` is written back into the scratch buffer first, so every trial
    starts from the same plaintext.
    """
    cmd = ""
    if payload is not None:
        cmd += ("dd if=/data/local/tmp/%s of=%s bs=1 seek=%d count=%d "
                "conv=notrunc 2>/dev/null; " % (payload, arena, idx * 4096,
                                                count))
    cmd += "insmod /data/local/tmp/%s.ko" % name
    sh(ROOT_LOOP + cmd)


def read_page(arena, idx, name="page.bin"):
    local = ROOT / "artifacts" / name
    sh(ROOT_LOOP + "dd if=%s bs=4096 skip=%d count=1 of=/data/local/tmp/%s "
                   "2>/dev/null; chmod 644 /data/local/tmp/%s"
       % (arena, idx, name, name))
    host(ADB, "pull", "/data/local/tmp/%s" % name, str(local))
    return local.read_bytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flash", action="store_true",
                    help="write the marker to miscdata 0x2000 and sync")
    args = ap.parse_args()

    dev_plain = ROOT / "artifacts/sipplain.bin"
    if not dev_plain.exists():
        dev_plain.write_bytes(b"VerifiedBoot-UNLOCK".ljust(64, b"\0"))
    host(ADB, "push", str(dev_plain), "/data/local/tmp/sipplain.bin")

    arena, idx, pa, va = pin_page()

    # 1. sign: op 0x31 needs len >= 0x80 to pass the "sprdsec" mapper, and the
    #    first 64 output bytes are the marker (AES-CBC, plaintext is fixed).
    #    The first map of a boot fails with -14 (EFAULT) whatever the
    #    operation is, so retry until the SMC itself reports success.
    plaintext = b"VerifiedBoot-UNLOCK".ljust(64, b"\0")
    marker = None
    for attempt in range(4):
        name = "sip31_%d" % attempt
        build(0x31, pa, va, 0x80, name, ROOT / ("artifacts/%s.ko" % name),
              ("--dcache",))
        load_module(name, arena, idx, "sipplain.bin", 64)
        page = read_page(arena, idx, "signed%d.bin" % attempt)
        rc = int.from_bytes(page[0x40:0x44], "little", signed=True)
        print("[*] op 0x31 attempt %d -> rc=%d" % (attempt, rc))
        if rc == 0 and page[:64] != plaintext:
            marker = page[:64]
            break
    if marker is None:
        raise SystemExit("op 0x31 never produced a marker")
    (ROOT / "artifacts/marker.bin").write_bytes(marker)
    print("[+] marker:", marker.hex(" "))

    # 2. verify exactly the way U-Boot does: 0x40 bytes in a 0x80 block, op
    #    0x33, status byte at +0x40.  The stub's return words are moved to
    #    +0xF0 so they do not clobber the status byte.
    block = ROOT / "artifacts/marker80.bin"
    block.write_bytes(marker + b"\0" * 64)
    host(ADB, "push", str(block), "/data/local/tmp/marker80.bin")
    status = None
    for attempt in range(4):
        name = "sip33_%d" % attempt
        build(0x33, pa, va, 0x80, name, ROOT / ("artifacts/%s.ko" % name),
              ("--dcache", "--ret-off", "0xF0"))
        load_module(name, arena, idx, "marker80.bin", 128)
        page = read_page(arena, idx, "verified%d.bin" % attempt)
        rc = int.from_bytes(page[0xF0:0xF4], "little", signed=True)
        print("[*] op 0x33 attempt %d -> rc=%d status=%d"
              % (attempt, rc, page[0x40]))
        if rc == 0:
            status = page[0x40]
            break
    if status != 1:
        raise SystemExit("secure world did not accept the marker (status %s)"
                         % status)

    sh(ROOT_LOOP + "pkill -f sip_page 2>/dev/null")
    print("[+] verified marker saved to artifacts/marker.bin")

    if not args.flash:
        print("[i] dry run: rerun with --flash to write miscdata 0x2000")
        return

    host(ADB, "push", str(ROOT / "artifacts/marker.bin"),
         "/data/local/tmp/marker.bin")
    out = sh(ROOT_LOOP +
             "dd if=/data/local/tmp/marker.bin of=/dev/block/by-name/miscdata "
             "bs=1 seek=8192 count=64 conv=notrunc && sync && "
             "dd if=/dev/block/by-name/miscdata bs=1 skip=8192 count=64 "
             "2>/dev/null | md5sum")
    print(out.strip())
    print("[+] miscdata 0x2000 written; wipe /data once, then reboot")


if __name__ == "__main__":
    main()
