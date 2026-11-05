# 19 - The boot_a rescue image: the friendly flashing & recovery guide

> **New here?** This page is written so you can follow it top to bottom
> even if you have never flashed a partition by hand. It explains what
> the rescue image is, why it exists, the exact commands that put it on
> the phone, how to *prove* it works before you depend on it, and what
> to do when a test kernel hangs. If you only want the commands, jump
> to the [TL;DR cheat sheet](#tldr-cheat-sheet) at the end.

Shells: host steps are bash (Git Bash on Windows) with
`export MSYS2_ARG_CONV_EXCL="*"` set once per shell - see the README
"Shell conventions" section. Nothing on this page needs fastboot; in
fact fastboot flashing is exactly what does **not** work here (why, in
a moment).

## 1. The big picture: why boot_a is sacred

All kernel experiments on this phone run from `boot_b`, because only
slot `_b` has a userspace (`super` holds only the `_b` logical
partitions). The problem: the bootloader's fastboot *download* gate
rejects every flash request - even byte-identical stock images - with
`Please verify the signature!` (fully decoded in
[11](11-flash-gate.md)). So `boot_b` can only be written with a raw
`dd` from a rooted Android, and **there is no fastboot way back** if
the image you wrote hangs.

That is where the A/B slot machinery saves us. The bootloader picks a
slot by *priority* from a 32-byte metadata block in `misc`
(+0x800), decrements the slot's `tries_remaining` on each attempt, and
falls back to the other slot when the active one is spent. So we keep
a tiny, self-contained **rescue image in `boot_a`** whose only job is:

1. rewrite `boot_b` from a copy of the stock image *embedded inside
   itself*,
2. put the A/B metadata block back to the known-good `_b` state,
3. reboot.

The result: a hung test kernel costs **one long power press** and
about three minutes - no PC-side flashing, no BootROM session, no
`/data` or `/cache` needed (the rescue never mounts them; it carries
everything in its own initramfs).

Because `boot_a` is the only thing standing between a hung kernel and
a much more painful recovery, it gets exactly one image - the verified
rescue - and nothing else, ever.

## 2. Meet the rescue image

It is a normal-looking 64 MiB Android boot image built around the
**stock kernel and stock dtb**, with one difference: the ramdisk is a
minimal cpio containing a freestanding static-aarch64 `/init` (a few
KB, raw syscalls, no libc) and a `blob/` directory holding the stock
`boot_b` payload (34,789,632 B) plus its 64-byte AVB footer.

```
boot_a (64 MiB partition)
  [ANDROID! hdr 2048]
  kernel       = stock kernel from boot_b          25,358,352 B
  ramdisk      = gzip cpio (~19.4 MB compressed, ~34.8 MB unpacked)
                   /init          the rescue binary (this file does everything)
                   /blob/boot_b   stock boot_b[0 : 0x211d900]   <- the restore source
                   /blob/footer   stock AVBf footer (64 B)
  dtb          = stock dtb                            175,466 B
  [vbmeta AVB0, throwaway key] [zero pad]
  [AVBf footer at 0x3ffffc0, partition end]
```

Two build modes exist (same image otherwise):

* **restore** - the real thing: rewrites `boot_b` from the blob,
  zero-pads to the footer offset, writes the footer, verifies the whole
  partition by hash, sets the A/B block to the known-good steady
  state, reboots. Android is back on the stock kernel.
* **dry** - the rehearsal: hashes the blob, writes its status marker,
  sets the A/B block, reboots - but **never touches `boot_b`**. Used
  to prove a newly built rescue actually runs before you trust it.

### What the v3 rescue adds (and why)

Before restoring, the v3 `/init` mounts `pstore` and copies the
*previous* kernel's console ring (`console-ramoops-0`) to
`sysdumpdb + 4 MiB` under the magic `H71RING1`. That ring is readable
exactly once - at the rescue kernel's pstore probe - and our own boot
output overwrites it within seconds if nobody saves it. So when a hung
test kernel warm-resets into the rescue, its last words survive, and
`scripts/host/read_h71_log.py` can read them later from Android.
Failure-tolerant by design: if anything in the save fails, the restore
still runs.

### The known images

| image (repo copy) | sha256 | status |
|---|---|---|
| `artifacts/rescue/boot_rescue_restore_v3.img` | `46519e13b79cf532880f6ee080cc69b3859ea32195c393dda7a9742170c23a87` | **live on boot_a since 2026-11-05**; performed real recoveries |
| `artifacts/rescue/boot_rescue_dry_v3.img` | `aea008b05281979165d70e3549a55b75b63d4b03e2949560663e545133c0c278` | v3 dry-run; proved the v3 channel (2026-11-05) |
| `artifacts/rescue/boot_rescue_restore.img` | `fc3ca0efd6414d4f5d24c478b1592ea1ba9386f1476883a0bd8a1b8b1a3844c0` | v2 restore; boot-tested 2026-10-30; live before v3 |
| `artifacts/rescue/boot_rescue_restore_rebuild_750ebd0c.img` | `750ebd0c...6753` | v2 **rebuild, never boot-tested - do not flash** |

Note: the build is *not* bit-reproducible (the v2 rebuild above came
out different for reasons still unpinned), so **the only rescue you
may flash is one that has been boot-tested on this device**. A freshly
built image must first pass the dry-run proof (section 5.3) and a
restore proof before it becomes the live rescue.

## 3. Before you start

Checklist - all of these are required:

- [ ] The phone is in Android (adb up), on slot `_b`, with root:
      `adb shell "su -c 'id -u'"` prints `0`. (No Magisk? On the stock
      kernel `/data/local/tmp/mali_kroot` also works - but remember it
      leaves SELinux Permissive until the next reboot, so never use it
      on a boot where a Play Integrity verdict matters.)
- [ ] The rescue image file on the host, with its expected sha256 from
      the table above.
- [ ] Git Bash with `export MSYS2_ARG_CONV_EXCL="*"` (or PowerShell -
      the raw commands below are bash).
- [ ] ~2 minutes of patience and a charged phone.

The golden rules, up front:

1. `boot_a` gets **one** image: the verified rescue. Nothing else,
   ever.
2. **Hash-verify everything**: the staged file *before* the write, the
   whole partition *after*. No exceptions.
3. Never `fastboot flash boot_a` - the download gate rejects it anyway
   (`Please verify the signature!`); `dd` from root is the only way.
4. Never flash a rescue build that has not been boot-tested (dry first,
   then restore - see section 5.3).
5. Keep the A/B block in the known-good steady state before relying on
   the fallback (check it - section 5.2).

## 4. Flash the rescue to boot_a, step by step

The whole procedure is four commands and one read-back check. It never
touches `boot_b`.

### 4.1 Confirm where you are

```bash
adb devices                       # phone listed as "device"
adb shell getprop ro.boot.slot_suffix   # _b  (the running slot)
adb shell "su -c 'id -u'"         # 0  (root available)
```

### 4.2 Push the image and verify it landed intact

```bash
adb push artifacts/rescue/boot_rescue_restore_v3.img /data/local/tmp/rescue.img
adb shell "su -c 'sha256sum /data/local/tmp/rescue.img'"
# must print 46519e13b79cf532880f6ee080cc69b3859ea32195c393dda7a9742170c23a87
```

Why the on-device hash: adb push over a flaky cable can truncate. If
the hash differs, do not continue - re-push. Never write an unverified
file to `boot_a`.

### 4.3 Write it to boot_a and read the whole partition back

```bash
adb shell "su -c 'dd if=/data/local/tmp/rescue.img \
    of=/dev/block/by-name/boot_a bs=1M && sync && \
    sha256sum /dev/block/by-name/boot_a'"
# must print 46519e13b79cf532880f6ee080cc69b3859ea32195c393dda7a9742170c23a87
```

What happens here:

- `dd` copies the full 64 MiB over the partition (`bs=1M` = 64 blocks,
  fast);
- `sync` flushes the UFS write cache - **do not skip it**;
- `sha256sum` then reads the *entire partition back from flash*. The
  rescue is useless if any byte is wrong, so a partial check is not
  good enough. The hash must equal the image hash exactly.

If the read-back differs: re-push (step 4.2) and `dd` again. The
running system is not affected by a bad `boot_a` (you are booted from
`_b`), but the safety net is gone until the hashes match - do not
reboot into any test with an unverified `boot_a`.

### 4.4 Clean up the staging file

```bash
adb shell "su -c 'rm /data/local/tmp/rescue.img'"
```

`/data/local/tmp` stays lean (64 MB of staging junk adds up, and the
rescue copy on the host + `boot_a` are the canonical copies now).

### 4.5 Alternative helpers

- `scripts/device/write_boot_a.sh <staged-path>` - the older on-device
  wrapper; it elevates with `mali_kroot`, so it only works on the
  stock kernel. The inline `su -c` above is preferred (works with
  Magisk root on any kernel).
- `scripts/host/run_boot_b_test.ps1` refuses to start any `boot_b`
  test unless `boot_a` reads back the verified v3 rescue hash
  (`46519e13...`) - so if you forget to check, the test runner checks
  for you.

## 5. After flashing: verify before you rely on it

### 5.1 The rescue's own black box

Every rescue run writes a 128-byte `DRESCUE1` status record at
`sysdumpdb + 0x900000` (offset 9,437,184) - even a *failed* run
records how far it got. From a rooted Android:

```bash
adb exec-out "su -c 'dd if=/dev/block/by-name/sysdumpdb bs=1 skip=9437184 count=128'" > marker.bin
python scripts/host/decode_rescue_marker.py marker.bin
```

(or pull the whole forensic trail - marker, A/B block, BCB, pstore -
with `scripts/device/rescue_forensics.sh` on a stock-kernel boot, and
decode `marker.bin` + `ab32.bin` together.)

Status codes worth knowing:

| status | meaning |
|---|---|
| 99 | `/init` started (device nodes created) - the rescue kernel really ran |
| 1  | restore started |
| 2  | **restore OK** - boot_b rewritten, footer written, whole partition verified, A/B block set |
| 3  | restore FAILED - see the `extra`/hash fields |
| 10 | dry: blob hashed OK |
| 11 | dry: A/B block written and read back OK - the "channel proven" code |
| 12 | dry: A/B write failed (`extra` = negative errno) |
| 90-96 | the init ran but the blob/copy/footer step failed (90 blob unreadable, 93 open boot_b failed, 94 copy mismatch, 95/96 pad or footer write failed) |

The record also captures the A/B block *before* and *after* the run -
the single most useful debug field when a slot behaves unexpectedly.

### 5.2 Check the A/B steady state

The rescue only runs when the bootloader picks slot `a`, so the rest
of the time keep the metadata block in the known-good `_b` steady
state:

```bash
adb shell "su -c 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 | od -An -tx1'"
```

Expected (one of the two observed good states):

```
5f 62 00 00 42 43 41 42 01 02 00 00 8e 00 9f 00
00 00 00 00 00 00 00 00 00 00 00 00 53 6d d6 a3      (crc, slot b tries 1)
```

or the block the rescue itself writes (slot b `ef` = priority 15,
tries 6, successful 1, crc `16 de b9 49`). What matters: suffix
`5f 62` = `_b`, slot a `8e` (priority 14), slot b `9f`/`ef` (priority
15), and a CRC that the decoder validates. If you see `_a` in byte
0-1 or slot a at priority 15, something is off - decode the marker
before trusting the fallback.

### 5.3 Prove it: boot the rescue deliberately (recommended)

This is the same procedure used to qualify v3 on 2026-11-05, and it
costs one boot cycle. For a *new* build, always do the **dry** variant
first - it proves the image runs without touching `boot_b`.

1. Flash the dry (or restore) image as in section 4.
2. Flip the slot to `a` for one shot and warm-reboot:

   ```bash
   adb push scripts/device/set_slot_a_active.sh /data/local/tmp/set_slot_a_active.sh
   adb shell "su -c 'sh /data/local/tmp/set_slot_a_active.sh'"
   #   prints AB_SLOTA_OK only after reading the block back
   adb reboot
   ```

3. What you should see: normal logo, a short pause while the rescue
   runs (~10-30 s), then a reboot and Android coming back on `_b`.
   The dry round trip measured ~35 s; the restore variant ~40 s
   (plus the 34.8 MB write to `boot_b`).
4. Verify from Android:
   - decode the marker (section 5.1): dry = `status 11`, restore =
     `status 2`, mode `dry`/`restore` respectively;
   - dry build: `boot_b` hash **unchanged** (still whatever you had);
   - restore build: `boot_b` hash is now the stock
     `ccd0faff51ab24d921b2671c562f0fe08e7a1ba2b7f19bb93a5f2650eb4f7b18`;
   - v3 images: `python scripts/host/read_h71_log.py` finds the
     `H71RING1` zone (a stale ring from the previous boot, possibly
     empty on a clean warm reboot - the zone simply being present
     with a valid header is the proof).
5. Clean up: `adb shell "su -c 'rm /data/local/tmp/set_slot_a_active.sh'"`.

Only after a dry pass + a restore pass may the new image be called the
live rescue. (Alternative for step 2 when Android is not running:
`fastboot set_active a` from the bootloader menu also boots the
rescue - the helper above is just more convenient.)

## 6. When a boot_b test hangs: the recovery flow

Every `boot_b` test is flashed with slot b set to **one** attempt
(`scripts/device/set_slot_b_tries1.sh` prints `AB_TRIES1_OK`), so the
SPL falls back to slot `a` on any reset. When the test kernel hangs:

1. Hold **Power ~15 s** and release (one power cycle, no key combo).
   If the test kernel has its own boot watchdog (the 7.1 test builds
   arm a 150 s one), you may not even need this - the phone warm-resets
   itself and the fallback happens automatically.
2. The SPL finds slot b's attempt spent -> picks slot `a` -> the
   rescue runs: it saves the previous kernel's pstore ring (v3),
   rewrites stock `boot_b`, restores the A/B block, reboots.
3. Android is back on the stock kernel. adb usually reappears around
   **2-3 minutes** after the power press (measured: ~170 s in the
   simple case; the 7.1 flash tests with their 150 s boot watchdog
   took up to ~10 min total). The test runner
   (`run_boot_b_test.ps1 -WaitSeconds 900`) waits accordingly.

Then, from the returned Android:

- **Read the evidence** if the hung kernel left any: the rescue's
  `H71RING1` zone via `read_h71_log.py`, and `/sys/fs/pstore` (a warm
  reset preserves it, a cold power-hold does not).
- **Root**: the rescue restored *stock* `boot_b`, so Magisk is gone.
  Either use `mali_kroot` (works, but leaves SELinux Permissive until
  the next reboot - see the README's integrity warning), or bring the
  Magisk boot back for good:

  ```powershell
  .\scripts\host\restore_magisk_after_rescue.ps1
  ```

  It stages the known-good Magisk `boot_b`
  (`90416c09...cad3c`), arms the one-attempt fallback, reboots, and
  verifies `su` + SELinux `Enforcing` before returning.

Only if the phone shows **no logo, no backlight** and enumerates as
`1782:4D00` (the SPL itself failed, or the rescue is unreachable) is
BootROM needed: [14](14-brom-recovery-runbook.md). Do **not** flash a
pristine stock `misc.img` to fix slot metadata - stock marks slot b
successful at priority 15, which selects the broken kernel again.

## 7. Troubleshooting

| symptom | meaning / fix |
|---|---|
| `fastboot flash boot_a` -> `Please verify the signature!` | Expected. The gate is global and content-independent ([11](11-flash-gate.md)); the unlock marker does not open it. Use the `dd` flow in section 4. |
| staged hash != image hash after push | Bad push/cable. Re-push and re-verify; never `dd` an unverified file. |
| read-back hash != image hash after `dd` | Re-push and re-`dd` (with `sync` before hashing). If it persists, stop - the running system is fine (you are on `_b`), but do not run any `boot_b` test until `boot_a` verifies. |
| deliberate boot bootloops (logo, reset, repeat) | The historical priority trap: an A/B block that keeps selecting slot `a`. Current builds write the whole known-good block, so decode the marker - its before/after A/B fields show exactly what the init saw and wrote. Fix the block (section 5.2) to break the loop. |
| no `DRESCUE1` marker after a deliberate boot | The rescue `/init` never ran - bad/incompatible image, or the kernel died before init. Re-check the image hash and re-run the dry proof; if `boot_b` is also broken, that is the BootROM case ([14](14-brom-recovery-runbook.md)). |
| marker status 90-96 | The init ran but failed inside (blob unreadable, boot_b write failed, ...). `decode_rescue_marker.py` prints the meaning and the `extra` field (e.g. the offset where padding failed). |
| rescue ran (status 2) but Android did not return | Check the A/B block and `boot_b`'s hash (should be stock `ccd0faff...`). If both look right, power-cycle once more; then BootROM ([14](14-brom-recovery-runbook.md)). |
| no logo, no backlight, USB id `1782:4D00` | SPL itself failed or slot metadata dead. BootROM/FDL route: [13](13-recovery-bootrom.md) / [14](14-brom-recovery-runbook.md). |
| `run_boot_b_test.ps1` aborts with `boot_a is not the verified rescue image` | Working as intended: it pins the v3 hash (`46519e13...`). Flash the verified rescue (section 4) or, if you deployed a *new* generation, update the `$expectedRescue` constant in the runner. |

## TL;DR cheat sheet

Flash the verified rescue (bash, `MSYS2_ARG_CONV_EXCL="*"` set):

```bash
adb push artifacts/rescue/boot_rescue_restore_v3.img /data/local/tmp/rescue.img
adb shell "su -c 'sha256sum /data/local/tmp/rescue.img'"          # 46519e13...
adb shell "su -c 'dd if=/data/local/tmp/rescue.img of=/dev/block/by-name/boot_a bs=1M && sync && sha256sum /dev/block/by-name/boot_a'"
adb shell "su -c 'rm /data/local/tmp/rescue.img'"                   # keep /data/local/tmp lean
```

Hung test kernel: hold **Power ~15 s**, release, wait ~3 min.

Decode a rescue run:

```bash
adb exec-out "su -c 'dd if=/dev/block/by-name/sysdumpdb bs=1 skip=9437184 count=128'" > marker.bin
python scripts/host/decode_rescue_marker.py marker.bin
python scripts/host/read_h71_log.py          # v3: the previous kernel's ring
```

## Appendix: building the image from source

You only need this when the rescue itself must change (the v3
`H71RING1` feature was added this way). Prerequisites: a clang with
lld (any recent one; the reference build used the VPS toolchain), and
the **stock `boot_b` backup** - pass it via `HAWAII_STOCK_BOOT_B` (the
script refuses to run without the exact stock base). The AVB key lives
in `artifacts/kernel-build/avb-test-key.pem`.

```bash
# 1. build the static inits (both modes, ~6 KB each)
bash scripts/rescue/build_init.sh scripts/rescue/rescue_init.c artifacts/rescue
#    (this expects the VPS clang-11.0.1 layout - on any other machine use
#     the raw clang line documented in the header of rescue_init.c)

# 2. pack + sign (embeds the stock blob and footer)
python scripts/host/build_rescue.py dry     artifacts/rescue/boot_rescue_dry_v3.img
python scripts/host/build_rescue.py restore artifacts/rescue/boot_rescue_restore_v3.img
```

`build_rescue.py` prints the final sha256 and runs two offline proofs:
the cpio carries exactly the stock blob/footer, and blob + zeros +
footer reproduces the stock image byte-for-byte.

Two warnings:

- The build is **not bit-reproducible** (a 2026-11-02 v2 rebuild
  produced `750ebd0c...` instead of `fc3ca0ef...`). A different hash
  does not mean the build is broken - but it also is not proof it is
  good.
- Therefore: **a new build is not the live rescue until it has passed
  the dry boot proof and the restore boot proof** (section 5.3), and
  until then `run_boot_b_test.ps1` will (correctly) refuse to run
  tests. Update the runner's `$expectedRescue` when the new
  generation takes over.

## Reference

- Design rationale, dry runs and the original restore test:
  [12](12-slot-b-testing-channel.md)
- The init source: `scripts/rescue/rescue_init.c` (heavily commented -
  the A/B block encoding and the pstore-ring save are documented there)
- Builder: `scripts/host/build_rescue.py`; init builder:
  `scripts/rescue/build_init.sh`
- Marker decoder: `scripts/host/decode_rescue_marker.py`; ring reader:
  `scripts/host/read_h71_log.py`
- One-shot slot helpers: `scripts/device/set_slot_a_active.sh`
  (boot the rescue deliberately), `scripts/device/set_slot_b_tries1.sh`
  (arm the one-attempt fallback)
- Post-rescue Magisk restore: `scripts/host/restore_magisk_after_rescue.ps1`
- BootROM fallback: [13](13-recovery-bootrom.md) /
  [14](14-brom-recovery-runbook.md)
- Live-rescue deployment + v3 qualification evidence:
  [evidence/2026-11-05-boot_b-tests.txt](evidence/2026-11-05-boot_b-tests.txt),
  [evidence/2026-11-05-7.1-ring.txt](evidence/2026-11-05-7.1-ring.txt)

