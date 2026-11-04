# 18 - Building and flashing the custom kernel


Shells: sections 0-3 are bash on the **build machine** (any Linux box);
section 4 and later are bash/PowerShell on the **Windows host** that holds
the images. Set `export MSYS2_ARG_CONV_EXCL="*"` in Git Bash first - see
README "Shell conventions".
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

Two config routes exist:

* **Daily kernel (recommended)** - the *stock-config* build of section 8b
  (+ KVM per section 9).  It is the one that loads the vendor modules and
  is what currently runs on the phone.
* **Older custom config** (non-LTO, `MALI_MDBG_CRUMB` diagnostics, ...)
  committed as `patches/kernel-sprd/branch-hawaii-diag/phone.config` in
  the analysis repo - the diag-series route; it does NOT load the vendor
  modules (CRC mismatch) and is kept for the probe/diag workflows.
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
    LLVM_AR=llvm-ar LLVM_NM=llvm-nm KCFLAGS="" \
    LOCALVERSION=+-ab612c2 Image modules
```

`LOCALVERSION=+-ab612c2` makes `UTS_RELEASE` byte-match the shipping
kernel (`4.14.199+-ab612c2`), which the vendor modules' vermagic check
requires - omit it and every `insmod` fails with a version-magic error.
The CFI-ABI compat patches (section 8b) must be in the tree; the
published branch already carries them.

**Daily-driver path (recommended):** `bash build.sh` in the kernel tree
works from any fresh clone on any Linux build host (a laptop, a VM or a
rented box - it does not need to be the machine that flashes; in this
project it is a small VPS).  It does all of the above in one go: it
recovers the shipping `.config` (`stock_kernel_config.txt` in the repo
root), applies the vendor-module-compat + Mali/WLAN/BT/KVM options,
builds `Image modules` together, and then **copies the boot-critical
outputs into `$STABLE`** (default `~/kernel-out`: Image, `mali_kbase.ko`,
`sprdwl_ng.ko`, `sprdbt_tty.ko`, `Module.symvers`, `kernel.config`, plus
a `SHA256SUMS` manifest).  Everything is overridable via the
environment: `TOOLCHAIN` (dir with clang/lld), `CONFIG` (starting
.config), `OUT` (build dir, default `/tmp/kbuild` - it may be RAM-backed
and wiped on reboot), `STABLE` (persistent output dir).  `~/kernel-out`
is the source of truth: Image and modules there are guaranteed to come
from the same build, which is what keeps vermagic and `module_layout`
CRC consistent.

Outputs that matter:

* `Image` (from `~/kernel-out`, was `arch/arm64/boot/Image`) - the kernel
* `mali_kbase.ko` - the GPU driver (staged via the Magisk module; the
  kernel alone boots to the logo because SurfaceFlinger needs
  `/dev/mali0`)
* `sprdwl_ng.ko` - the SC2355 WiFi driver (the module must keep this
  exact name; the WiFi HAL gates on a `/proc/modules` line starting with
  `sprdwl_ng`)
* the vendor modules (camera/BT/FM/SAR, and `incrementalfs`) are loaded
  by the vendor rc files themselves - nothing to stage

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

**Keep `/data/local/tmp` clean** (2026-11-04: it had grown to 1.7 GB of
stale staged images before this was enforced):

* the flash script pulls/copies the image it needs and deletes its own
  staging copy afterwards - never leave a `boot_*.img` behind;
* only two things belong there permanently: the proven rescue
  (`boot_rescue_restore.img`, `fc3ca0ef...44c0`) and
  `mali_kroot` (the CVE-2021-28663 launcher used when there is no
  Magisk root yet);
* kernel modules that are actively being tested may stay while a test
  cycle is open, and must be removed once it closes;
* every image a test produced lives on the host in
  `artifacts/kernel-build/` - pull from there instead of re-uploading
  and keep the device directory near 100 MB (rescue + modules).

## 6. Stage the Magisk modules (GPU, and WiFi when enabled)

The kernel alone boots to the logo - SurfaceFlinger needs `/dev/mali0`.
`build.sh` already builds the modules with the Image; first copy them
off the build host (they are in `$STABLE`, default `~/kernel-out`, one
build together with the Image), then stage them (they survive reboots
on the device).  Replace `<build-host>` with however you reach your
build box (in this project that is `test-vps`):

```powershell
# 1) copy the fresh build's modules to the host (same build as the Image!)
scp <build-host>:kernel-out/mali_kbase.ko artifacts/kernel-build/mali_kbase.ko
scp <build-host>:kernel-out/sprdwl_ng.ko  artifacts/kernel-build/sprdwl_ng.ko
scp <build-host>:kernel-out/SHA256SUMS    artifacts/kernel-build/SHA256SUMS.last

# 2) stage them as Magisk modules
.\scripts\host\install_mali_magisk_module.ps1 -Ko artifacts\kernel-build\mali_kbase.ko
.\scripts\host\install_wlan_magisk_module.ps1 -Ko artifacts\kernel-build\sprdwl_ng.ko
```

Each installs `module.prop` + `post-fs-data.sh` (from the tracked
`modules/<id>/` skeletons) + the `.ko` under
`/data/adb/modules/<id>/`; on the next boot init runs them at
post-fs-data, `insmod`s the module, and logs to
`/data/local/tmp/<id>_module_load.log`.

The `.ko` files must come from the **same kernel build** as the flashed
Image (same vermagic `4.14.199+-ab612c2`, same `module_layout` CRC) -
that is why step 1 pulls them from the build host's `$STABLE`, whose
`SHA256SUMS` binds Image and modules to one build.  After every kernel
rebuild, redo steps 1-2 with the fresh files before rebooting into the
new Image.  If
the device runs an Image whose matching `.ko` was never staged, expect
the boot to sit at the logo (kernel up, `system_server` waiting on
SurfaceFlinger) - recover per `docs/14`, then stage the right `.ko`.
The vendor modules need no staging: `camera.rc` / `wcn.rc` insmod them
from `/mnt/vendor/socko/` on every boot.

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

On the stock-config build the vendor rc insmods *succeed*, so the only
expected log noise is:

* `wcn.rc` trying to insmod the non-existent `socko/sprdbt_tty.ko` (the
  real file is `sprdbt_sdio_tty.ko` - a vendor rc typo, harmless), and
* our own post-fs-data insmod of `mali_kbase`/`sprdwl_ng` failing with
  "File exists" if the vendor rc loaded its copy first (one driver per
  name; either copy works on this kernel).

On the older `phone.config` diag build those vendor insmods fail with a
`module_layout` CRC mismatch instead - also harmless there, our in-tree
replacements load later.

## 8. What is still not working on the custom kernel

Nothing in the vendor-module list - the vendor-module-compatible build
(docs 17 section "2026-11-03 (result)", config recipe in section 8b) loads
*all* of them: camera stack, flash IC, BT (`sprdbt_sdio_tty`, HAL runs
real HCI), FM (`sprd_sdio_fm`), SAR (`aw9610x_sar`), and `incrementalfs`
is loaded by the vendor rc itself.  KVM is in the same build too (see
section 9): the task_struct/mm_struct field relocation
(docs 17 "2026-11-03 (2)") is implemented and device-verified with the
`modules/abiprobe` offsets check.

## 8b. Vendor-module-compatible build (camera experiments)

The stock camera/BT/SAR/FM/incfs modules in `/mnt/vendor/socko/` were built
with CFI on, so a normal custom-kernel build refuses them.  A kernel that
accepts them is built from the recovered stock config:

```bash
cp /path/to/stock_kernel_config.txt .config     # artifacts/kernel-build/stock_kernel_config.txt
scripts/config --disable LTO --disable LTO_CLANG --enable LTO_NONE     --disable CFI --disable CFI_CLANG --disable CFI_CLANG_SHADOW
scripts/config --module MALI_MIDGARD --set-str MALI_PLATFORM_NAME qogirl6     --enable MALI_REAL_HW --enable MALI_DMA_FENCE --enable MALI_GATOR_SUPPORT     --module SPRD_WLAN_COMBO --module SPRDBT_TTY
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CC=clang LD=ld.lld     LLVM_AR=llvm-ar LLVM_NM=llvm-nm OBJDUMP=llvm-objdump     LOCALVERSION=+-ab612c2 -j$(nproc) Image modules
```

Three details make it work (all scripted):

* `LOCALVERSION=+-ab612c2` reproduces the vendor vermagic
  `4.14.199+-ab612c2 SMP preempt mod_unload modversions aarch64`.
* `scripts/host/apply_vendor_module_compat.py` +
  `..._compat2.py` patch the tree for the CFI ABI: unconditional
  `struct module::cfi_check` and `struct timer_list::__function`, skip the
  `module_layout` CRC check, log-and-accept other CRC differences, and
  export a no-op `__cfi_slowpath`.
* **KVM can be added to this config only together with the field
  relocation**: KVM selects `MMU_NOTIFIER`/`PREEMPT_NOTIFIERS`, which
  change `struct mm_struct` / `struct task_struct`.  With
  `scripts/host/apply_kvm_field_relocation.py` applied (published
  branch: yes) the two fields sit at the struct tails and the vendor
  ABI is preserved - verified with `modules/abiprobe`
  (docs/evidence/abiprobe/README.md).  Without the relocation, do not
  enable KVM.

Rationale and measurements: `docs/17-vendor-module-rebuilds.md`.

Practical notes for the build host:

* keep **one** `O=` build directory at a time on a RAM-backed `/tmp`
  (the reference VM's tmpfs is 3.9 GB; two 2 GB build trees fill it and
  the final `objcopy` fails with `No space left on device`).  Save the
  finished tree's `Module.symvers` somewhere persistent
  (`~/Module.symvers.compat-nokvm`) before deleting it - it is the
  CRC reference for the ABI comparisons.
* an interrupted build resumes with the same `make ... Image modules`
  command; only the final link/objcopy steps are redone.

## 9. KVM (the reason this kernel exists)

Status 2026-11-03: KVM is back in the *single* daily kernel - the stock
config + KVM group + the task_struct/mm_struct field relocation pass the
abiprobe ABI check (docs 17 "2026-11-03 (2)", evidence
`2026-11-03-kvm-compat-success.txt`).  The build recipe of section 8b plus
`--enable VIRTUALIZATION --enable KVM --enable KVM_ARM_HOST --enable
KVM_VFIO --enable VHOST --enable VHOST_NET --enable VSOCKETS --enable
MMU_NOTIFIER --enable PREEMPT_NOTIFIERS` (after the relocation patches)
produces it.  Do NOT add those options *without* the relocation.

`/dev/kvm` is created early (misc 10:232, root-only) - the diag series
carried the early KVM/EL2 init. Verified guests:

- Debian 13.7 arm64 netinst reaches its installer in Termux QEMU with
  `-accel kvm -cpu host` (GICv3 `its=off`, virtio-blk qcow2, UEFI ramfb,
  VNC) - exact command in `docs/evidence/2026-11-02-kvm-verified.txt`
- **Windows 11 IoT Enterprise LTSC 24H2 ARM64** (build
  26100.ge_release_24H2) installed and running as a
  "KVM Virtual Machine" (6 vCPU, 2 GB RAM; screenshots in
  `screenshots/kvm_win11_screenshots/`)

QEMU must run as root (`su -c`) to open `/dev/kvm`.

## 10. External kernel modules (build + recovery)

The analysis repo carries small out-of-tree kernel modules for
on-device work (`modules/`):

| module | purpose |
|---|---|
| `modules/abiprobe` | dumps `offsetof()`/`sizeof()` for the ABI-critical structs - the vendor-module ABI check (docs/17) |
| `modules/gpu-gpll-poker` | DVFS register access + tools: `clocks`/`index`/`rate` (clk re-rate), `guard` (veto the 650 MHz GPLL re-clamp), `base` 0-5 + `rd`/`wr`/`dump` (raw AON register access), `mon` (us-resolution FSM transition capture), `clkwalk` (kernel clock tree walk) |
| `modules/gpu-dvfs-untrim` | research record: the boot-time GPU DVFS untrim experiment (`untrim_gpll` module param, default 0) |

Build against the kernel tree with a separate `O=` directory:

```bash
cd /path/to/kernel-sprd          # any checkout of the kernel tree
export PATH=/path/to/clang+llvm-11.0.1-*/bin:$PATH   # toolchain from step 1
make -j$(nproc) O=/tmp/kbuild2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CC="clang --target=arm64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar \
     LLVM_NM=llvm-nm M=~/poker_build modules
```

(put the module's .c + Makefile in an out-of-tree dir like
`~/poker_build`; the result is `~/poker_build/<module>.ko`).

**Recovery after a /tmp wipe** (a RAM-backed `O=` tree disappears on
reboots - this rebuilds a module-only tree in ~2 minutes, no full
kernel build needed):

```bash
# one-time: save the production config somewhere persistent
cp /path/to/stock_kernel_config.txt ~/kconfig_stock.txt
# (a `build.sh` run also leaves the production config in
#  $STABLE/kernel.config and Module.symvers next to it -
#  those survive reboots too and can seed the module-only tree)

# fresh module-prepare tree
mkdir -p /tmp/kbuild2 && cp ~/kconfig_stock.txt /tmp/kbuild2/.config
cd /path/to/kernel-sprd
export PATH=/path/to/clang+llvm-11.0.1-*/bin:$PATH
make -j$(nproc) O=/tmp/kbuild2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CC="clang --target=arm64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar \
     LLVM_NM=llvm-nm olddefconfig
make -j$(nproc) O=/tmp/kbuild2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CC="clang --target=arm64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar \
     LLVM_NM=llvm-nm modules_prepare
# then build the module with M=... as above
```

Notes:

* the module tree needs **no `Module.symvers`** - this kernel's relaxed
  `check_version` (kernel-side patch) accepts modules built without
  modversions, same as it accepts the vendor modules.  Verified live:
  the poker module built against a bare `modules_prepare` tree insmods
  and runs.
* a full-build `O=` tree (after `make ... modules`) also works for
  module builds and produces them with proper version info; the
  `modules_prepare` route is just the fast recovery path.
* on-device: `insmod /data/local/tmp/<module>.ko` via `su -c` (custom
  kernel boots).  Remember the adb quirks (README "Shell conventions"):
  `MSYS2_ARG_CONV_EXCL="*"` on the host, and push device scripts to
  files instead of heredocs through `su -c`.

## Reference

* build evidence + hashes: `docs/evidence/2026-11-02-mali-autoload-success.txt`
* the boot-hang investigation (why non-LTO, why `power_control_init`
  needed the skip): `docs/evidence/2026-11-02-mali-abort-rootcause.txt`
* kernel commits: https://github.com/CreitinGameplays/motorola-moto-e32-kernel
  (the build fixes are part of the same series; apply the whole branch)

## 11. On-panel boot indicator (what you see during boot)

Every kernel from this branch paints a small **boot progress bar** on
the boot logo while Android starts; the Android boot animation replaces
the picture a few seconds later (`include/linux/diag_stage.h`,
DIAG_BANNER):

* a 16-px-tall gray bar near the **top edge** of the panel at rows 24-39
  (mirrored at rows 1560-1575, see below), 12 segments of 48 px starting
  at column 72, that fill left to right as boot progresses:
  * a dim track plus segments 0-2 in `head.S` (the pre-MMU milestones:
    `el2_setup`, page tables, `__cpu_setup`) - each one shade brighter,
    so a photo of a hang before the MMU names the last completed step
  * segments 0-7 right after `paging_init()` in `setup.c`
  * segments 8-11 after `do_basic_setup()` in `init/main.c` (all
    initcalls done) - full width = kernel up, Android starting

**Geometry - settled by experiment** (trail in the `diag_stage.h`
comment): the logo partition (`/dev/block/by-name/logo`, sda12) holds
gzip-compressed BMPs that are **720x1600 24-bpp with the picture upright**
in the canvas (content bounding boxes are taller than wide), and the
panel's DRM mode is 720x1600.  The bootloader copies the BMP straight
into `lcd_base`, so the framebuffer is **portrait: 720 columns x 1600
rows, stride 2160 = 720 * 3, displayed 1:1**:

```
buffer row    = panel Y (down)
buffer column = panel X (right)
```

Two traps that cost several boots, both confirmed the hard way:

* the cmdline `lcd_size=1600x720` describes the panel in its *native
  landscape* orientation - it is NOT the buffer layout.  Painting with a
  4800-byte stride into the real 2160-byte buffer shears every row onto a
  lattice of columns about 80 px apart: that is the **several vertical
  dotted bars** v4 showed (it was reported as "4 vertical lines, one at
  each edge, two in between" - see
  `docs/evidence/2026-11-03-bootbar4-flash.txt`), and it also explains
  the sheared text of v2 (which already used 2160 for painting but the
  landscape row/column counts).
* two of the charging BMPs are 720x800 with sideways content; that is
  what made a "rotated scanout" theory look plausible for a while.

How to check a candidate mapping without flashing: render the exact write
pattern into a buffer of the proposed geometry and compare the picture
with a photo of the panel.  For v4's pattern the landscape model predicts
two clean horizontal lines, while the portrait model predicts the dotted
vertical columns that were actually observed - that comparison, not the
photo of v1 alone, is what settled it.

Colors are byte-symmetric gray (white/black/gray only): the
per-channel byte order of the scanout is unconfirmed - no colored
indicators until a known-color test is photographed.

Turn it off with `#define DIAG_BANNER 0` in
`include/linux/diag_stage.h`; the full multi-row diag console is
`DIAG_SCREEN` (diag builds only), and it now paints in the same portrait
geometry, so its photos read upright too.

**History:** v1 (stride 4800, text) ran up the panel edge, v2 (2160 with
landscape dimensions) sheared, v3 ("rows 0..1", stride 4800) was invisible,
v4 (landscape model, stride 4800) produced the vertical dotted lattice,
and v5 (kernel `d8067a1389cc`, portrait 2160) **works**: the panel shows
the top bar and its bottom mirror filling left to right (user-confirmed
2026-11-04, evidence in `docs/evidence/2026-11-04-bootbar5-flash.txt`).

**If a boot stops at the logo with the bar full**, the kernel reached
`do_basic_setup()` and the problem is in Android userspace, not the
kernel: after the next boot, `/sys/fs/pstore/console-ramoops-0` will
show `run init` followed by the vendor native-hang watchdog's
`systemserver cmd` polls and `sysrq: Kill All Tasks` instead of a
panic (see `docs/evidence/2026-11-03-bootbar-hang-analysis.txt`).
