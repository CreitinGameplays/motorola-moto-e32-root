# motorola-moto-e32-root

> Note: The main host used was Windows 10 and some of the required files (such as Android SDK, firmware files and others) were moved to an external disk (D:) to save C: storage space.

Runtime root on the **Motorola Moto E32 (XT2227-1, "hawaii", Unisoc T606)**
via the ARM Mali GPU use-after-free **CVE-2021-28663 / CVE-2021-28664**, and
persistent **Magisk** root on the same device.

The exploit turns the Mali `kbase` UAF into kernel physical read/write, then
patches its own `cred` (uid/gid/capabilities) and `selinux_state.enforcing`.
Root survives until reboot and is inherited by the parent adb shell.

> **Status (2026-10-31): two root paths are live on this unit.**
>
> 1. **Runtime root (the exploit)** - working and hardened. Final build
>    verified **5/5 fresh boots and 3/3 same-boot reruns**, first attempt,
>    2-5 s per run, no panic. It needs no unlock and no pre-existing root and
>    it writes nothing to flash, but the elevation is **lost on reboot**.
> 2. **Persistent root (Magisk 31.1)** - the device's current state. A
>    Magisk-patched `boot_b` (stock kernel, patched ramdisk) is flashed, so
>    root survives reboots and Zygisk modules can run. The bootloader is
>    unlocked (software `VerifiedBoot-UNLOCK` marker in `miscdata`).
>    Module stack and Play Integrity results: `docs/15-play-integrity.md`;
>    how the image was flashed: `docs/12-slot-b-testing-channel.md`.
>
> **Careful:** the runtime exploit clears `selinux_state.enforcing`, leaving
> SELinux **Permissive** until the next reboot. That is a tamper signal and it
> breaks Play Integrity's BASIC verdict - on any boot where an integrity
> verdict matters, use Magisk `su` instead of the exploit.
>
> **Update:** the bootloader is unlocked in software, using the runtime root
> to mint the secure-world `VerifiedBoot-UNLOCK` marker into `miscdata`. See
> `docs/07-unlock-how-to.md` and `docs/06-secure-world-unlock-path.md`.
>
> **Proof:** an Android 15 GSI with no Motorola signature now boots on the
> device (`ro.boot.flash.locked=0`, `verifiedbootstate=orange`,
> `vbmeta.device_state=unlocked`) - see `docs/09-gsi-proof.md`.

## Target

| | |
|---|---|
| Device | Motorola Moto E32, XT2227-1, codename `hawaii` |
| SoC / GPU | Unisoc UMS9230 / T606, ARM64, Mali-G57 (Valhall, JM), kbase DDK r28p0 |
| OS | Android 11, build `RORS31.335-58-1`, security patch 2024-02-05 |
| Kernel | Linux 4.14.199+ (`#1 SMP PREEMPT`), KASLR effectively disabled |
| Bootloader | unlocked in software (`ro.boot.flash.locked=0`, `verifiedbootstate=orange`) |
| Current root | Magisk 31.1 (patched `boot_b`, slot `_b`), Zygisk Next 1.5.2 + modules; the exploit is kept as an independent path |
| Access needed | USB debugging, `adb` shell (uid 2000); the exploit needs **no** unlock and **no** pre-existing root |

Kernel addresses and struct offsets in the exploit are hardcoded for this
firmware. Other builds need their symbols re-derived - see
`docs/02-kallsyms-and-kernel-image.md`.

## Requirements

**Host**
- `git`
- `adb` (Android platform-tools) with the device authorized
- Android **NDK** with the LLVM toolchain (tested with r27c; any recent NDK is
  expected to work); `ANDROID_NDK_HOME` must point at it
- Windows PowerShell 5.1+ or Linux/macOS with `bash`
- Optional: Python 3 + `vmlinux-to-elf` (only to re-derive symbols/offsets)

**Device**
- Moto E32 XT2227-1 on the firmware above (`adb shell getprop ro.build.fingerprint`)
- USB debugging enabled, host key authorized
- Bootloader: the exploit works whether it is locked or unlocked (this unit has
  since been unlocked in software - see `docs/07-unlock-how-to.md`)

## Repository layout

```
README.md
LICENSE                     MIT
docs/
  00-device-profile.md      hardware, security posture, access restrictions
  01-mali-cve-2021-28663.md vulnerability, trigger order, primitives
  02-kallsyms-and-kernel-image.md  symbol/offset recovery
  03-root-exploit.md        full exploit write-up
  04-reliability-hardening.md  failure modes, fixes, measurements
  05-bootloader-unlock-research.md  initial unlock research: why the key/legacy routes fail
  06-secure-world-unlock-path.md  secure-world SMC signing oracle -> unlock
  07-unlock-how-to.md       step-by-step software bootloader unlock
  08-debloat.md             Motorola/OOBE/Facebook bloat removal
  09-gsi-proof.md           a GSI boots = independent proof of the unlock
  10-kernel-source.md       the full kernel source: where it is, how it was
                            verified against the phone, and the measured gap
                            to the shipped build (closed by patches/kernel-sprd)
  11-flash-gate.md          the fastboot download gate and how it was decoded
  12-slot-b-testing-channel.md  boot_a rescue image + slot_b as the test channel
  13-recovery-bootrom.md    bootROM/FDL route analysis
  14-brom-recovery-runbook.md  bootROM recovery runbook
  15-play-integrity.md      Magisk root + Play Integrity work log (BASIC pass)
  evidence/                 captured successful-run logs
patches/
  kernel-sprd/              the measured header delta (git patch) + the
                            reconstructed production config fragment
scripts/
  mali/                     target-side C: exploit + primitive probes
  host/                     host-side Python/PowerShell helpers
  device/                   on-device helper scripts (unlock, DT dump, ...)
  build.ps1 / build.sh      build the exploit with the NDK
  run_matrix.ps1            reliability matrix (N boot + run cycles)
artifacts/                  local build output and dumps (gitignored)
tools/, apks/, ...          local working data (gitignored)
```

## Step-by-step

### 1. Get the source and toolchain

```bash
git clone git@github.com:CreitinGameplays/motorola-moto-e32-root.git
cd motorola-moto-e32-root

# Android NDK: download from developer.android.com/ndk and set the path
export ANDROID_NDK_HOME=/path/to/android-ndk     # PowerShell: $env:ANDROID_NDK_HOME = "..."
```

### 2. Build

```bash
# Linux / macOS
./scripts/build.sh

# Windows PowerShell
.\scripts\build.ps1
```

Output: `artifacts/mali_kroot` (static aarch64 binary). To build another probe:

```bash
SOURCE=scripts/mali/mali_rwtest3.c OUT=artifacts/mali_rwtest3 ./scripts/build.sh
.\scripts\build.ps1 -Source .\scripts\mali\mali_rwtest3.c -Out .\artifacts\mali_rwtest3
```

### 3. Connect the device

```bash
adb devices                       # device must be listed as "device"
adb shell getprop ro.build.fingerprint
adb shell id                      # uid=2000(shell)
```

### 4. Run the exploit

```bash
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
adb shell chmod 755 /data/local/tmp/mali_kroot
adb shell /data/local/tmp/mali_kroot
```

Do **not** pipe the output through `head`/`Select-Object -First N`: closing the
stream kills the process mid-run and skips the mandatory PTE teardown. If that
happens, reboot the device.

Expected key lines:

```
[+] validated pg=0x... probe=9 pte=... (live PTE page confirmed)
[+] cand pg=0x... i=... slots=.../... high=0xe8000000000000 low=0xf53
[+] cred patched (readback uid=0 gid=0 cap_eff=3fffffffff)
[+] selinux enforcing now: 00 00 00 01
uid=0(root) gid=0(root) groups=0(root),... context=u:r:shell:s0
Permissive
```

A run takes about 2–5 s. If no live PTE page is found, the tool re-arms the
Mali context and retries (up to 4 attempts).

### 5. Verify

The adb shell session (and its children) is now root:

```bash
adb shell "id; getenforce; id -u"
# uid=0(root) ... Permissive ... 0
```

Reboot to remove **this** root - the `cred`/`selinux_state` patches live in
RAM only. (The device's *persistent* root comes from Magisk and is unaffected;
see `docs/15-play-integrity.md`.) Note that running the exploit leaves SELinux
Permissive until the reboot, which is a tamper signal for Play Integrity.

### 6. (Optional) reliability matrix

Starts from a fresh boot each cycle and reports success:

```powershell
.\scripts\run_matrix.ps1                 # 5 cycles, reboot each
.\scripts\run_matrix.ps1 -Cycles 3 -NoReboot
```

### 7. (Optional) software bootloader unlock

With root, the bootloader's verified-boot policy can be changed permanently:
the secure world signs `"VerifiedBoot-UNLOCK"` with a chip-unique HUK-derived
key, and that 64-byte marker is what U-Boot validates against `miscdata`
offset `0x2000` on every boot. The signing SMC is not gated on lock state, so
a rooted kernel can mint the marker itself.

```bash
adb push artifacts/sip_page   /data/local/tmp/sip_page
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
python scripts/host/unlock_marker.py            # dry run
python scripts/host/unlock_marker.py --flash    # writes miscdata 0x2000
```

Then wipe `/data` once from stock recovery (same as a normal unlock) and
reboot: `ro.boot.flash.locked=0`, `verifiedbootstate=orange`, and U-Boot logs
`WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!`. The full mechanism,
constraints and the step-by-step are in `docs/06-secure-world-unlock-path.md`
and `docs/07-unlock-how-to.md`. Only the boot-time AVB policy changes - the
fastboot *download* gate is a separate mechanism and was still refusing
unsigned requests when last probed.

The functional proof: with the marker in place an **Android 15 GSI boots**
(a system image with no Motorola signature), installed with
[DSU-Sideloader](https://github.com/VegaBobo/DSU-Sideloader) - see
`docs/09-gsi-proof.md`.

## How it works (short version)

1. **CVE-2021-28663 UAF** - a 32 MB native Mali region is aliased, then marked
   `BASE_MEM_DONT_NEED`. While the kernel reclaims memory, the kbase shrinker
   frees the native pages but the alias (CPU + GPU mappings) keeps using them.
2. **Page-table spray** - 15360 x 2 MB anonymous chunks, tagged with markers at
   two pages per chunk, reclaim the freed pages as the *page-table pages* of
   those chunks.
3. **Validated PTE hijack** - the candidate PTE page is proven live by faulting
   one untouched page through our own mapping (*read-only*, before any write),
   then a GPU `WRITE_VALUE` job rewrites a PTE. That maps any physical page into
   our address space with user RW permissions: **arbitrary kernel physical
   read/write**.
4. **Privilege escalation** - walk `init_task.tasks`, find our task via `comm`,
   patch `cred` (uid/gid = 0, caps `0x3fffffffff`) and the parent shell's cred,
   then clear `selinux_state.enforcing`.

The full chain, offsets and reasoning are in `docs/03-root-exploit.md`;
hardening and measured reliability are in `docs/04-reliability-hardening.md`.

### Hardening highlights

- candidates are **validated read-only** before the first write (no writes into
  stale/reclaimed pages),
- physical/kernel addresses are range-checked (`MemFree`-independent, correct
  4 GiB linear-map span),
- memory pressure is driven to the watermark so the kbase shrinker actually
  evicts the pages (`pressure_fill`),
- the alias is re-scanned every spray round (early pages often become live
  candidates only later),
- every hijacked PTE line is GPU-zeroed and cache-thrashed on exit.

## Troubleshooting

| symptom | meaning / fix |
|---|---|
| `validated pg=... probe entry absent` repeatedly | system memory pressure was not reached; the tool retries with fresh pressure. If all attempts fail, reboot and rerun |
| `all attempts failed` | same as above - reboot is the reliable reset (kbase pool/shrinker state) |
| `already root` / `enforcing byte != 1` | the session (or SELinux) was already elevated - normal on reruns; reboot to test the full chain |
| exploit killed mid-run | PTE teardown did not run - **reboot** before continuing |
| `getenforce` still `Enforcing` | SELinux byte at `selinux_state+1` was not 1; check the build/firmware matches |
| device panic | only seen with older, unhardened builds; the final build is validated |

## Limits / notes

- The **exploit**'s root is **in RAM only**: `cred` and `selinux_state`
  changes are lost on reboot. The **Magisk** root on this unit is persistent
  (patched `boot_b`) - the two paths are independent.
- The exploit shell keeps the `u:r:shell:s0` SELinux context; permissive mode
  makes that sufficient for DAC/capability access, not a policy come domain.
  Magisk's `su` does give a policy-correct `u:r:magisk:s0` shell.
- `CONFIG_STATIC_USERMODEHELPER=y` makes the classic `modprobe_path` trick
  unusable (not needed here).
- The runtime exploit does not need an unlocked bootloader and no boot image is
  flashed by it. This unit's bootloader was later unlocked **in software**
  (`miscdata` marker - see `docs/07-unlock-how-to.md`) and a Magisk-patched
  `boot_b` was flashed afterwards (see `docs/12-slot-b-testing-channel.md`);
  `boot_a` holds the proven rescue/restore image. The key/legacy unlock routes
  are dead ends (`docs/05-bootloader-unlock-research.md`), and the separate
  fastboot *download* gate still rejects unsigned images, so "unlocked" here
  means the verified-boot/AVB policy is skipped, not that arbitrary fastboot
  flashing works.
- The device boots Android with the bootloader unlocked, so Play Integrity
  cannot reach MEETS_DEVICE_INTEGRITY without spoofing; the current stack
  reaches **MEETS_BASIC_INTEGRITY** (`docs/15-play-integrity.md`).

## Documentation

- `docs/00-device-profile.md` - device, firmware, security posture, limits
- `docs/01-mali-cve-2021-28663.md` - vulnerability and proven primitives
- `docs/02-kallsyms-and-kernel-image.md` - kallsyms/Image recovery
- `docs/03-root-exploit.md` - the complete exploit chain and offsets
- `docs/04-reliability-hardening.md` - failure analysis and hardening
- `docs/05-bootloader-unlock-research.md` - bootloader unlock feasibility
- `docs/07-unlock-how-to.md` - step-by-step software bootloader unlock
- `docs/10-kernel-source.md` - the full kernel source: Motorola/Unisoc
  `kernel-sprd` @ `R-11-release-RORS`, verified against the phone (config,
  Kconfig, headers, device tree) plus the measured gap to the shipped build
- `docs/11-flash-gate.md` - the fastboot download gate and how it was decoded
- `docs/12-slot-b-testing-channel.md` - the `boot_a` rescue image and using
  `boot_b` as the kernel-testing channel
- `docs/13-recovery-bootrom.md` / `docs/14-brom-recovery-runbook.md` - the
  bootROM/FDL route and its runbook
- `docs/15-play-integrity.md` - Magisk root on the unlocked device: module
  stack, Play Integrity verdicts (BASIC passes, DEVICE still open)
- `docs/evidence/` - captured successful-run logs and fastboot recon

## Kernel source

The device runs the Motorola/Unisoc **4.14.199 "Petit Gorille"** kernel
(qogirl6 / UMS9230 = T606). The GPL source is public:

```powershell
.\scripts\host\get_kernel_source.ps1     # -> D:\AndroidSDKTools\kernel-sprd
```

It is verified against the phone on five axes (build config, Kconfig symbol
coverage, 4,852/4,852 header match, device tree, version string). The delta
between the published 2022-10 snapshot and the shipped Feb-2024 build was
measured and is closed: `patches/kernel-sprd/` holds the 7-header backport and
the reconstructed production config fragment. Full write-up:
`docs/10-kernel-source.md`.

## License

[MIT](LICENSE). The vulnerability research is provided for education and
security testing on devices you own; use it only on hardware you are allowed
to modify.
