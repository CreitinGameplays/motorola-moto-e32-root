# Bootloader unlock research (Moto E32 / hawaii)

Investigation for `todo.md`: is there a **software** bootloader-unlock exploit for
this device? The Moto E32 has no official Motorola unlock support
(`hawaii` is not in Motorola's unlock program), so the only options are the
Unisoc-specific unlock paths.

Short answer for the **key/legacy routes: no.** The unlock machinery is
present, but it is signature-gated by Motorola/ODM keys, and the public Unisoc
key leak does not match this device. The BootROM (CVE-2022-38694) route is
blocked by device-specific FDL requirements and a high brick risk.

That is not the final answer, though. The persisted unlock state turned out to
be a secure-world marker in `miscdata` that a *root* caller can have signed
(SIP service `0xb4000020` op `0x31`) with no private key at all. The follow-up
analysis decoded that path and it **works**: mechanism in
[06-secure-world-unlock-path.md](06-secure-world-unlock-path.md), procedure in
[07-unlock-how-to.md](07-unlock-how-to.md), proof in
[09-gsi-proof.md](09-gsi-proof.md). Read this document as the survey of the
key-based routes and of what the stock bootloader exposes - not as a verdict
that the device cannot be unlocked.

## Device bootloader facts

Collected with `fastboot getvar all` (read-only) and from partition dumps made
with the working runtime-root exploit.

| item | value |
|---|---|
| product / sku | `hawaii` / XT2227-1, bootloader `hawaii-0bc803f-20220927141356-20240220112928` |
| U-Boot | `2015.07-g0bc803f (Feb 20 2024 11:29:28) QOGIRL6` |
| SoC | `T606 AB` (UMS9230), `storage-type: UFS` (Samsung KM5P9001DM-B424, 64 GB) |
| secure boot | `secure: true`, AVB green, `ro.boot.flash.locked=1`, dm-verity enforcing |
| lifecycle state | `lcs: 5` |
| other vars | `unlock_raw_data: a3ba69438ad7993682f1665ab5f25045`, `socidp1/p2`, `tokenp1` |
| U-Boot source tree | `/workspace/spread/2-T606R-Aruba/bsp/bootloader/u-boot15/lib-ontim/...` |

The build path (`2-T606R-Aruba`, `lib-ontim`) shows the bootloader is an
Unisoc/Ontim stack for this exact T606 project, with OpenSSL linked in for
signature verification (`ontim_secverify.c`).

## Fastboot command surface (probed)

Everything below was run in fastboot mode; no state-changing command was used.

| command | result |
|---|---|
| `fastboot getvar all` | works, full variable set above |
| `fastboot oem help` | `FAILED (remote: 'unknown cmd.')` |
| `fastboot oem device-info` | `unknown cmd.` |
| `fastboot oem get_unlock_data` (Motorola flow) | `unknown cmd.` |
| `fastboot flashing get_unlock_ability` | `Not implement.` |
| `fastboot oem get_identifier_token` | **works** → token `5a4635323358394e5857` (= `ZF523X9NXW`) |
| `fastboot oem get_unlock_bootloader_nonce` | `unknown cmd.` |
| `fastboot flashing unlock_bootloader` | host `fastboot` refuses it locally (`unknown 'flashing' command`); it is a raw Unisoc packet, not tested against the bootloader |

So Motorola's own unlock commands are stripped, but **Unisoc's identifier-token
unlock is present** — this is the same protocol used by
`patrislav1/unisoc-unlock` and the "Identifier Token" guides.

## Can the bootloader run a kernel from RAM? (checked 2026-10-30)

The natural way to test a locally built kernel without writing flash is
`fastboot boot <boot.img>`. On this device it **does not work**, and the reason
is worth recording because the command replies `OKAY`.

**First, there are two different fastboot implementations:**

| entry point | `is-userspace` | `fastboot boot` |
|---|---|---|
| `adb reboot fastboot` (fastbootd, inside Android) | `yes` | `FAILED (remote: 'Unrecognized command boot')` |
| `fastboot reboot bootloader` (real U-Boot) | `no` | `Sending OKAY` + `Booting OKAY`, then a reset |

Every probe must first check `fastboot getvar is-userspace`; only `no` is the
real bootloader, and only there is `boot` even dispatched.

**In the real bootloader the command is a stub.** It accepts *any* payload,
including a 6,144-byte file of random bytes with no `ANDROID!` magic, prints
`Booting OKAY [ 0.012s]`, and resets the phone ~6 s later; Android then boots
the flashed stock kernel. Controls that all behaved identically:

| image | size | result |
|---|---|---|
| `boot_vtest.img` (stock repack, version banner patched `ab612c2` -> `ab612cX`) | 34.7 MB | OKAY, reset, stock `ab612c2` boots |
| `boot_vtest_full.img` (full stock `boot_b`, 1 banner byte patched) | 64 MB | OKAY, reset, stock `ab612c2` boots |
| `boot_addrfix.img` (stock `boot_b` + load addresses set to real DRAM `0x80080000`/`0x82000000`/`0x80000100`) | 64 MB | OKAY, reset, stock `ab612c2` boots |
| `boot_b.img` (pristine stock image, sha256 `CCD0FAFF…`) | 64 MB | OKAY, reset, stock `ab612c2` boots |
| 4 KiB of random bytes (client wraps it into a 6 KB boot image) | 6 KB | OKAY, reset, Android boots |

Two independent checks prove nothing was ever executed:

* **No idle timeout.** Sitting in the real bootloader with no command, the
  device stayed in fastboot for >119 s (29 probes, 4 s apart). So the reset is
  caused by `boot`, not by a timeout.
* **The bootloader's own log is consistent with a reboot.** The `uboot_log`
  ring records the cause of each reset as `reset_mode`; over the whole ring the
  only `(c)-(kernel_crash)` record is a historical one, while fastboot-initiated
  resets appear as `(4)-(fastboot)`. Caveat: the ring was not rewritten by these
  attempts (the same 14 records and the same maximum boot counter appear in the
  dumps taken before and after), so it corroborates but does not prove the
  per-run cause.
* **No kernel-side trace.** `console-ramoops-0` after the attempts is 2.6 KB
  with no `Linux version` line and no `ab612cX` marker.

The U-Boot binary is consistent with this: its fastboot command string pool
contains `getvar:`, `download:`, `flash:`, `erase:`, `powerdown`, `reboot-*`,
`set_active:`, `oem`, `setdump`/`getdump`, `getlcs`, `setrma`, `getsocid` -
with **no standalone `boot` entry** (the only `boot:` bytes in the image are
part of `Hit any key to stop autoboot:`), and no load/jump path for a RAM
payload was found in the disassembly. The empirical garbage-payload test above
is the decisive part: the command never looks at the image.

The other candidate RAM-execution doors are closed as well:

| door | state |
|---|---|
| `kexec` / `crash_dump` in the stock kernel | `# CONFIG_KEXEC is not set`, `# CONFIG_CRASH_DUMP is not set` |
| `/dev/mem`, `/dev/kmem`, `/proc/kcore` | all absent (`# CONFIG_DEVMEM is not set`, `# CONFIG_PROC_KCORE is not set`); `/proc/kallsyms` is permission-denied |
| SPRD download mode | full command set recovered (`dl_cmd_auth_request`, `..._check_partition`, `..._read_vcur`, `..._write_vcur`, `..._repartition`, `..._set_debuginfo`, ...) - all read/write partition operations, **no boot/jump/exec**, writes signature-gated by `dl_secure_process_flow` |
| U-Boot console (`bootm`, `booti`, `go`, `fatload`, `setenv`, `run`) | UART-only: the image has **no USB keyboard driver** (`usbkbd`/`keyboard` = 0 hits) and no USB console, so it needs physical UART pads |
| `fastboot oem ...` | real bootloader answers `unknown cmd.` for unknown subcommands; the known ones are unlock/dump/NV operations (`get_identifier_token`, `unlock_bootloader`, `getlcs`, `setrma`, `getsocid`, `setdump`, `getdump`, `frp-state`) - none executes code. (In fastbootd every `oem` call blindly returns `OKAY`, which is easy to misread as acceptance.) |

Conclusion: **`fastboot boot` cannot be used to run the built kernel.** The only
remaining way to run it on the phone is to write it to `boot_b`, which is a
flash operation and requires a deliberate decision (the stock image is dumped
in `artifacts/bootloader/bl3/boot_b.img`, sha256 `CCD0FAFF…`, for restore).
Full probe log: [evidence/2026-10-30-fastboot-ram-boot-dead-end.txt](evidence/2026-10-30-fastboot-ram-boot-dead-end.txt).

## The fastboot write gate (still active after the unlock)

Testing the flash path with the **pristine, byte-identical stock images** (the
same bytes the phone is already running) is rejected:

```
fastboot flash boot_b boot_b.img
  Sending 'boot_b' (65536 KB)   OKAY [  1.569s]
  Writing 'boot_b'              (bootloader) Please verify the signature!
  FAILED (remote: 'Please verify the signature!')

fastboot flash misc   misc.img     -> FAILED (remote: 'Please verify the signature!')
fastboot flash dtbo_a dtbo_a.img   -> FAILED (remote: 'Please verify the signature!')
```

So the write gate is **global and content-independent**, and the
`VerifiedBoot-UNLOCK` marker (which makes the *boot* path skip AVB) does **not**
unlock it. The gate lives in the Unisoc secure-download code
(`lib-ontim/ontim-config/ontim_secverify.c`, `...#signature...` strings, and the
`dl_secure_process_flow`/`SECUREBOOT_ENABLE` path used by download mode); the
device is `secure: true`, i.e. the signature key is anchored in secure boot.

Practical consequences:

* There is **no fastboot way to write `boot_b`** - and therefore **no fastboot
  way to restore it** either.
* Writing `boot_b` from Android with `dd` (as root) is possible in principle,
  but it is a **one-way trip**: if the new kernel fails, Android never boots,
  the fastboot write gate still blocks re-flashing the stock image, and
  `adb reboot download` does not enter download mode (verified - the phone
  stays in Android). Recovery would need a signed Motorola factory package
  written through an authenticated download session, or a UFS programmer.
* `fastboot set_active a` exists, but slot `_a` carries an older kernel
  (`4.14.199+-abc1989`, built 2024-01-23) and different
  `vbmeta_system`/`vbmeta_vendor`/`vbmeta_product` hashes, so it is not a clean
  fallback for slot `_b`.

New leads for a future session (not yet exploited): the download-mode protocol
has a **password** authentication path (`dl_cmd_auth_request`,
`Start password verify ...`, `Password verify successfully.`,
`You can flash ro.carrier.`) and TrustOS exposes `FUNCTYPE_CHECK_PWD` /
`FUNCTYPE_GET_LCS` next to the `VerifiedBoot-*` functions; `SET_RMA` /
`getlcs`/`setrma` are also reachable through `fastboot oem`. If a download
session can be entered and authenticated without a Motorola key, that would
also reopen the flash path.

## What the U-Boot image contains

Dumped `uboot_a` (3 MB), `sml_a` (1 MB), `trustos_a` (6 MB), `miscdata` (1 MB),
`prodnv` (10 MB), `vbmeta_a`, `boot_a` (first 8 MB) for offline analysis
(`artifacts/bootloader/bl/`, gitignored).

**Slot note (checked 2026-10-30).** The device boots **slot `_b`**
(`ro.boot.slot_suffix=_b`, `fastboot getvar current-slot` -> `b`), while the
dumps above are the `_a` copies. Verified on the device:

| partition pair | sha256 | identical? |
|---|---|---|
| `uboot_a` / `uboot_b` | `9218339e…` | **yes** |
| `vbmeta_a` / `vbmeta_b` | `80164877…` | **yes** |
| `sml_a` / `sml_b` | `a3534538…` / `24f0ef27…` | no |
| `trustos_a` / `trustos_b` | `7467775e…` / `6a6080c8…` | no |

For TrustOS the hash differs, but `trustos_b` carries the **same two RSA keys
at the same offsets** (`0x159459`, `0x159709`) and the same
`VerifiedBoot-*` / `FUNCTYPE_*` strings at the same offsets (`0x82e70` …
`0x83540`), so the secure-world analysis below applies to the active slot too.


Relevant U-Boot strings (offsets in `uboot_a.img`):

```
0x0c368a  get_identifier_token
0x0c369f  Identifier token:
0x0c36c6  Bootloader can not been unlocked repeatly.
0x0c36f1  Unlock bootloader fail.
0x0c3780  Info:Unlock bootloader success!
0x0c3a1c  get_unlock_bootloader_nonce
0x0c3a38  unlock_bootloader
0x0c3a4a  Please firstly execute <fastboot oem get_identifier_token>
0x0c3a86  Warning: Unlock device may erase user data.
0x0c1c10  WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!
0x0d6b48  uboot_verify_product_sn_signature() return error:param->a0=%d
```

This is the complete Unisoc unlock flow:

1. `fastboot oem get_identifier_token` → hex token (the product serial)
2. `fastboot download <signature>` → 512-byte RSA signature over the token
3. `fastboot flashing unlock_bootloader` → U-Boot calls
   `uboot_verify_product_sn_signature()` and unlocks (erasing userdata) on success

The whole gate is the **RSA signature over the serial number**, verified against
a public key baked into the bootloader.

## Route A: identifier-token unlock (leaked OEM key)

The community tool signs the token with a leaked 4096-bit key
(`rsa4096_vbmeta.pem`, first popularised for the Anbernic RG405M / T618) and
sends the raw `flashing unlock_bootloader` packet.

**Key comparison performed on the actual images:**

| key | where | bits | SHA-256 of modulus |
|---|---|---|---|
| leaked `rsa4096_vbmeta.pem` | Anbernic/T618 leak | 4096 | `36949b827927c883…` (head `d804afe3d3846c7e`) |
| Motorola AVB key | `vbmeta_a` aux block (AVB, `SHA256_RSA4096`) | 4096 | `ecbe1669a209b526…` (head `f6ab7d9f81f0ed40`) |
| U-Boot embedded key | `uboot_a` @ `0xb7ac8` (DER SPKI) | 2048 | `20c694a8bd917976…` (head `c0cb16e76cf37aca`) |
| TrustOS keys | `trustos_a` @ `0x159459`, `0x159709` (also present at the same offsets in `trustos_b`) | 1024 | `8f31417f7ad923c6…`, `205c1515d220f0ae…` |

The leaked key's modulus appears **nowhere** in `uboot`, `sml`, `trustos`,
`prodnv`, `miscdata`, `vbmeta` or the boot image. The unlock verifier either
uses the U-Boot-embedded 2048-bit key or a key held in secure world; in both
cases it is not the leaked key.

**Conclusion:** the identifier-token unlock is implemented, but without
Motorola's private key it cannot produce a valid signature. The public
`unisoc-unlock` flow is expected to fail with `Unlock bootloader fail.`
A real attempt would be harmless on failure and would wipe userdata on success
(it did not succeed in offline analysis, so it was not attempted).

## Route B: BootROM exploit CVE-2022-38694 (+ 38691/38692)

NCC Group's Unisoc BootROM research (unchecked write address in recovery mode)
gives code execution in the BootROM/FDL1, and the `TomKing062` toolkit turns it
into a one-time or persistent signature-verification bypass. `ums9230` (T606)
is a supported platform, and the toolkit has a `ums9230_moto_g04.zip` release.

Blockers specific to this device:

- **Downloads must be entered by key combo or test point** (per the project wiki:
  power+vol up / power+vol down / all three). No software path exists: the
  kernel exposes no reboot-mode node and `adb reboot download` is not a
  supported Unisoc target.
- **Motorola UFS devices enumerate as `22b8:2e81` ("SPRD4:AutoD") instead of
  the SPRD BootROM (`1782:*`)** — reported for the Moto G04 (XT2421-2,
  UMS9230 UFS) in the toolkit's issue #317. FDL1 executes, but FDL2 reports
  "incompatible partition", the partition list cannot be read, and
  `miscdata` cannot be dumped. Nothing can be unlocked in that state.
- **No `hawaii` (Moto E32) support**: the support list has `moto e13` and
  `moto e20` only, and the E13 entry is marked *"EMMC ONLY, THIS WILL ERASE
  YOUR UFS"*. Motorola UFS devices must not use FDLs from Motorola EMMC
  devices or from other vendors.
- **Brick risk is real**: wrong/foreign FDL1/FDL2 on a UFS device can erase the
  partition table. Without a working download mode there is no way to take a
  full backup first.

**Conclusion:** not usable today. It would require a `hawaii`-specific, UFS-correct
FDL1/FDL2 (from a Motorola factory/blankflash package) plus physical access to
the download-mode key combo or the UFS test points, and it can destroy the
device if anything is wrong.

## Route C: Motorola official unlock

Not available: `hawaii` is absent from Motorola's unlock programme, and the
bootloader does not implement `oem get_unlock_data` / `oem unlock`. The
`unlock_raw_data` and `tokenp1/socidp1` variables exist for the Unisoc flow
above, not for a Motorola web unlock.

## Other observations

- `miscdata` starts with `"90PS"` + serial and a factory tag table
  (`DOWNLOAD`, `WRITESN`, `CFT`, `BBAT`, `WCN`, `ANTENNA`, `IMEI`, `PASS`), plus
  bootloader config strings (`disable`, `autoreboot-enable`). It contains **no
  unlock state** on a locked device.
- U-Boot's `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!` is the classic
  Unisoc message used when the device is already unlocked. Follow-up reversing
  (see [06](06-secure-world-unlock-path.md)) shows the flag is **not** an OTP
  bit: U-Boot reads a 64-byte signed marker from `miscdata` @`0x2000`,
  validates it with SMC op `0x33`, and skips AVB when it is valid. The marker
  is produced by SMC op `0x31` (`VerifiedBoot-UNLOCK`), which is now being
  tested as a signature oracle from Linux.
- `lcs: 5` is the lifecycle state reported by `fastboot getvar`; it is not
  writable through any exposed fastboot command.
- AVB on this device is `SHA256_RSA4096`; the vbmeta key is Motorola's
  (`ecbe1669…`), so even a runtime-root write of `boot_a` would be rejected by
  the bootloader.

## Reproduce the analysis

All dumps were taken with the runtime-root exploit (no flashing):

```bash
adb shell 'chmod 755 /data/local/tmp/mali_kroot; /data/local/tmp/mali_kroot >/dev/null 2>&1; \
  dd if=/dev/block/by-name/uboot_a of=/data/local/tmp/bl/uboot_a.img bs=4096'
adb pull /data/local/tmp/bl ./artifacts/bootloader/bl
python scripts/host/analyze_bootloader.py artifacts/bootloader/bl
```

`scripts/host/analyze_bootloader.py` extracts the DER/AVB public keys, prints
their fingerprints, and compares them against a candidate leaked key.

## Verdict

| route | available | why |
|---|---|---|
| Motorola official unlock | no | device unsupported, commands removed |
| Unisoc identifier-token unlock | **no** (mechanism present) | needs Motorola/ODM private key; leaked key does not match |
| CVE-2022-38694 BootROM exploit | **no** (platform matches) | needs physical download mode + hawaii UFS FDLs; Moto UFS falls back to AutoD; brick risk |
| secure-world `miscdata` marker (SMC `0xb4000020` op `0x31`) | **yes - works** | mechanism decoded in [06](06-secure-world-unlock-path.md), applied and verified; a GSI boots as independent proof, see [07](07-unlock-how-to.md) and [09](09-gsi-proof.md) |
| run a custom kernel from RAM (`fastboot boot`) | **no** | real bootloader ACKs and reboots without executing the payload; fastbootd has no `boot` at all; kexec/devmem absent; no exec command in download mode; U-Boot console is UART-only (see the section above) |
| write a custom kernel with `fastboot flash` | **no** | global signature gate: even the phone's own byte-identical stock images are refused with `Please verify the signature!` (`boot_b`, `misc`, `dtbo_a` all tested); the unlock marker opens boot, not writes ([evidence](evidence/2026-10-30-flash-gate.txt)). The gate is decoded in [11](11-flash-gate.md): it needs a non-secure efuse (secure-world SIP op `0xa`) or the RAM flag `0x9f70a001`, whose only setter is unreferenced dead code. `erase:` is gated by the same function |
| switch slots with `fastboot set_active` | **yes** | ungated (not a `flash:`/`erase:` command, it only rewrites the BCB in `misc`): `set_active a` and `set_active b` both return `OKAY` in 0.016 s. See [evidence](evidence/2026-10-30-slot-switch.txt) |
| boot slot `a` with its stock image | **no** | boot-loops: `boot_a` carries the older `abc1989` kernel (2024-01-23) which does not come up against the installed `RORS31.335-58-1` system (`ab612c2`, 2024-02-20), most likely a vendor-module `__crc_` mismatch |
| recover a boot-looping slot | **yes, manual** | hold **Volume Down** during the failed boot to enter fastboot, then `fastboot set_active b` + reboot -> Android on the stock kernel, root regained on the first `mali_kroot` attempt. The phone does *not* fall back to fastboot on its own |
| write `boot_a` with `dd` from rooted Android, keep `boot_b` stock | **untested, recoverable** | boot-time verification is skipped while unlocked (`WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!`, [11](11-flash-gate.md) §10) and the BCB round trip above is proven, so slot a is a recoverable experiment - but its stock image already fails to boot, so success is not guaranteed |
| write `boot_b` with `dd` from rooted Android | **possible but a one-way trip** | no fastboot restore path exists and `adb reboot download` does not enter download mode, so a failed kernel cannot be rolled back over USB |
| runtime root (this repo) | **yes** | `scripts/mali/mali_kroot.c`, 5/5 fresh boots |

Recommendation: keep using the runtime-root exploit. Bootloader unlock via the
legacy/key paths is not reachable with public tooling; do not flash or force
download mode without a hawaii-specific UFS FDL and a verified recovery plan.
The secure-world marker route turned out to be the winning one: it needs no
private key and no FDL, only the runtime root that this repo already provides.
It is now applied and verified on the device (`ro.boot.flash.locked=0`,
`verifiedbootstate=orange`); the step-by-step is in
[07-unlock-how-to.md](07-unlock-how-to.md) and the captured evidence in
[evidence/2026-10-29-unlock.txt](evidence/2026-10-29-unlock.txt).
Functionally confirmed as well: an Android 15 GSI with no Motorola
signature boots on the unlocked device ([09-gsi-proof.md](09-gsi-proof.md),
[evidence/2026-10-29-gsi-boot.txt](evidence/2026-10-29-gsi-boot.txt)).
