# 12 - Making slot_b usable: the boot_a rescue image

Status: **done - the boot_a rescue works in both modes (dry handoff and full
restore), verified on the device.** It is now the safety net for kernel tests
in `boot_b`. Evidence:
[evidence/2026-10-30-rescue-dry1-bootloop.txt](evidence/2026-10-30-rescue-dry1-bootloop.txt).
Evidence: [evidence/2026-10-30-channel-research.txt](evidence/2026-10-30-channel-research.txt).

## Why

Every custom-kernel test so far ran from `boot_a`. That was the only safe
slot, but slot `a` has no userspace: `super` contains only the `_b` logical
partitions, so a kernel booted from `boot_a` can never reach Android. All the
data we want (does KVM come up, do drivers probe, does userspace start) lives
on the other side of that gap.

The kernel that *does* get a userspace can only come from `boot_b`, because
the bootloader derives both "which boot partition" and
`androidboot.slot_suffix` from the same A/B metadata block. The cmdline
cannot override it (the bootloader discards our cmdline).

So the question is not "how do we write `boot_b`" - root can `dd` it today -
but **how do we get back if the image in `boot_b` hangs**, given that
`fastboot flash` is gated shut and a hang never resets the SoC by itself.

Answer: put a guaranteed, self-contained rescue in `boot_a`.

## Design

`boot_a` becomes an image that can only ever do one thing: restore
`boot_b` from a copy stored inside its own initramfs, set the active slot
back to `_b`, and reboot. It carries everything it needs, so it does not
depend on `/cache`, `/data`, the filesystem, or even Android being intact.

```
boot_a (64 MiB partition)
  [ANDROID! hdr 2048]
  kernel       = stock kernel from boot_b          25,358,352 B
  ramdisk      = uncompressed cpio (~34.80 MB)
                   /init          static aarch64, raw syscalls
                   /blob/boot_b   stock boot_b[0 : 0x211d000+2304]
                   /blob/footer   stock AVBf (64 B, from 0x3ffffc0)
                   /blob/ab       A/B block: suffix "_b", CRC fixed
  dtb          = stock dtb                            175,466 B
  [vbmeta AVB0, our key]
  [zero pad to 0x3ffffc0]
  [AVBf footer at partition end]
```

Budget: `2048 + 25,358,352 + ~34,800,000 + 175,466 + 2304 = ~60.33 MB`
against 67,108,864 B - about 6.7 MB of padding left. Tight but valid.

Size could be halved by storing the blob in `/cache` instead
(ext4 is built in), but then a cache wipe silently removes the only way
back. The blob is only the 34.79 MB *used extent* of the stock image; the
remaining 32.3 MB are zeros and are regenerated at restore time.

## Rescue `/init`

1. `mknod` `/dev/boot_b` (block, 259:26) and `/dev/misc` (block, 8:4) -
   `CONFIG_DEVTMPFS` is not set, so nothing creates these for us.
2. Write `/blob/boot_b` verbatim to `boot_b` (34,789,632 B).
3. Write zeros up to offset `0x3ffffc0`, then `/blob/footer` (64 B).
   Result is byte-identical to the stock backup at
   `D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\boot_b.img`.
4. Zero `misc+0..32` (clears the stale `bootonce-bootloader` command) and
   write the known-good A/B block at `misc+0x800`: suffix `_b`, slot a
   priority 14, **slot b priority 15** (`0x00ef`), CRC32 over bytes 0..27.
   The slot is chosen by *priority*; patching the suffix alone does nothing
   (dry run #1 boot-looped exactly this way).
5. `reboot(LINUX_REBOOT_CMD_RESTART)`.

No mount, no shell, no console, no parameters. Binary is `-nostdlib
-static`, a few KB.

## Recovery procedure once this exists

```
test kernel hangs on slot b
power-cycle -> hold Vol Down -> fastboot
fastboot set_active a      # boots the rescue
# rescue restores stock boot_b, sets _b, reboots
# device is back on Android
```

No PC-side flash, no BootROM keys, no FDL variant risk.

## Why this unblocks the KVM work

Custom kernels are then written to `boot_b`, which boots with
`androidboot.slot_suffix=_b`, the `_b` vendor ramdisk and the `_b` system/
vendor/product partitions - i.e. the real userspace. That is what the
previous experiments could never reach.

## Rollout (each step needs approval before writing to the device)

1. Build the static init + cpio + avb-signed image; verify the 64 MiB
   geometry and footer offsets offline.
2. `dd` it to `boot_a` (test channel, already replaced many times), read
   back and compare sha256.
3. `set_active a`, boot the rescue **with the restore step disabled first**
   (a dry-run build that only prints nothing / hashes the blob and reboots
   to `_b`). This proves the initramfs runs on the stock kernel without
   touching `boot_b`.
4. Enable the restore, boot it, verify `boot_b` readback == stock backup
   sha256 and that the device returns to Android on `_b`.
5. Only then start writing test kernels to `boot_b`.

## Dry run #1 (2026-10-30): bootloop

`boot_rescue_dry.img` (`40cdc04e...727c`) was `dd`-ed to `boot_a`, read back
byte-identical, and `set_active a` used to boot it. The phone then rebooted
every few seconds forever: no adb, no fastboot, no userspace. `boot_b` was
untouched (dry build).

Cause: the init patched only the `slot_suffix` bytes of the A/B block. This
bootloader selects the slot by **priority** in the same 32-byte block
(`slot_info[0]` = slot a, `slot_info[1]` = slot b, u16 with
`priority:4/tries:3/successful:1/verity:1`), and `slot_suffix` is only the
bootloader's report of what it booted. `set_active a` had left slot a at
priority 15, so every reboot booted the rescue again.
[Full evidence](evidence/2026-10-30-rescue-dry1-bootloop.txt).

Fix: the init now writes the whole known-good 32-byte block (slot b priority
15, slot a 14, suffix `_b`, crc32 `0x49b9de16`), verifies the constant's CRC
at runtime and reads the block back. It also writes marker status 99 right
after creating the device nodes, so the next run can tell "init never ran"
from "init ran, handoff ignored".

The recorded marker proved the rescue itself is sound (status 11; the
embedded 34.79 MB blob and footer hash-match the host-side stock bytes; the
`misc` write was verified), and that `fastboot set_active` merely *swaps* the
two `slot_info` records. The block the fixed init writes is byte-identical to
what `set_active b` leaves behind, re-read from the device after recovery.

## Dry run #2: passed (2026-10-30)

`boot_rescue_dry2.img` (`f46ded7b...672c`) was `dd`-ed to `boot_a` (readback
identical, `boot_b` still `ccd0faff...7b18`), then `set_active a`. Result:

```
t+34 s  sys.boot_completed = 1, ro.boot.slot_suffix = _b
marker  DRESCUE1 status 11 (dry), blob/footer hashes exact
misc before: "_a"  a=0x00ef (prio 15)  b=0x008e (prio 14)
misc after:  "_b"  a=0x008e (prio 14)  b=0x00ef (prio 15)  crc 0x49b9de16
```

The rescue runs on slot `a`, rewrites the whole A/B block, reboots, and the
bootloader picks slot `b` - Android userspace, on the stock `boot_b`. This is
the handoff the whole channel depends on, and it is now proven.

Recovery from here is unchanged and did not need the key combo: the loop never
happened, because the handoff works.

## Restore test: passed (2026-10-30)

`boot_rescue_restore.img` (`fc3ca0ef...44c0`) was `dd`-ed to `boot_a` and
booted with `set_active a`. The init rewrote the whole 64 MiB `boot_b` from
its embedded copy, padded with zeros, wrote the footer, verified the **entire
partition** by FNV-1a readback, wrote the A/B block, and rebooted:

```
marker  DRESCUE1 mode 1 (restore) status 2 (OK)
        blob size 34724096, blob/footer hashes exact,
        readback hash 0xe00219676ca740d7 == expected
boot_b  sha256 ccd0faff...7b18  (unchanged, byte-identical to stock)
boot_a  sha256 fc3ca0ef...44c0  (the restore rescue)
slot    _b, Android up after 40 s
```

So the full round trip is proven: `boot_b` can be rewritten by a `boot_a`
rescue without fastboot, `/cache`, `/data` or the filesystem, and the device
returns to Android on `_b`.

## Risks

* The initramfs is large (34.8 MB uncompressed); if the bootloader or kernel
  dislikes it, step 3 fails safely on `boot_a` and we fall back to the
  current state.
* The A/B CRC was reverse-engineered from one sample and validated against
  it; the rescue writes the *same* block with only the suffix changed, so a
  decode error would show up in step 3 (device must reboot into `_b`).
* If `boot_b` is corrupted *and* `/cache` is wiped, `boot_a` still works -
  that is the point of keeping the blob inside the image.
* Unisoc BROM/FDL remains the fallback if `boot_a` itself is ever lost.