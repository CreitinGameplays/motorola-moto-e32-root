# motorola-moto-e32-root

Runtime root on the **Motorola Moto E32 (XT2227-1, "hawaii", Unisoc T606)**
without unlocking the bootloader, via the ARM Mali GPU use-after-free
**CVE-2021-28663 / CVE-2021-28664**.

The exploit turns the Mali `kbase` UAF into kernel physical read/write, then
patches its own `cred` (uid/gid/capabilities) and `selinux_state.enforcing`.
Root survives until reboot and is inherited by the parent adb shell.

> **Status:** working and hardened. Final build verified **5/5 fresh boots and
> 3/3 same-boot reruns**, first attempt, 2–5 s per run, no panic.
> Root is **runtime only** - nothing is flashed.
>
> **Update:** the bootloader is now also unlocked, purely in software, using
> the runtime root to mint the secure-world `VerifiedBoot-UNLOCK` marker into
> `miscdata`. See `docs/07-unlock-how-to.md` and
> `docs/06-secure-world-unlock-path.md`.

## Target

| | |
|---|---|
| Device | Motorola Moto E32, XT2227-1, codename `hawaii` |
| SoC / GPU | Unisoc UMS9230 / T606, ARM64, Mali-G57 (Valhall, JM), kbase DDK r28p0 |
| OS | Android 11, build `RORS31.335-58-1`, security patch 2024-02-05 |
| Kernel | Linux 4.14.199+ (`#1 SMP PREEMPT`), KASLR effectively disabled |
| Bootloader | unlocked in software (`ro.boot.flash.locked=0`, `verifiedbootstate=orange`) |
| Access needed | USB debugging, `adb` shell (uid 2000); **no** unlock, **no** root |

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
- Bootloader **can stay locked**

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
  05-bootloader-unlock-research.md  bootloader unlock feasibility (negative result)
  06-secure-world-unlock-path.md  secure-world SMC signing oracle -> unlock
  07-unlock-how-to.md       step-by-step software bootloader unlock
  evidence/                 captured successful-run logs
scripts/
  mali/                     target-side C: exploit + primitive probes
  host/                     host-side Python helpers
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

Reboot to remove root.

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
and `docs/07-unlock-how-to.md`. Note that fastboot flashing stays
signature-gated; only the boot-time AVB policy changes.

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

- Root is **in RAM only**: `cred` and `selinux_state` changes are lost on reboot.
- The shell keeps the `u:r:shell:s0` SELinux context; permissive mode makes
  that sufficient for DAC/capability access, not a policy come domain.
- `CONFIG_STATIC_USERMODEHELPER=y` makes the classic `modprobe_path` trick
  unusable (not needed here).
- The bootloader is **not** unlocked and no boot image is flashed, by design
  (brick risk on a locked bootloader). Why unlocking is not reachable is
  analysed in `docs/05-bootloader-unlock-research.md`.

## Documentation

- `docs/00-device-profile.md` - device, firmware, security posture, limits
- `docs/01-mali-cve-2021-28663.md` - vulnerability and proven primitives
- `docs/02-kallsyms-and-kernel-image.md` - kallsyms/Image recovery
- `docs/03-root-exploit.md` - the complete exploit chain and offsets
- `docs/04-reliability-hardening.md` - failure analysis and hardening
- `docs/05-bootloader-unlock-research.md` - bootloader unlock feasibility
- `docs/evidence/` - captured successful-run logs and fastboot recon

## License

[MIT](LICENSE). The vulnerability research is provided for education and
security testing on devices you own; use it only on hardware you are allowed
to modify.
