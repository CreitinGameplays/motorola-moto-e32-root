# Device Profile: Motorola Moto E32 (XT2227-1, "hawaii")

## Hardware / build
- Model: moto e32 (XT2227-1), codename `hawaii`
- SoC: Unisoc UMS9230 / T606 (qogirl6 platform), ARM64
- GPU: ARM Mali-G57 (Valhall, JM-based, DDK r28p0)
- RAM: 4 GB class
- Android 11, kernel 4.14.199
- Build: `RORS31.335-58-1`, fingerprint `motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys`, slot `_b`
- Kernel build: `Linux version 4.14.199+-ab612c2 (xscm@ontimbjlx020) (Android clang 11.0.1 r383902) #1 SMP PREEMPT Tue Feb 20 11:32:22 CST 2024`
- Security patch: 2024-02-05
- `ro.debuggable=0`, `ro.adb.secure=1`, ADB shell runs as uid 2000

## Security posture
- **As shipped:** bootloader locked, AVB green, dm-verity enforcing, SELinux
  enforcing.
- **Current state of the test device (2026-10-29):** bootloader unlocked in
  software (`ro.boot.flash.locked=0`, `verifiedbootstate=orange`,
  `vbmeta.device_state=unlocked`). SELinux is still `Enforcing` at boot; the
  runtime exploit switches it to `Permissive` per shell session.
- Bootloader: U-Boot `2015.07-g0bc803f` (QOGIRL6, Ontim build), `secure: true`,
  `androidboot.securefuse=true`, `androidboot.vbmeta.device_state=locked`
  as shipped, `lcs: 5`; AVB algorithm `SHA256_RSA4096` (Motorola key
  `ecbe1669...`)
  - Unlock history: the key/legacy routes (Motorola code, Unisoc identifier
    token, CVE-2022-38694 BootROM) are **not** usable - see
    `docs/05-bootloader-unlock-research.md`. The working route is the
    secure-world `miscdata` `VerifiedBoot-UNLOCK` marker, decoded in
    `docs/06-secure-world-unlock-path.md` and applied with
    `docs/07-unlock-how-to.md`.
- Kernel config highlights (`artifacts/kernel-config`):
  - `CONFIG_RANDOMIZE_BASE=y` but panic log shows `Kernel Offset: disabled` -> KASLR effectively off; static kernel addresses usable
  - `CONFIG_KALLSYMS=y`, `CONFIG_KALLSYMS_ALL=y` (but `/proc/kallsyms` denied to shell)
  - `CONFIG_IKHEADERS=m`, `CONFIG_SLAB_MERGE_DEFAULT=y`, `CONFIG_HARDENED_USERCOPY=y`
  - `CONFIG_STATIC_USERMODEHELPER=y` -> `modprobe_path` overwrite is NOT usable
  - `CONFIG_DEBUG_LIST=y`, `CONFIG_VMAP_STACK=y`, `CONFIG_STRICT_KERNEL_RWX=y`, `CONFIG_STRICT_MODULE_RWX=y`
  - `CONFIG_ARM64_PAN=y`, `CONFIG_ARM64_UAO=y`, `CONFIG_ION=y`, `CONFIG_OVERLAY_FS=y`, `CONFIG_DEBUG_INFO=y`, `CONFIG_DM_VERITY=y`, `CONFIG_SECCOMP=y`
- Kernel panic evidence: `Bad mode in Error handler detected on CPU6, code 0xbe000011 -- SError` -> `Kernel panic - not syncing: bad mode`; `ro.boot.bootreason=kernel_panic,bad_oome`
  - Sysdump KTXT `[0xffffff8008081000--0xffffff8008e60000]`, `Kernel Offset: disabled`
- Panic logs preserved: `artifacts/panic_seerror_console.txt`, `artifacts/panic2_console.txt`

## Access restrictions observed from shell
- `/proc/kallsyms` -> Permission denied (entire file)
- `/proc/sys/kernel/randomize_va_space`, kptr_restrict not readable
- `/sys/module/mali_kbase/sections/.text` -> denied
- `mali_kbase` is a loadable module, 757760 bytes, used by 36 (`/proc/modules`, Live)
  - Module file not in `/vendor/lib/modules` (only `incrementalfs.ko`, `kheaders.ko`, `trace_*.ko`)
  - Likely on root-only `/mnt/vendor/odmko` (dm-10) -> Permission denied
- `/dev/mali0` is world-rw (`gpu_device`), openable from shell
- `/dev/ion` world-writable; `/proc/config.gz` readable
- `adb pull` denied for `/system_ext/bin/linkturbonative`, `srmi_proxyd`
- Termux installed but app not debuggable; no su/Magisk

## Firmware
- Stock firmware mirror: https://mirrors.lolinet.com/firmware/lenomola/2022/hawaii/
  - `official/` (~48 GB of ROMs), `flashtool/`
- Exact build RORS31.335-58-1 expected under `official/`
- Purpose: obtain `boot.img`/`vendor.img` (and `odmko` module image) to extract
  `vmlinux` (symbols/offsets) and `mali_kbase.ko` (verify DDK + patch status)

## Tooling
- Android NDK r27c tested (any NDK with the LLVM aarch64 toolchain works)
  - set `ANDROID_NDK_HOME` and use `scripts/build.ps1` / `scripts/build.sh`
  - or call `aarch64-linux-android30-clang` directly
- Build pattern: `-static -O2 <src.c> -o <out>`, `adb push` to `/data/local/tmp`, `chmod 755`
- Note: PowerShell surfaces adb stderr as NativeCommandError (harmless)
- Pstore panic: readable via `cat /sys/fs/pstore/console-ramoops-0` (ls denied)

## Test scripts (this repo)
- `scripts/mali/kbase_check.c` / `artifacts/kbase_check` - version ioctl
- `scripts/mali/kbase_probe.c` / `artifacts/kbase_probe` - DDK version + atom stride
- `scripts/mali/mali_stage.c` / `artifacts/mali_stage` - staged UAF trigger
- `scripts/mali/mali_leak.c` / `artifacts/mali_leak` - full scan variant (panics)
- `scripts/mali/mali_rwtest.c` / `mali_rwtest2.c` / `mali_rwtest3.c` - UAF/reclaim tests
- `scripts/mali/mali_gpuw.c` / `artifacts/mali_gpuw` - GPU WRITE_VALUE primitive
