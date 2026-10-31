# 15 - Play Integrity on the unlocked Moto E32 (no bootloader relock)

Date started: 2026-10-31
Status: **in progress, blocked** (2026-10-31 12:00)

- persistent Magisk root works on `boot_b` (bootloader still unlocked);
- TrickyStore 1.4.1 + keybox makes KeyAttestation report *locked*;
- Play Integrity returns **all three verdicts false** in every configuration
  tried, including with TrickyStore inert. This is a *regression*: before
  Magisk was installed the same checker reported BASIC = pass.
- Next experiment (cheapest): boot a stock, non-Magisk signed image and
  re-check, to separate "Magisk present" from "keybox/attestation" as the
  cause. See "next steps" at the end.

Work log in section 7, hypotheses in 8, ordered next steps in 9, repro
commands in 10, file inventory in 11.

## 1. Objective and constraint

Make the device pass **Play Integrity** (`MEETS_BASIC_INTEGRITY`,
`MEETS_DEVICE_INTEGRITY`, ideally `MEETS_STRONG_INTEGRITY`) for apps that
require it (banking, Google Wallet, some games), **without relocking the
bootloader** and without losing the current setup:

- stock Android 11 (RORS31.335-58-1, security patch 2024-02-05), GMS 26.43.30
- bootloader unlocked in software via the `miscdata` marker
  (`ro.boot.flash.locked=0`, `ro.boot.verifiedbootstate=orange`)
- `boot_a` = the proven restore rescue; `boot_b` = stock Android
- root today is runtime only (`mali_kroot`), persistent root is desired anyway
  for the attestation-spoofing daemon

## 2. Device state at the start (2026-10-31)

| item | value |
|---|---|
| serial | ZF523X9NXW |
| build | `motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys` |
| Android | 11 |
| security patch | 2024-02-05 |
| GMS | 26.43.30 (versionCode 264330022) |
| Play Store | installed, Google account signed in |
| bootloader | unlocked (`flash.locked=0`, `verifiedbootstate=orange`) |
| root | runtime only; exploit works (one SIGBUS run seen, retry OK) |

## 3. How Play Integrity is decided (short)

1. App calls `PlayIntegrityManager.requestIntegrityToken()` (classic) or the
   standard request, via Google Play services.
2. GMS collects signals: **hardware key attestation** of a key in the TEE
   (certificate chain rooted in Google's attestation CA, plus an attestation
   extension containing `verifiedBootState`, `deviceLocked`, patch levels,
   OS version, app ID), APK signature, Play install info, account info.
3. GMS sends all of it to Google's servers.
4. Google returns a **signed JWT**. The app (or its backend) verifies the
   Google signature and reads the verdicts.

Verdict meaning (as enforced by Google's server, not by the phone):

| verdict | requirements |
|---|---|
| `MEETS_BASIC_INTEGRITY` | genuine Play-services device, app not re-signed/tampered |
| `MEETS_DEVICE_INTEGRITY` | + genuine/certified device, **bootloader locked**, verified boot, no tampering |
| `MEETS_STRONG_INTEGRITY` | + hardware-backed attestation and **recent patch levels** (Google currently expects roughly within the last year) |

Consequences for this phone:

- The JWT cannot be forged locally (it is signed by Google).
- `verifiedBootState=orange` / `deviceLocked=false` in the attestation
  extension is what kills DEVICE and STRONG. `Security patch 2024-02` also
  kills STRONG.
- Therefore the only viable route that keeps the unlock is to make the
  **key attestation output** say "locked + verified + recent patch", while
  the real TEE still signs (or the chain is re-signed) with a key that
  Google's CA accepts.

## 4. Approaches surveyed (2026 state)

| # | approach | can pass DEVICE? | notes |
|---|---|---|---|
| 1 | **Relock bootloader** (delete `miscdata` marker, wipe `/data`) | yes, legitimately | Explicitly excluded by the task; loses the unlocked state and the `dd` kernel-testing freedom; would give green DEVICE and probably STRONG with a real 2026 patch (impossible on this 2024 firmware) |
| 2 | **Root hiding only** (Magisk DenyList, Shamiko, Zygisk Assistant) | no | hides root from the app, but the attestation still says unlocked |
| 3 | **Keybox + keystore attestation spoofing** - TrickyStore, TEESimulator(-RS), OhMyKeymint | **yes** | the standard 2024-2026 method; replaces / re-signs the attestation chain with a leaked Google-attestation keybox; the Google-rooted chain is genuine, so the server accepts it; TrickyStore can also rewrite `verifiedBootState`/`deviceLocked` and the patch levels |
| 4 | **Props/fingerprint spoof** (Play Integrity Fix / PIF, Integrity-Box, ...) | no (alone) | spoofs `ro.*` build props; needed to match the keybox profile or to hide a test-keys/custom-ROM fingerprint, but does not change the TEE attestation |
| 5 | **Client-side hooking** (LSPosed "Device Checker"-style hooks of the Play Integrity API) | local-only | fakes the verdict inside the app process; any backend that validates the JWT with Google still fails |
| 6 | **Forge the JWT** | impossible | Google's signing key is not obtainable |
| 7 | **Patch the bootloader / TrustOS to report locked** while keeping the unlock marker | maybe, very risky | would be the most "honest" spoof (real TEE key + green state), but U-Boot/SPL/TrustOS are signature-checked; writing `uboot_b`/`trustos_b` risks an unrecoverable boot chain. Not attempted unless 3 fails |
| 8 | **Custom ROM / GSI + relock** | excluded | still orange when unlocked, and this device has no relockable custom AVB chain |

### Why option 3 works on an unlocked device

- A `keybox.xml` contains the **private attestation key** and its
  Google-signed certificate chain (leaked from a real device).
- TrickyStore intercepts the keystore attestation call and either
  re-signs/patches the TEE-produced leaf certificate with the keybox key or
  generates the whole chain itself (TrickyStore "leaf hack" / "generate"
  modes), then re-encodes the attestation extension. That extension is where
  `verifiedBootState`, `deviceLocked`, `osPatchLevel`, `vendorPatchLevel`,
  `bootPatchLevel` and the app ID live, so they can be set to "locked /
  green / recent".
- The resulting chain is rooted in Google's real attestation CA, so Google's
  server accepts it as genuine hardware attestation.
- The main practical cost: keyboxes are leaked/shared, get **revoked**, and
  are against Google's terms. A revoked keybox makes DEVICE fail again; the
  keybox must be rotated when that happens.

### Module comparison (2026)

| project | Android | targets Android 11 here? | boot-state spoof? | state |
|---|---|---|---|---|
| **TrickyStore** 1.4.1 (5ec1cff) | 10+ | yes | **yes** (leaf hack / generate, BootloaderSpoofer heritage) | closed source since 1.1; still the reference stack |
| **TEESimulator** 4.0 (JingMatrix) | 10+ | yes (legacy `keystore` path documented) | **no** - deliberately harvests the *real* root of trust, so an unlocked phone attests unlocked | open source, very active |
| **TEESimulator-RS** 6.0.1 (Enginex0) | 10+ | yes | uncertain (fork of the above; adds `ro.boot.*` prop spoofing) | open source, active 2026-07 |
| **OhMyKeymint** 1.2.5 (qwq233) | **12+** | no | yes (full AIDL keystore) | open source, active |

Because this phone is **unlocked**, TEESimulator's design choice (real root
of trust) makes it unsuitable as the primary. The plan is:

1. Magisk (for persistent root / module loading)
2. **TrickyStore 1.4.1** with a valid keybox
3. Play Integrity Fix / props module only if the verdict needs it
4. Magisk Zygisk + DenyList for root hiding

## 5. Chosen stack and why Magisk

TrickyStore needs a daemon that survives boot and injects into the
`keystore` process, i.e. persistent root. Options were Magisk, KernelSU,
APatch. KernelSU/APatch need a kernel patch; this device's self-built kernel
does not boot (see `todo.md`) and the bootloader flash gate is closed.
Magisk only patches the **ramdisk** and works with the stock kernel, which
is exactly the channel already proven on 2026-10-30
(`boot_stock_signed.img` boots Android userspace).

The AVB constraint: TrustOS rejects images that carry no vbmeta
(`a0=6`) but tolerates a well-formed chain signed by an unknown key
(`a0=5`, `allow_verification_error=1`). So the Magisk-patched image is
re-signed with the throwaway `SHA256_RSA4096` key exactly like
`scripts/host/build_avb_boot.py` does.

## 6. Recovery path (unchanged, proven)

- `boot_a` holds `boot_rescue_restore.img` (fc3ca0ef...), which rewrites the
  whole stock `boot_b` from its embedded blob and flips the A/B block back
  to `_b`.
- If the Magisk kernel hangs: power-cycle; the SPL spends slot `b`'s try and
  falls back to slot `a`; the rescue restores stock `boot_b`; Android is back
  in ~40 s.
- Before any write, slot `b` is set to one attempt (`0x001f` = prio 15,
  tries 1, not successful) so the fallback happens after one power cycle and
  does not need the Vol-Down timing.
- Full partition backup: `D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\`
  (`boot_b.img` sha256 `ccd0faff51ab...4f7b18`).

## 7. Work log

### 2026-10-31 - research and tool inventory

- Confirmed device state (table above), GMS 26.43.30, Google account present.
- Read the current (2026) approaches: HackTricks Play-Integrity skill,
  onehourroot/privacyportal 2026 guides, T.A.K.R. keybox repository.
- Tooling downloaded to `D:\AndroidSDKTools\pi\` (kept off C:):
  - `Magisk-v31.1.apk` (10,679,283 B)
  - `TEESimulator.zip` (canary 76, v4.0)
  - `TrickyAddon.zip` (v4.4)
  - `IntegrityBox.zip` (v46)
  - `Megatron` + decoded `keybox_meow.xml`
- Keybox test (`megatron` = 10x base64 -> hex -> rot13 -> keybox XML):
  - Google chain: leaf `O=TEE, CN=405d3d105161e72c763ae726e2f1695f`,
    issuer `O=Google LLC, CN=Droid CA3` -> `Droid CA2` ->
    `Key Attestation CA1` (self-signed root)
  - leaf validity 2026-10-25 .. **2026-11-06** (only ~6 days left)
  - serials **not** in `https://android.googleapis.com/attestation/status`
    (not revoked as of 2026-10-31)
  - EC-only keybox (TrickyStore accepts; TEESimulator wants RSA+ECDSA)
- Note: `keybox.kowx712.cc` (T.A.K.R.) is the community repository; the
  download endpoint requires a captcha, the `Megatron` blob in
  MeowDump/Integrity-Box is one of its keyboxes (decoded above).

### 2026-10-31 - Magisk boot image prepared

- Runtime root: `adb shell "/data/local/tmp/mali_kroot"` -> uid=0,
  SELinux permissive. (One earlier run died with signal 7; the retry was
  clean - same known flakiness as `docs/04-reliability-hardening.md`.)
  Remember: the exploit elevates the *current* adb shell and its children
  only, so the root work must run in the same `adb shell` invocation.
- Staged Magisk v31.1's own patcher on the device:
  `/data/local/tmp/pi/stage/` = `magiskboot`, `magiskinit`, `magisk`,
  `init-ld`, `busybox`, `boot_patch.sh`, `util_functions.sh`, a `dos2unix`
  shim; input `stock_boot_b.img` (sha256 `ccd0faff...`).
- `BOOTMODE=true sh boot_patch.sh stock_boot_b.img` ->
  `new-boot.img` (64 MiB; Magisk keeps the stock OEM vbmeta footer, which
  is now stale).
- Pulled to `D:\AndroidSDKTools\pi\magisk_patched_raw.img`
  (sha256 `77597e34803de41186b002fd39591cb513734b9ef317bc18640bf58fccccbcca`).
  `avbtool info_image`: Original image size 34,932,736; the preserved OEM
  vbmeta hash describes the old payload -> must be replaced.
- Rebuilt the footer: payload = first 34,932,736 B, then
  `avbtool add_hash_footer --partition_name boot --partition_size 67108864
  --key artifacts/kernel-build/avb-test-key.pem --algorithm SHA256_RSA4096
  --rollback_index 2 --salt f83b9936...af0991`
  -> `D:\AndroidSDKTools\pi\boot_magisk_avb.img`
  (sha256 `90416c09f6359fdcc0711f36e214454421c42598518787f58c1916be6c5cad3c`,
  64 MiB, kernel size unchanged 25,358,352, ramdisk 9,393,149).

### 2026-10-31 - Magisk flashed to `boot_b` and booted (persistent root)

Procedure used (repeatable, matches `docs/12-slot-b-testing-channel.md`):

1. push `D:\AndroidSDKTools\pi\boot_magisk_avb.img` to
   `/data/local/tmp/pi/boot_magisk_avb.img`, verify sha256 on device
   (`90416c09...cad3c`).
2. single root shell (`mali_kroot`), then in the same invocation:
   - read `boot_b`, require sha256 == `ccd0faff...4f7b18` (stock) else abort;
   - `dd` the new image to `/dev/block/by-name/boot_b`, `sync`;
   - read back, require sha256 == `90416c09...cad3c` else abort;
   - write the A/B block = one attempt for slot b (`0x001f`: prio 15,
     tries 1, successful 0; block bytes
     `5f 62 00 00 42 43 41 42 01 02 00 00 8e 00 1f 00 ...` crc `20a582b1`).
3. `adb reboot`; Android came back on `_b` in ~50 s, `sys.boot_completed=1`.

Result and checks:

- `ps -A | grep magisk` -> `root 468 1 ... magiskd` (persistent root daemon).
- `getprop ro.boot.slot_suffix` = `_b`; `ro.boot.verifiedbootstate` = `orange`,
  `ro.boot.flash.locked` = `0` (unlock untouched, as intended).
- `mali_kroot` still works, but it is only needed to reach `/data/adb` until
  the Magisk app installs `su`; after that, persistent root comes from
  `magiskd`.
- **Caveat found later (important):** every successful `mali_kroot` run sets
  the kernel's `selinux_state.enforcing` to 0 *in RAM* (see
  `scripts/mali/mali_kroot.c:patch_selinux`, `docs/03-root-exploit.md`), so
  `getenforce` reports **Permissive for the rest of that boot**. It returns to
  Enforcing only after a reboot. Measured 2026-10-31 12:05: `getenforce` =
  `Permissive` with `ro.boot.vbmeta.device_state=unlocked`,
  `ro.boot.flash.locked=0`, `ro.boot.verifiedbootstate=orange`.
  This is a plausible **independent cause** of the all-red verdicts: every
  Play Integrity test in this session was run in a shell session that had
  already executed the exploit (i.e. with SELinux permissive), whereas the
  pre-Magisk baseline was measured on a fresh boot. See hypothesis 0 below.

Important ordering detail: a freshly patched ramdisk has Magisk's binaries
only inside `/debug_ramdisk`; `/data/adb/magisk` is empty until the **Magisk
app** performs "additional setup". Before that, `magisk --install-module`
fails with **"Incomplete Magisk install"**. Fix: install
`Magisk-v31.1.apk`, open it, accept "Requires additional setup" -> the app
reboots once and populates `/data/adb/magisk` (binaries + config).

Tooling installed from `D:\AndroidSDKTools\pi\` (all three sideloaded):

| apk | package | purpose |
|---|---|---|
| `Magisk-v31.1.apk` | `com.topjohnwu.magisk` | root manager, module install, Zygisk/DenyList |
| `KeyAttestation-v1.8.4.apk` (vvb2060) | `io.github.vvb2060.keyattestation` | reads the real keystore attestation chain |
| `checker.apk` (Play Integrity API Checker) | `gr.nikolasspyr.integritycheck` | shows the three verdicts |

(UI automation notes: `am start -n .../.MainActivity` works for the checker;
KeyAttestation's activity is `.home.HomeActivity`; the CHECK button is at
~`(360,1056)` on this 720x1600 panel.)

### 2026-10-31 - TrickyStore 1.4.1 installed, keybox applied

- `TrickyStore.zip` (release `1.4.1`, tag `245-72b2e84`) from
  `github.com/5ec1cff/TrickyStore` installed with
  `/debug_ramdisk/magisk --install-module`. Module lands in
  `/data/adb/modules/tricky_store/` (`daemon`, `service.apk`,
  `libtricky_store.so`, `service.sh`, `post-fs-data.sh`, `sepolicy.rule`,
  `verify.sh`).
- `service.sh` starts `./daemon` in a `while true` loop; the daemon is
  `/system/bin/app_process -Djava.class.path=./service.apk --nice-name=TrickyStore
  io.github.a13e300.tricky_store.MainKt`. Visible as process **`TrickyStore`**
  (uid 0). `DEBUG=false` in `service.sh` - set it to `true` if verbose logs are
  needed (it only affects the daemon's own logging).
- Configuration dir `/data/adb/tricky_store/`:
  - `keybox.xml` - replaced with the decoded `Megatron` keybox
    (`D:\AndroidSDKTools\pi\keybox_meow.xml`, 5903 B; the module's default
    software keybox was backed up as `keybox.xml.default`).
  - `target.txt` - package list, one per line; `?` suffix = "leaf hack" mode,
    `!` suffix = force generate, `#` starts a comment.
  - `security_patch.txt` - optional patch-level spoof (`system=`/`vendor=`/
    `boot=` dates).
  - `key_db/` - TrickyStore's own sqlite (`keystore.db` + WAL), created
    automatically.
  - `tee_status` - **`teeBroken=true`** on this device (see below).

### 2026-10-31 - KeyAttestation results

Two modes were compared with `io.github.vvb2060.keyattestation` (relaunch the
app after every change; it caches the last certificate).

**A. TrickyStore inert (`target.txt` = `# none`) - native TEE attestation:**

```
Google hardware attestation root certificate
Bootloader is unlocked
subject:SERIALNUMBER=f92009e853b6b045 ... (Google root)
subject:SERIALNUMBER=d8bfe951..., T=TEE
subject:SERIALNUMBER=966cd7af..., T=TEE
subject:CN=Android Keystore Key
Version: Keymaster 4.0 / Security level: TrustedEnvironment
```

=> The TEE works, the device really is Google-key-attested hardware, and it
honestly reports *unlocked*. (This is why TEESimulator-style "real root of
trust" designs cannot pass DEVICE here.)

**B. TrickyStore active (`target.txt` = gms/vending/gsf/keyattestation):**

```
Unknown root certificate
Root certificate is not a known trusted certificate authority.
Bootloader is locked
subject:C=US, O=Google LLC, OU=Android, CN=Key Attestation CA1 (2025-07-17..2035-07-15)
subject:CN=Droid CA2, O=Google LLC   (2026-02-09..2029-02-08)
subject:CN=Droid CA3, O=Google LLC   (2026-10-26..2027-01-04)
subject:CN=405d3d105161e72c763ae726e2f1695f, O=TEE  (2026-10-25..2026-11-06)
        number of certs issued in last 30 days: 64
        manufacturer:Xiaomi
subject:CN=Android Keystore Key
Version: Keymaster 4.0 / Security level: TrustedEnvironment
```

Notes / interpretation:

- `Bootloader is locked` proves TrickyStore is rewriting the attestation
  extension (`verifiedBootState`/`deviceLocked`). The chain is the keybox's
  genuine Google RKP chain (`Key Attestation CA1` -> `Droid CA2` -> `Droid CA3`
  -> leaf). The chain is *not* the same CA as the on-device native chain (that
  one is the older `SERIALNUMBER=f92009e8...` root), so KeyAttestation shows
  "Unknown root certificate" - expected, **not** an error.
- `manufacturer:Xiaomi` comes from the keybox profile. This is a red flag for
  Play Integrity: GMS sees the keybox's attestation record (Xiaomi
  manufacturer/model/build fingerprint) while the device reports
  `motorola/hawaii/hawaii`. Google's server can cross-check these; a
  mismatched profile is a documented cause of DEVICE failure and even of the
  whole token degrading to BASIC=false.
- `Version: Keymaster 4.0` with the keybox chain is plausible for the RKP
  keybox (Keymaster 4.0/4.1 both appear), so that alone is not fatal.
- `?` suffix (leaf-hack) produced **the same** chain as plain package names,
  i.e. on this device the daemon already takes the "generate + sign with
  keybox key" path. So `?` vs bare names is not a differentiating knob here.

### 2026-10-31 - `tee_status` = teeBroken=true

`/data/adb/tricky_store/tee_status` contains `teeBroken=true`. Consequence:
TrickyStore refuses to do the "patch the real TEE leaf" path and instead
**generates** the whole certificate chain and signs it with the keybox key
(`key_db/keystore.db` holds the generated keys). Observed facts:

- The native path works fine (mode A) - the TEE is *not* broken. The flag is
  therefore a **false positive** (TrickyStore's probe likely misdetects this
  Unisoc/Trusty Keymaster 4.0/4.1 mix, or the probe runs before keystore is
  ready).
- Deleting the file / setting `teeBroken=false` and restarting the daemon is
  worth testing: the "patch real leaf" path keeps the device's real key and
  only rewrites the attestation extension, which is much closer to what GMS
  expects than a fully generated chain.
- The generated-chain path is also why `manufacturer` follows the keybox and
  not the device.

### 2026-10-31 - Play Integrity verdicts (the actual blocker)

Baseline **before Magisk** (same checker app, same GMS): BASIC = pass,
DEVICE = fail, STRONG = fail.

After Magisk + TrickyStore, every configuration tried so far returns
**all three red**, including the case where TrickyStore is inert:

| # | TrickyStore state | security_patch.txt | BASIC | DEVICE | STRONG |
|---|---|---|---|---|---|
| 1 | target = gms, vending, gsf, keyattestation | yes (2026-10-05) | fail | fail | fail |
| 2 | same target | removed | fail | fail | fail |
| 3 | target = `# none` (inert) | absent | **fail** | fail | fail |
| 4 | target with `?` suffixes | absent | fail | fail | fail |
| 5 | target = `# none` + Zygisk + DenyList (gms, gms.unstable, vending, gsf) | absent | **fail** | fail | fail |

Screenshots: `D:\AndroidSDKTools\pi\s1.png` (baseline, pre-Magisk: BASIC
green), `s3/s5/s6.png` (TrickyStore active), `s7.png` (inert), `s8.png`
(inert + Zygisk/DenyList). Raw logcat dumps: `log_all.txt`. Cleaned-up
evidence transcript:
[evidence/2026-10-31-play-integrity-session.txt](evidence/2026-10-31-play-integrity-session.txt).

=> The BASIC regression is **not** caused by the keybox/target list: it
appears as soon as Magisk is present, and survives both an inert TrickyStore
*and* a Zygisk DenyList. So the current leading explanations are (a) the
Play Integrity **token request itself errors** in this environment and the
app renders three red crosses, or (b) GMS sees something about the modified
boot image/env that breaks BASIC regardless of process-level hiding.

**Key evidence from logcat for the `s8` run** (Zygisk active, denylist
working - `Magisk: zygisk64: [com.google.android.gms.unstable] is on the
denylist`):

```
I PlayCore: IntegrityService : requestIntegrityToken(IntegrityTokenRequest{...})
I PlayCore: ServiceConnectionImpl.onServiceConnected(
            com.android.vending/com.google.android.finsky.integrityservice.IntegrityService)
I Finsky  : requestIntegrityToken() finished for gr.nikolasspyr.integritycheck.
I PlayCore: OnRequestIntegrityTokenCallback : onRequestIntegrityToken
```

i.e. the request completes in ~1.4 s, no exception, no `ApiException`, and no
error toast - the app is showing a **real verdict token with all verdicts
false**, not an error dialog. That points at (b): Google's server is
rejecting the whole request, most likely because the **DroidGuard/attestation
signals are inconsistent** (keybox profile mismatch or a broken attestation
record), or because the boot image's self-signed AVB key makes GMS report
"modified system" for BASIC.

Also note the Magisk settings DB before this session had **no** `zygisk` and
no `denylist` rows at all - the fresh install had both disabled. Enabled then
with:

```
/debug_ramdisk/magisk --sqlite "REPLACE INTO settings (key,value) VALUES('zygisk','1')"
/debug_ramdisk/magisk --sqlite "REPLACE INTO settings (key,value) VALUES('denylist','1')"
/debug_ramdisk/magisk --denylist add com.google.android.gms
/debug_ramdisk/magisk --denylist add com.google.android.gms com.google.android.gms.unstable
/debug_ramdisk/magisk --denylist add com.android.vending
/debug_ramdisk/magisk --denylist add com.google.android.gsf
```
(CLI accepts `add <pkg> [<proc>]`; `<proc>` must be a real process name -
`*` is rejected by the CLI even though the app UI can store wildcard rows.
Reboot is required for Zygisk to load; confirm with
`logcat | grep "is on the denylist"`.)

### 2026-10-31 12:00-12:15 - **root cause of the all-red regression: permissive SELinux**

The cheapest experiment (hypothesis 0) was decisive.

1. `adb reboot`. Immediately after boot, with **no exploit run in that boot**:
   `getenforce` = **Enforcing**.
2. Checker run (TrickyStore inert, target.txt = `# none`, USNF installed):
   **BASIC = green**, DEVICE = red, STRONG = red. Screenshot `s9.png`.
3. So the earlier "all red" state had nothing to do with the keybox, the
   target list or Magisk: **every one of those five attempts ran after
   `mali_kroot` had set `selinux_state.enforcing = 0`, and DroidGuard treats
   permissive SELinux as tampering.** The regression reproduces exactly:
   permissive -> BASIC red; enforcing -> BASIC green.
4. Consequence for the whole workflow: **do not run `mali_kroot` on a boot
   where an integrity verdict matters.** Use Magisk `su` for root instead
   (does not touch SELinux). Grant it once, from an exploit shell, by writing
   the policy row (persists across boots):

```
/debug_ramdisk/magisk --sqlite "REPLACE INTO policies (uid,policy,until,logging,notification) VALUES (2000,2,0,1,1)"
```

   `policies` schema is `uid|policy|until|logging|notification`, `policy=2`
   means "allow forever" (same encoding as the app's "grant" entry). After a
   reboot with a clean boot:

```
adb shell su -c 'id'      -> uid=0(root) ... context=u:r:magisk:s0
adb shell su -c getenforce -> Enforcing
```

   This is now the standard way to do root work from adb on this device:
   `adb shell "su -c '<cmd>'"`, no exploit, SELinux stays Enforcing.
   (Caveat: `su` needs a single-quoted command and the adb shell itself stays
   uid 2000; `su -c` starts a new `u:r:magisk:s0` context.)

### 2026-10-31 12:08 - state found on re-entry, and what it means

Between two work sessions the device had been changed outside this log:

- **Universal SafetyNet Fix v2.4.0** (`kdrag0n`, module id `safetynet-fix`)
  installed at 11:59. Its `system.prop` contains the classic prop spoofs:
  `ro.boot.verifiedbootstate=green`, `ro.boot.veritymode=enforcing`,
  `vendor.boot.vbmeta.device_state=locked`, `ro.debuggable=0`,
  `ro.secure=1`, `ro.build.tags=release-keys`. Verified live after a boot:
  `getprop ro.boot.verifiedbootstate` -> **green**,
  `getprop ro.boot.flash.locked` -> **1**, `ro.boot.veritymode` -> enforcing,
  `ro.debuggable` -> 0. (The real bootloader state is still unlocked/orange;
  these are `resetprop` values in RAM.)
- Magisk "Systemless hosts" module enabled (12:02).
- DenyList entries changed: the GMS/GSF/Vending rows were **replaced by
  WhatsApp rows**, and su policies exist for `flar2.devcheck` (uid 10225) and
  `com.termux` (uid 10226). Note this is actually *correct* for USNF 2.4.0:
  it needs **Zygisk injection into GMS**, and a package on the DenyList is
  exactly what Zygisk refuses to inject into - so GMS must **not** be on the
  list while USNF is in use. (TrickyStore does not need GMS on the DenyList
  either; it hooks keystore system-side.)

### 2026-10-31 12:10 - TrickyStore active + Enforcing SELinux: BASIC green, DEVICE red

With `target.txt` = gms, vending, gsf, keyattestation:

- KeyAttestation: `Bootloader is locked`, chain = the keybox
  (`Key Attestation CA1` -> `Droid CA2` -> `Droid CA3` -> leaf
  `405d3d10...`, `manufacturer:Xiaomi`, leaf `not after 2026-11-06`),
  `Version: Keymaster 4.1`, `Security level: TrustedEnvironment`,
  key cert validity to 2106 (generated key). Same as before.
- Play Integrity: **BASIC green, DEVICE red, STRONG red** (screenshot
  `s10.png`). This is the same verdict as with USNF alone and with TrickyStore
  inert - i.e. TrickyStore is currently adding nothing.

### 2026-10-31 12:12 - `teeBroken` cannot be overridden by editing the file

- Wrote `teeBroken=false` to `/data/adb/tricky_store/tee_status`, killed the
  daemon (`kill -9 $(pidof TrickyStore)`; the `service.sh` loop then exits,
  as designed, because the daemon returned non-zero), restarted it manually
  (`cd /data/adb/modules/tricky_store && nohup ./daemon >/data/local/tmp/tricky_daemon.log 2>&1 &`).
- After ~4 s the daemon **rewrote the file back to `teeBroken=true`**: the
  value is the result of a live keystore probe, not a config knob. To get the
  "patch the real leaf" path we would have to fix the probe itself (or use a
  different implementation - see TEESimulator / TEESimulator-RS).
- Practical note: starting the daemon from an interactive `adb shell` keeps
  that shell alive (`nohup ... &` inherits the adb pty), which made the
  command appear to hang until timeout. The daemon itself is fine; the log is
  `/data/local/tmp/tricky_daemon.log`. Prefer restarting by reboot.

### 2026-10-31 12:19-12:40 - A/B matrix with raw verdicts (SPIC) and Shamiko

Installed **SPIC v1.4.0** (`com.henrikherzig.playintegritychecker`,
github.com/herzhenr/spic-android) - unlike the nikolas checker it prints the
raw `deviceIntegrity.deviceRecognitionVerdict`, which removes all guessing
about what the three colored rows mean. Verdict matrix so far (all on fresh
boots, SELinux Enforcing, no `mali_kroot` in the boot):

| config | verdict |
|---|---|
| TrickyStore only (USNF disabled) - s12 | `[]` (NO_INTEGRITY) |
| USNF only (TrickyStore disabled) - s14/s15 | `[]` (NO_INTEGRITY) |
| USNF + TrickyStore, denylist=1, GMS **not** in list - s16 | `[MEETS_BASIC_INTEGRITY]` |
| USNF + TrickyStore, denylist=1, **GMS + :unstable in list** - s17 | `[]` (NO_INTEGRITY) |
| + Shamiko 1.2.5, denylist=1 - s18 | `[MEETS_BASIC_INTEGRITY]` |
| + Shamiko, denylist=0 (enforcement off) - s19 | `[MEETS_BASIC_INTEGRITY]` |

Conclusions:

1. **USNF's prop spoof is load-bearing for BASIC** on this device: without it
   (s12) the verdict is empty even though TrickyStore is serving a full
   keybox chain to GMS. DroidGuard evidently also reads `ro.boot.*` /
   `ro.debuggable` etc., and `orange`/`0` fails the check.
2. **Magisk's enforced DenyList is what breaks TrickyStore** (s17): with GMS
   on the enforced list, Magisk's denylist daemon prevents Zygisk module
   injection into `com.google.android.gms`, so TrickyStore's keystore hook
   never runs there and the verdict collapses to NO_INTEGRITY. This is the
   classic "Enforce DenyList vs Zygisk modules" conflict.
3. **Shamiko 1.2.5** (module id `zygisk_shamiko`, installed via
   `magisk --install-module`) resolves the conflict: with Shamiko present the
   enforced DenyList no longer blocks module injection (s18 BASIC green).
   Shamiko's own mode is: Zygisk ON, *Enforce DenyList OFF*, denylist table
   = its hide list.
4. Odd observation: the `com.google.android.gms` +
   `com.google.android.gms.unstable` denylist rows that existed during the
   s17 boot were **gone** after the next reboot (before s18). Nothing in the
   session removed them; possibly a Magisk-app interaction. Noted as
   unexplained; it did not matter because Shamiko was already active.
5. A Magisk-settings DB footgun worth recording: `--sqlite "REPLACE INTO
   settings ... VALUES(0x64656e796c697374,0)"` does **not** match the text
   key `denylist` - SQLite stores the hex literal as the *integer*
   7234309844229518196, which TEXT affinity converts to that decimal string,
   creating a junk row. Use a quoted text key (`VALUES("denylist",0)`) or
   the CLI (`magisk --denylist disable`). The junk row was deleted.

**Current working BASIC stack:** Magisk 31.1 + Zygisk + USNF 2.4.0 (props)
+ TrickyStore 1.4.1 (attestation) + Shamiko 1.2.5 (hiding), SELinux
Enforcing, no exploit in the boot. Reproducible across three boots.

**DEVICE is still missing** (`deviceRecognitionVerdict =
[MEETS_BASIC_INTEGRITY]` only, s16/s18/s19). The Megatron keybox (Xiaomi RKP
leaf `405d3d10...`, valid 2026-10-25..2026-11-06) does not produce
MEETS_DEVICE_INTEGRITY - consistent with it being revoked/profile-mismatched
on Google's side. DEVICE now hinges entirely on a *valid, non-revoked*
keybox; the rest of the stack is in place.

### 2026-10-31 12:41-13:05 - PIFork v18 + keybox/fingerprint A/B (s20-s28)

Replaced the 2022-era props layer with the current standard. Installed
**PlayIntegrityFork v18** (osm0sis, `playintegrityfix` module id); its
installer auto-removes USNF on next reboot (it flags USNF as conflicting).
Generated a fingerprint with `autopif4.sh --strong` from the module dir:
Pixel Canary `ZP11.260918.007`, `SECURITY_PATCH=2026-10-05`, estimated expiry
2026-11-18; it also auto-synced TrickyStore's `security_patch.txt`
(`all=2026-10-05`) and killed the GMS/vending processes. GMS was re-added to
the denylist table (Shamiko's hide list, enforcement stays OFF).

Verdict matrix extension (all boots SELinux Enforcing, SPIC raw verdicts):

| config | verdict |
|---|---|
| PIF + TrickyStore + **AOSP default keybox** - s20-s23 | `[MEETS_BASIC_INTEGRITY]` |
| PIF + TrickyStore + **Megatron keybox** - s24-s26 | `[MEETS_BASIC_INTEGRITY]` |
| **PIF alone** (TrickyStore disabled) - s27-s28 | `[MEETS_BASIC_INTEGRITY]` |

Notes and conclusions:

1. The TrickyStore default `keybox.xml` is the **AOSP software attestation
   root** (KeyAttestation labels it exactly that: "Private key of attestation
   key is well-known"). It produces the same verdict as the Megatron keybox -
   i.e. swapping keyboxes alone does not unlock DEVICE here.
2. **PIF alone still gives BASIC** on this device (unlike USNF alone, which
   gave NO_INTEGRITY in s14/s15) - PIF's prop spoofing is strictly stronger.
   But DEVICE still fails without TrickyStore, consistent with the real
   (unspoofed) key attestation from the broken TEE leaking
   `verifiedBootState=ORANGE` to GMS.
3. PIF is verifiably active: verbose logs (`verboseLogs=1` in
   `custom.pif.prop`, tag `PIF/Native`) show it hooks both
   `com.android.vending` and `com.google.android.gms.unstable`, parses the
   23-key config, and converts prop->JSON format. The raw verdict JSON is
   also visible in logcat via PlayCore/System.out:
   `"deviceRecognitionVerdict": ["MEETS_BASIC_INTEGRITY"]`.
4. Therefore **DEVICE is neither a fingerprint problem nor a keybox-swap
   problem** on this Android 11 device. Remaining explanations, in order:
   (a) the Megatron keybox is revoked/profile-mismatched server-side (leaf
   expires 2026-11-06) - needs a fresh, valid, profile-matched keybox;
   (b) Play Protect *certification status* is a server-side per-device flag
   (visible in Play Store settings) that PIF cannot change;
   (c) DroidGuard's 2026 checks in GMS 26.43.30 require more than the classic
   legacy path on A11.

**State at wrap-up (2026-10-31 ~13:05):** stack = Magisk 31.1 + Zygisk +
PIFork v18 (Pixel Canary fingerprint, exp ~2026-11-18) + TrickyStore 1.4.1
(Megatron keybox restored from backup, md5-verified) + Shamiko 1.2.5;
denylist enforcement OFF, GMS on the Shamiko hide list; SELinux Enforcing.
TrickyStore's `disable` marker was removed after the PIF-alone test, so it
re-activates on the next reboot; the current boot passes BASIC with PIF
alone. BASIC is stable; DEVICE remains unsolved pending a valid keybox.

## 8. Working hypotheses (in order of likelihood)

0. **SELinux Permissive - CONFIRMED 2026-10-31 12:08.** `mali_kroot` flips
   `selinux_state.enforcing` to 0 in RAM and it stays Permissive until reboot
   (`getenforce` -> `Permissive`, confirmed 2026-10-31 12:05). Every Play
   Integrity attempt in this session happened *after* an exploit run, i.e.
   with SELinux Permissive; the pre-Magisk baseline (BASIC = pass) was
   measured on a fresh boot with SELinux Enforcing. DroidGuard is known to
   treat permissive SELinux as tampering, which would explain why BASIC goes
   red regardless of the TrickyStore configuration - and why the regression
   looked like "Magisk's fault". Test = reboot and check PI *before* touching
   the exploit (Magisk root via `su` does not need permissive).
   **Result: permissive -> BASIC red; Enforcing -> BASIC green, reproducibly.
   This hypothesis is closed: never run the exploit before an integrity
   check; use `adb shell "su -c ..."` (policy row for uid 2000).**
1. **Keybox/device profile mismatch (most likely, DEVICE)** - the attestation
   record says `manufacturer:Xiaomi`, `Keymaster 4.0`, RKP `Droid CA3`; the
   device is Motorola/hawaii/Keymaster 4.0-4.1 with a 2024-02 patch. Google
   can compare the attested `ro.product.*`, `os_version`, `os_patch_level`,
   `vendor_patch_level`, `boot_patch_level` with what GMS/Play reports for
   the account/device. Fix: use a keybox whose profile matches (Motorola,
   Android 11, 2024-02) **or** spoof the props to match the keybox (Xiaomi
   Android 13/14 fingerprint + patch levels) with PIF/Integrity-Box, and/or
   set `security_patch.txt` + `boot_props` so everything agrees.
2. **`teeBroken=true` forces the generated-chain path** - a generated chain
   with a keybox leaf may be rejected because the *key usage / attestation
   record* does not look like a real TEE output (e.g. `Security level`
   `TrustedEnvironment` but no real TEE binding, or missing
   `attestationSecurityLevel` bits). Fix: force the "patch real leaf" path
   (delete/repair `tee_status`, `!`/no-suffix targets), or use TEESimulator-RS
   which is designed to re-sign a *real* TEE leaf.
3. **BASIC regression is boot-image related** - the AVB footer is signed with
   a throwaway key, so the device is "unverified boot, unknown key". Root
   hiding (DenyList/Shamiko) does not change what the bootloader/TrustOS
   reports. Fix candidates: make the boot image's vbmeta chain look like the
   stock OEM one (impossible without the OEM key), or make GMS believe
   `verifiedBootState=green` via TrickyStore + `boot_props_mode`, or accept
   that BASIC needs a `ro.boot.*` prop spoof (Magisk `resetprop` at
   post-fs-data, which affects new processes only).
4. **USNF vs TrickyStore - DISPROVED as a conflict (2026-10-31 12:40).**
   The A/B matrix shows the opposite: they are *complementary*. USNF alone
   (s14) and TrickyStore alone (s12) both give NO_INTEGRITY; only the
   combination gives BASIC (s16). USNF covers the `ro.boot.*`/build-prop
   surface that DroidGuard checks locally; TrickyStore covers the
   keystore/attestation surface. What *did* break BASIC was Magisk's
   **enforced DenyList** blocking TrickyStore's injection into GMS (s17),
   fixed by Shamiko (s18).
5. **GMS-side cached device state** - Play Integrity caches "device
   integrity" server-side for a while; after switching the boot image the
   cached state may stay bad for hours. Worth re-testing after 12-24 h and
   after clearing GMS data (`pm clear com.google.android.gms` is risky - it
   removes the account registration, re-login needed).

## 9. Ordered next steps

Ordered, cheapest/most informative first:

0. **DONE (2026-10-31 12:08): clean boot gives BASIC green.** Root cause of
   the all-red state = permissive SELinux. From now on: root work through
   `adb shell "su -c ..."` (policy row for uid 2000 already added), never
   through `mali_kroot` on a boot where a verdict matters.

0b. **DONE (2026-10-31 12:40): USNF/TrickyStore A/B matrix + Shamiko.**
   USNF and TrickyStore are complementary, not conflicting (both needed for
   BASIC). The real BASIC killer was the enforced DenyList blocking
   TrickyStore's injection into GMS; Shamiko 1.2.5 installed, DenyList
   enforcement now OFF (`denylist=0`), BASIC stable across three boots
   (s16/s18/s19). SPIC installed for raw-verdict readings.

1. **DEVICE: validate/replace the keybox (the only remaining blocker).**
   The Megatron keybox does not yield MEETS_DEVICE_INTEGRITY and its leaf
   expires 2026-11-06. Steps: (a) run a keybox validity check (e.g.
   chiteroman's KeyboxChecker or an online checker) to distinguish
   "revoked/banned" from "profile mismatch"; (b) if banned, a fresh valid
   keybox is required (user-supplied); (c) re-test SPIC after swapping
   `/data/adb/tricky_store/keybox.xml` (no reboot needed - the daemon
   reloads the file, but a reboot is the clean way).
2. **DONE (2026-10-31 12:45): props layer modernized.** PlayIntegrityFork
   v18 (osm0sis) installed; its installer auto-removed USNF. `autopif4.sh
   --strong` generated a Pixel Canary fingerprint (`ZP11.260918.007`, patch
   2026-10-05, est. expiry 2026-11-18) and synced TrickyStore's
   `security_patch.txt`. Verdict unchanged: BASIC only (s20-s28) - see the
   12:41-13:05 section above for the full A/B matrix.
3. **Check whether GMS consumes TrickyStore's chain at all** (only needed if
   the keybox swap does not move the verdict): (a) `logcat | grep -iE
   "tricky|keymaster|attest"` while the checker runs; (b) SPIC's raw JSON
   already shows the verdict shape - `deviceRecognitionVerdict` labels are
   the whole signal.
2. **Test `tee_status` override**: `echo teeBroken=false >
   /data/adb/tricky_store/tee_status` (or delete it), restart the daemon,
   re-run KeyAttestation. If the chain then keeps the device's real leaf and
   only the extension is patched, re-test PI.
3. **Try a profile-matching keybox** - `LufsX/keybox-lite`,
   `rawbin.dpejoh.com/catalog`, or the T.A.K.R. site with captcha; prefer one
   whose leaf says Motorola (or at least not Xiaomi) and whose validity is
   long. Rotate before 2026-11-06 anyway.
4. **Add a props layer** (Play Integrity Fix or Integrity-Box) with a
   fingerprint that matches the keybox profile and recent patch levels; also
   spoof `ro.boot.verifiedbootstate=green`, `ro.boot.flash.locked=1`,
   `ro.boot.vbmeta.device_state=locked` via `resetprop` in
   `post-fs-data.d` (note: `ro.boot.*` are read-only properties set by init
   from the kernel cmdline - `resetprop` can still change them in memory for
   new processes, but a mismatch with `/proc/cmdline` can itself be a tell).
5. **Try TEESimulator-RS 6.0.1** instead of TrickyStore: it re-signs the real
   TEE leaf and has `boot_props_mode` for `ro.boot.*` spoofing; on this device
   the TEE is healthy, so it may produce a *more* consistent record than
   TrickyStore's generated chain. Keep TrickyStore installed but disabled
   (Magisk module toggle) for A/B comparison.
6. **Revert Magisk to isolate the trigger** (only if step 0 does not explain
   it): temporarily boot a stock, signed-only boot image
   (`artifacts/kernel-build/boot_stock_signed.img`, proven to boot) and re-run
   the checker, again *without* running the exploit. If BASIC goes green, the
   trigger is the Magisk ramdisk/module set; if it stays red, the trigger is
   somewhere else (GMS state, account, earlier keybox experiments). Costs one
   reboot write to `boot_b` (slot b one-attempt block first, `boot_a` rescue
   stays in place).
   Second variant of the same test, no flashing: disable the TrickyStore
   module (`touch /data/adb/modules/tricky_store/disable`, reboot) and check
   PI with Magisk alone.
7. Only after BASIC is green: re-add `security_patch.txt`
   (`system=2026-10-05`, `vendor=2026-10-05`, `boot=2026-10-05`), re-add the
   targets, and test DEVICE/STRONG.

## 10. Repro cheat sheet

```bash
# root shell for one command batch
MSYS_NO_PATHCONV=1 adb shell 'set -e; /data/local/tmp/mali_kroot >/dev/null 2>&1; <cmds>'

# TrickyStore state
cat /data/adb/tricky_store/target.txt /data/adb/tricky_store/tee_status
ps -A | grep TrickyStore

# change target list, then relaunch the app that checks (no reboot needed)
printf "com.google.android.gms\ncom.android.vending\n" > /data/adb/tricky_store/target.txt

# UI: run checker and read verdicts
adb shell am start -n gr.nikolasspyr.integritycheck/.MainActivity
adb shell input tap 360 1056          # CHECK
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png D:/AndroidSDKTools/pi/
```

## 11. File inventory for this work

| path | what |
|---|---|
| `D:\AndroidSDKTools\pi\Magisk-v31.1.apk` | Magisk manager |
| `D:\AndroidSDKTools\pi\TrickyStore.zip` | TrickyStore 1.4.1 module |
| `D:\AndroidSDKTools\pi\keybox_meow.xml` | decoded `Megatron` keybox (expires 2026-11-06) |
| `D:\AndroidSDKTools\pi\magisk_patched_raw.img` | Magisk `boot_patch.sh` output, stale OEM footer |
| `D:\AndroidSDKTools\pi\boot_magisk_avb.img` | **flashed to `boot_b`** (sha256 `90416c09...`) |
| `D:\AndroidSDKTools\pi\KeyAttestation.apk`, `checker.apk` | verification apps |
| `D:\AndroidSDKTools\pi\s1..s8.png`, `log_all.txt` | evidence |
| `D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\boot_b.img` | stock `boot_b` (sha256 `ccd0faff...`) |
