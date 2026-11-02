# 18 - Building and flashing the custom kernel

How to go from a clean checkout to a phone running the custom kernel with
GPU (and, once flashed, WiFi) - on any Linux machine or VM. x86_64, ~30 GB
free disk, 8+ GB RAM recommended; a full build takes roughly 20-40 min on
4 cores, a partial rebuild (one .o) seconds.

Our build host is a Debian VM ("build VM"); nothing about it is special -
any Linux box with the toolchain below works. `sudo` is only needed to
install packages.

## 0. Get the kernel source

Two options.

**Option A - use our published branch** (recommended; it has all fixes):

```bash
git clone --depth 1 https://github.com/CreitinGameplays/motorola-moto-e32-kernel.git kernel-sprd
```

That repo is an orphan-import of the working branch `hawaii-diag`: one
commit holding the Motorola/Unisoc vendor OSS drop, then our real commits
as normal diffs. Kernel version `4.14.199` ("Petit Gorille", qogirl6 /
UMS9230 = T606).

**Option B - vendor drop + our patch series** (reproduces the same tree
byte-for-byte, `git am` of the 17-patch series; see
`patches/kernel-sprd/branch-hawaii-diag/README.md` in the analysis repo):

```bash
git clone https://github.com/MotorolaMobilityLLC/kernel-sprd.git
cd kernel-sprd
git checkout c4e610cd833c
git am /path/to/00[01][0-9]-*.patch
```

## 1. Toolchain

clang 11.0.1 + LLD 11.0.1 (the same versions the shipped kernel was built
with - keeps the ABI/vermagic stable):

```bash
# Debian/Ubuntu example; or download the same tarball:
# https://github.com/llvm/llvm-project/releases/tag/llvmorg-11.0.1
# clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10.tar.xz
mkdir -p ~/toolchains && cd ~/toolchains
tar xf clang+llvm-11.0.1-*.tar.xz
export PATH=~/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH
```

Install the usual build deps (flex, bison, bc, libssl-dev, python3, ...).
A newer distro clang works too but produces a different `vermagic`/CRC
set, which breaks the Magisk modules built against the 11.0.1 kernel -
stick to 11.0.1 unless you rebuild everything.

## 2. Configure

The working config (non-LTO, `MALI_MIDGARD=m`, qogirl6 platform, WCN bus
built-in, AON watchdog diagnostics) is committed as
`patches/kernel-sprd/branch-hawaii-diag/phone.config` in the analysis repo.
Copy it over `.config`:

```bash
cp /path/to/phone.config .config
# production: turn off the probe instrumentation
scripts/config --disable MALI_MDBG_CRUMB
# first build or after Kconfig changes:
make ARCH=arm64 olddefconfig
```

Key settings and why:

| option | value | why |
|---|---|---|
| `LTO_NONE` | y | LTO/CFI builds hang at boot on this board; non-LTO boots (evidence: `docs/evidence/2026-11-01-nolto-boot-test.txt`) |
| `MALI_MIDGARD` | m | in-tree r28p0-01eac0 DDK; loaded by the Magisk module at post-fs-data |
| `MALI_PLATFORM_NAME` | "qogirl6" | Unisoc glue: clocks/regulators owned by the platform, `power_control_init` skipped (the aonapb-gate#9 abort fix) |
| `MALI_MDBG_CRUMB` | m (probe) / n (production) | flash-crumb hang instrumentation; keep off for production |
| `SC23XX` + WCN_* | y | the marlin/sdiohal WCN bus, built-in - the WLAN driver binds to it |

## 3. Build

```bash
make -j$(nproc) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld \
    LLVM_AR=llvm-ar LLVM_NM=llvm-nm KCFLAGS="" Image modules
```

Outputs that matter:

* `arch/arm64/boot/Image` - the kernel
* `drivers/gpu/arm/midgard/mali_kbase.ko` - the GPU driver
* `drivers/net/wireless/sprd_wlan/sprd_wlan_combo.ko` - the SC2355 WiFi driver
* `fs/incfs/incrementalfs.ko` - for Android's incremental installs

Expect the Image at ~21.4 MB. If the build fails in `sprd_wlan` or
`midgard`, re-check step 2 (the tree builds clean with the committed
config).

## 4. Pack + sign the boot image

The kernel must be wrapped in the stock Android boot-image container and
AVB-signed, or the bootloader refuses it. From the analysis repo
(`moto-root-test`) on a machine with the phone's images:

```powershell
# Windows host example (any OS with python3 + the avb key works)
python scripts\host\pack_and_sign_boot.py <Image> artifacts\kernel-build\boot_custom_magisk.img `
    --base artifacts\kernel-build\magisk_boot_b_2026-11-01.img
```

`--base` is the known-good **Magisk** boot image (stock kernel + Magisk
ramdisk): the script reuses its ramdisk and DTB, swaps only the kernel,
recomputes the header, and signs with the throwaway AVB key
(`SHA256_RSA4096`, rollback index 2, stock salt). Using the Magisk base is
what makes `su` work on the result. The full flashing recipe (including
where the Magisk base comes from) is `docs/16-magisk-root-how-to.md`.

Output: a 67,108,864-byte (64 MiB) image, `ANDROID!` magic, `AVBf` footer.
Sanity-check the payload before flashing:

```bash
python - <<'EOF'
import struct, hashlib
d = open("artifacts/kernel-build/boot_custom_magisk.img","rb").read()
f = struct.unpack("<10I", d[8:48])
page, ks = f[7], f[0]
print("magic", d[:8], "kernel", ks, "page", page, "footer", d[-64:-60])
print("payload matches Image:", d[page:page+ks] == open("arch/arm64/boot/Image","rb").read())
EOF
```

## 5. Flash to the device

**`fastboot flash` does NOT work on this phone** - the bootloader's
download gate rejects unsigned images (`Please verify the signature!`).
The working channel is `dd` from a rooted Android (`docs/12`):

```powershell
# from the analysis repo; the script dd's the image to boot_b, verifies the
# read-back hash, arms slot b to ONE attempt, and reboots
.\scripts\host\run_boot_b_test.ps1 -Image artifacts\kernel-build\boot_custom_magisk.img `
    -Out docs\evidence\<date>-flash.txt -SkipWait
```

Preconditions (the script checks them):

* running the stock kernel (or the previous custom kernel) with **Magisk
  root** (`adb shell su -c id -u` prints `0`), SELinux Enforcing
* `boot_a` is the verified rescue image
  (`fc3ca0ef...44c0`) - this is the safety net
* the image is an `ANDROID!` boot image (raw `Image` is refused)

If the test kernel hangs: hold Power ~15 s once. Slot b's single attempt is
spent, the SPL falls back to `boot_a`, the rescue rewrites stock `boot_b`
and reboots Android. Full runbook: `docs/14-brom-recovery-runbook.md`
(BROM/FDL only if even the rescue is unreachable). Building and flashing
the rescue itself: `docs/19-rescue-image-howto.md`.

## 6. Stage the Magisk modules (GPU, and WiFi when enabled)

The kernel alone boots to the logo - SurfaceFlinger needs `/dev/mali0`.
Stage the modules once (they survive reboots):

```powershell
# GPU
.\scripts\host\install_mali_magisk_module.ps1 -Ko artifacts\kernel-build\mali_kbase_prod.ko
# WiFi (SC2355)
.\scripts\host\install_wlan_magisk_module.ps1 -Ko artifacts\kernel-build\sprd_wlan_combo.ko
```

Each installs `module.prop` + `post-fs-data.sh` (from the tracked
`modules/<id>/` skeletons) + the `.ko` under
`/data/adb/modules/<id>/`; on the next boot init runs them at
post-fs-data, `insmod`s the module, and logs to
`/data/local/tmp/<id>_module_load.log`.

## 7. Verify

```bash
adb shell cat /proc/version          # 4.14.199+ ... #<n> ... (debian@vm) - our build
adb shell getprop sys.boot_completed # 1
adb shell ls -l /dev/mali0           # GPU registered
adb shell grep -E "mali|sprd_wlan" /proc/modules
adb shell dmesg | grep -E "Kernel DDK version|Probed as mali0|sprdwl|sc2355"
adb shell ip link show wlan0          # WiFi netdev up
adb shell su -c id -u                 # 0 - Magisk root, SELinux Enforcing
```

Expected dmesg lines (GPU):

```
mali 23100000.gpu: Kernel DDK version r28p0-01eac0
mali 23100000.gpu: clocks/regulators handled by platform glue, skipping DDK power_control_init
mali 23100000.gpu: GPU identified as 0x1 arch 9.0.9 r0p1 status 0
mali 23100000.gpu: Probed as mali0
```

And two *expected* failures from the vendor's own rc files (their
prebuilt modules cannot load against our kernel - `module_layout` CRC
mismatch): `init.md.rc`'s `insmod .../socko/mali_kbase.ko` and
`wcn.rc`/`camera.rc`'s insmods. Harmless: our in-tree replacements load
later at post-fs-data.

## 8. What is still not working on the custom kernel

* camera stack (`sprd_camera`, `sprd_sensor`, `sprd_cpp`, `sprd_fd`,
  `sprd_flash_drv`, `flash_ic_ocp8135b`, `mmdvfs`) - sources not yet
  located; see `docs/17-vendor-module-rebuilds.md`
* BT/FM (`sprdbt_sdio_tty`, `sprd_sdio_fm`) - likely follow the WiFi route
  (`mu300-linux` keeps `sprdbt_tty` too)
* SAR sensor (`aw9610x_sar`)
* `incrementalfs` is in-tree (`fs/incfs`, `=m`) but not yet staged as a
  Magisk module - optional, affects Play incremental installs on /data

## 9. KVM (the reason this kernel exists)

`/dev/kvm` is created early (misc 10:232, root-only) - the diag series
carried the early KVM/EL2 init. Verified: a Debian 13 arm64 netinst
boots to its installer in Termux QEMU with `-accel kvm -cpu host`
(GICv3 `its=off`, virtio-blk qcow2, UEFI ramfb, VNC). QEMU must run as
root (`su -c`) to open `/dev/kvm`. Windows ARM64 guests are untested.
The exact command line is in
`docs/evidence/2026-11-02-kvm-verified.txt`.

## Reference

* build evidence + hashes: `docs/evidence/2026-11-02-mali-autoload-success.txt`
* the boot-hang investigation (why non-LTO, why `power_control_init`
  needed the skip): `docs/evidence/2026-11-02-mali-abort-rootcause.txt`
* kernel commits: https://github.com/CreitinGameplays/motorola-moto-e32-kernel
  (the build fixes are part of the same series; apply the whole branch)
