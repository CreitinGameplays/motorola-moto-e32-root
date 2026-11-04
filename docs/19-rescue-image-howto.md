# 19 - The boot_a rescue image: building, flashing, and using it


Shells: build steps are bash on the build machine; device steps are bash
(Git Bash on Windows) with `export MSYS2_ARG_CONV_EXCL="*"` - see README
"Shell conventions".
The `boot_a` rescue is the safety net that makes every `boot_b` kernel
experiment recoverable with one power press. This page is the complete
how-to: build it, flash it to `boot_a`, verify it, and use it when a test
kernel hangs. The design rationale is in
[12](12-slot-b-testing-channel.md).

## What it is

A 64 MiB Android boot image that boots on the **stock kernel** (it
reuses the stock kernel + dtb) with a minimal initramfs whose `/init`
(static aarch64, freestanding, ~6 KB) does exactly one thing:

- **restore build**: rewrite `boot_b` from an embedded blob of the stock
  image, write the AVB footer, set the A/B block back to the known-good
  steady state (`_b`, slot a prio 14, slot b prio 15, valid CRC), reboot.
  Result: Android is back on the stock kernel.
- **dry build**: same boot, but it only hashes the blob and writes a
  marker record - used once to prove the channel without touching
  `boot_b`.

Layout (offsets from the stock image):

```
[ANDROID! hdr][stock kernel][gzip cpio: /init + /blob/boot_b + /blob/footer][stock dtb]
[vbmeta AVB0, our key][zero pad][AVBf footer at 0x3ffffc0]
```

The verified rescue currently on the device (and the canonical build):
`boot_rescue_restore.img`, sha256
`fc3ca0efd6414d4f5d24c478b1592ea1ba9386f1476883a0bd8a1b8b1a3844c0`.

That exact blob is the one proven to boot and repair slot b, so the
repository copy in `artifacts/rescue/` **is** that blob. Note (2026-11-04):
the build is *not* bit-reproducible in practice - a rebuild on 2026-11-02
produced `750ebd0cbf6fc6e4f0cff098396fd4b10665ee059838fbcfde371559fe6f6753`
(kept as `artifacts/rescue/boot_rescue_restore_rebuild_750ebd0c.img`).
Until the source of the difference is pinned down, treat `fc3ca0ef...44c0`
as the only known-good rescue and verify the device copy against it; the
rebuild variant has *not* been boot-tested.

## 1. Build it

Prerequisites: the stock `boot_b` backup
(`D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\boot_b.img`,
`ccd0faff...7b18`), python3, and the AVB key (already in
`artifacts/kernel-build/avb-test-key.pem`).

```bash
# 1. build the static init (restore mode) - needs any clang with lld
clang --target=aarch64-linux-gnu -O2 -ffreestanding -nostdlib -static \
      -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables \
      -mgeneral-regs-only -fuse-ld=lld -Wl,-e,_start -DRESCUE_RESTORE \
      -o artifacts/rescue/rescue_init_restore scripts/rescue/rescue_init.c
# (or: bash scripts/rescue/build_init.sh)

# 2. pack + sign (embeds the stock boot_b blob and footer)
python scripts/host/build_rescue.py restore artifacts/rescue/boot_rescue_restore.img
```

`build_rescue.py` prints the blob/footer hashes it embedded and the
final image hash - compare with the canonical values above.  The build
is **not** bit-reproducible as of 2026-11-04 (a rebuild produced
`750ebd0c...6753` instead of `fc3ca0ef...44c0`), so a hash mismatch does
not automatically mean a broken build - but do **not** flash a variant
that has not been boot-tested: the boot-tested blob is the one shipped
in `artifacts/rescue/boot_rescue_restore.img`.

Sanity checks the script performs itself: 64 MiB geometry, `ANDROID!`
magic, footer offset `0x3ffffc0`, marker constants verified at runtime by
the init itself.

## 2. Flash it to boot_a

**Never use `fastboot flash boot_a`** - same download gate as `boot_b`;
it fails with `Please verify the signature!`. The working way is `dd`
from a rooted Android (Magisk `su` or the runtime exploit on the stock
kernel):

```bash
# stage and hash-verify
adb push artifacts/rescue/boot_rescue_restore.img /data/local/tmp/boot_rescue_restore.img
adb shell "su -c 'sha256sum /data/local/tmp/boot_rescue_restore.img'"
#   must be fc3ca0ef...44c0

# write boot_a and read back the whole partition
adb shell "su -c 'dd if=/data/local/tmp/boot_rescue_restore.img \
    of=/dev/block/by-name/boot_a bs=1M && sync && \
    sha256sum /dev/block/by-name/boot_a'"
#   must be fc3ca0ef...44c0 again
```

There is also the older helper `scripts/device/write_boot_a.sh` (takes
the staged image path; uses the runtime exploit for root, so stock-kernel
only) - the inline `su -c` above is the current preferred form because it
also works with Magisk root.

**Safety rule:** `boot_a` is the only thing standing between a hung test
kernel and a BROM session. Verify the read-back hash every time, and
never write anything else there.

## 3. Verify the A/B state before relying on it

The rescue only ever runs when the bootloader picks slot a, so keep the
A/B block in the steady state (`_b`, slot a priority 14, tries 0,
successful 1):

```bash
adb shell "su -c 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 | od -An -tx1'"
# 5f 62 00 00 42 43 41 42 01 02 00 00 8e 00 9f 00
# ... 53 6d d6 a3   (crc)     steady state
```

## 4. Use it: recovery from a hung boot_b kernel

Every `boot_b` test is flashed with slot b at **one** attempt
(`scripts/device/set_slot_b_tries1.sh`, verified read-back
`AB_TRIES1_OK`). If the test kernel hangs:

1. Hold **Power ~15 s** and release (one power cycle, no key combo).
2. The SPL finds slot b's attempt spent -> picks slot a -> the rescue
   runs: it rewrites stock `boot_b`, restores the A/B block, reboots.
3. Android is back on the stock kernel in ~2-3 min. adb appears around
   t+170 s from the power press.

Then re-apply Magisk if you need root back on the stock boot:
`scripts/host/restore_magisk_after_rescue.ps1` (stages the known-good
Magisk `boot_b`, arms the one-attempt marker, reboots).

Only if the phone shows **no logo, no backlight** and enumerates as
`1782:4D00` (the SPL itself failed, or the rescue is unreachable) is
BootROM needed: [14](14-brom-recovery-runbook.md).

## 5. When boot_a itself must be re-flashed

Cases: the rescue image is missing/corrupted (read-back hash differs),
or you deliberately want the newer build. That is exactly section 2.
After writing, boot it once deliberately to prove it (the cost is one
boot cycle: `fastboot set_active a` from the bootloader, or
`scripts/host/brom_set_slot.ps1 -Slot a -ConfirmWrite` from BootROM),
then confirm the marker and that Android returned on `_b`.

## Reference

- Design, dry runs, and the restore test:
  [12](12-slot-b-testing-channel.md)
- The init source: `scripts/rescue/rescue_init.c`
- Builder: `scripts/host/build_rescue.py`
- BootROM fallback: [13](13-recovery-bootrom.md) /
  [14](14-brom-recovery-runbook.md)
