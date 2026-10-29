# Bootloader unlock research (Moto E32 / hawaii)

Investigation for `todo.md`: is there a **software** bootloader-unlock exploit for
this device? The Moto E32 has no official Motorola unlock support
(`hawaii` is not in Motorola's unlock program), so the only options are the
Unisoc-specific unlock paths.

Short answer: **the unlock machinery is present, but it is signature-gated by
Motorola/ODM keys, and the public Unisoc key leak does not match this device.
The BootROM (CVE-2022-38694) route is blocked by device-specific FDL
requirements and a high brick risk. No working unlock exists with public
tooling as of 2026-10-29.**

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

## What the U-Boot image contains

Dumped `uboot_a` (3 MB), `sml_a` (1 MB), `trustos_a` (6 MB), `miscdata` (1 MB),
`prodnv` (10 MB), `vbmeta_a`, `boot_a` (first 8 MB) for offline analysis
(`artifacts/bootloader/bl/`, gitignored).

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
| TrustOS keys | `trustos_a` @ `0x159459`, `0x159709` | 1024 | `8f31417f7ad923c6…`, `205c1515d220f0ae…` |

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
