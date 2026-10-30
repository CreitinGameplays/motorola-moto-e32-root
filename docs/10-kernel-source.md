# Exact kernel source for the Moto E32 ("hawaii", Unisoc T606)

Status: **public source found and verified; the measured gap to the shipping
build is closed by a backport** (2026-10-29).

## TL;DR

| question | answer |
|---|---|
| Where is the source? | `https://github.com/MotorolaMobilityLLC/kernel-sprd`, branch **`R-11-release-RORS`** (tag `MMI-RORS31.193-14-6`, HEAD `c4e610cd833c47f08969678fa58f9bfcb57bd3a5`) |
| Is it the right tree? | **Yes**: it is the Unisoc 4.14.199 "Petit Gorille" kernel for `qogirl6`/UMS9230 = T606, the board file matches the running device tree byte for byte in every `compatible`/`model` string |
| Is it the *exact* source of our firmware? | **Almost.** Motorola's published snapshot is from **2022-10-25**; our kernel was built **2024-02-20** (`RORS31.335-58-1`). The delta was measured (7 headers + 3 `.c` files + 1 config fragment) and is now **backported**: with `patches/kernel-sprd/` applied, **4,852 of 4,852** shipped headers are code-identical to the tree and the build config reproduces `/proc/config.gz` with **0 conflicts** |
| Does it build? | **Yes** - full `Image dtbs modules` build on a Linux host, see [Building the tree](#building-the-tree) |
| What is still missing? | the Unisoc SIPC/JPG/VSP/sensor **.c** changes (the headers are known, the code is not published); plus the prebuilt `mali_kbase` GPU module |
| How close can we get? | public tree + exact `.config` + exact generated headers (both extracted from the phone) + the measured backport; every step is verifiable against the dumped kernel image |
| What is not public at all? | the **Mali `mali_kbase` module source** (prebuilt `.ko` in the vendor image) and the unpublished per-build history |

Local copy (blobless clone, 17.5 GB of git objects, 63,927 files checked out):

```
D:\AndroidSDKTools\kernel-sprd          # branch R-11-release-RORS
                                         # + local/rors31.335-58-1-gap (backport)
```

Fetch it again with:

```powershell
.\scripts\host\get_kernel_source.ps1          # clone + Windows-safe checkout + backport
.\scripts\host\get_kernel_source.ps1 -Verify  # + compare against the phone
```

## What the tree contains

```
Makefile                              VERSION=4 PATCHLEVEL=14 SUBLEVEL=199
                                       NAME = "Petit Gorille"   (Unisoc 4.14 tree)
arch/arm64/configs/sprd_qogirl6_defconfig   # 3,950 entries - the build config
sprd-diffconfig/androidr/qogirl6/arm64/     # release ("androidr" = Android 11) fragments
  aarch64_user_diff_config
  ums9230_4h10_diff_config                  # <- our board (4H10)
arch/arm64/boot/dts/sprd/
  qogirl6.dtsi                              # UMS9230/T606 SoC
  ums9230.dts / ums9230.dtsi / ums9230-mach.dtsi
  ums9230-4h10-overlay.dts                  # board file of this phone
```

Board identification, straight from the running phone (rooted, live DT):

```
/proc/device-tree/model      -> "Spreadtrum UMS9230 4H10 Board"
/proc/device-tree/compatible -> "sprd,ums9230-4h10"
```

which is exactly what `arch/arm64/boot/dts/sprd/ums9230-4h10-overlay.dts` declares.
There is **no "hawaii" string in the kernel source** - the E32 board is called
`4h10` there ("hawaii" is only the Android product codename).

## Verification: the public tree really is this kernel

Five independent checks, all reproducible with the scripts in `scripts/host/`:

### 1. Version / build identity

From the exact-build headers (`include/generated/`, extracted from the phone):

```c
/* utsrelease.h */ #define UTS_RELEASE "4.14.199+-ab612c2"
/* compile.h  */ #define LINUX_COMPILE_BY "xscm"
                 #define LINUX_COMPILE_HOST "ontimbjlx020"
                 #define UTS_VERSION "#0 SMP PREEMPT Tue Feb 20 11:31:04 CST 2024"
                 #define LINUX_COMPILER "Android (6443078 based on r383902) clang version 11.0.1 ..."
```

`4.14.199` matches `SUBLEVEL = 199` in the public `Makefile`.
The `-ab612c2` suffix is **not** a commit hash: `612c2` is the build id in the
firmware fingerprint (`motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:...`),
i.e. Motorola stamps the kernel with the firmware build id (the `+` comes from
`scripts/setlocalversion` when the tree is not at an exact git tag).

### 2. Build config

`arch/arm64/configs/sprd_qogirl6_defconfig` + the two release fragments in
`sprd-diffconfig/androidr/qogirl6/arm64/` reproduce the phone's `/proc/config.gz`:

* defconfig alone: 3,950 symbols, **64 mismatches** against the phone's config
* with the two release fragments: 3,941 symbols, 3,878 of them shared with the
  phone's config, **40 mismatches left**
* the 34 symbols present only in the phone's config are exactly the ones the
  fragments delete (`DEL:CONFIG_DEBUG_FS`, `DEL:CONFIG_KGDB`, ...), i.e. the
  fragments explain them

Remaining delta: the **40** mismatches are all diagnostic options
(`CONFIG_SPRD_DJTAG`, `CONFIG_SPRD_BUSMONITOR`, `CONFIG_FUNCTION_TRACER`,
`CONFIG_KGDB_SERIAL_CONSOLE`, ...) that the public defconfig enables but the
shipping kernel **disables**. The production build therefore applied **one
additional, unpublished config fragment**.

That fragment is now **reconstructed exactly** from the phone's own
`/proc/config.gz` (`scripts/host/reconstruct_release_config.py`):

```
artifacts/kernel-src/reconstructed_release_diff_config   # Motorola/Unisoc DEL:/ADD: format
artifacts/kernel-src/reconstructed_release.config         # classic diffconfig format
```

* 40 `DEL:` entries (all "not set" in the shipping kernel)
* 34 symbols that only the shipping config knows, including
  `CONFIG_TOUCHSCREEN_ILITEK_MODEL=""` (the public defconfig carries
  `#CONFIG_TOUCHSCREEN_ILITEK_MODEL="tianma-ili9883a"`)
* verification: after applying it, the reconstructed config matches the
  shipping `/proc/config.gz` with **0 conflicts and 0 uncovered symbols**

### 3. Kconfig symbol coverage

Scanning every `Kconfig*` in the public tree yields 17,984 defined symbols.
**All 3,912 symbols used by the running kernel are defined in the public tree
(0 missing)** - the tree is complete for this configuration, no driver is
missing.

### 4. Header-level match

`include/` of the running kernel (IKHEADERS tarball, see below) vs the public
tree, comparing code with comments/whitespace normalised (the vendor strips
comments out of the IKHEADERS tarball):

* before the backport: 4,842 identical, **7 genuine differences**
* after the backport (`patches/kernel-sprd/`): **4,852 of 4,852 identical,
  0 differences, 0 headers that exist only in the shipping kernel**
* 7-9 tree-only headers (Kbuild stubs and files the build never copies)

A handful of files (`uapi/linux/netfilter/xt_{CONNMARK,DSCP,RATEEST,MARK,TCPMSS}.h`,
`uapi/linux/netfilter_ipv4/ipt_{ECN,TTL}.h`, `uapi/linux/netfilter_ipv6/ip6t_HL.h`)
show up as differences only because NTFS is case-insensitive and the tree
contains both an upper- and a lowercase variant (different content). The
comparator resolves them straight from the git object store: they are
**identical** to the shipping headers - on ext4 there is no difference at all.

### 5. Device tree

Live `/proc/device-tree` (943 nodes, 3,154 properties) vs the public DTS:

* **184 of 184 `compatible`/`model` strings are present in the public DTS**
* 0 strings live-only
* the board file `ums9230-4h10-overlay.dts` is the one that was compiled in

So the board support in the public tree is exactly the board support the phone
is running.

## The gap: what the public tree is missing - and how it was closed

The public branch stops at `c4e610cd` ("Add design file", **2022-10-25**) and
the newest release tag is `MMI-RORS31.193-14-6` (= firmware `RORS31.193-14-6`).
Our phone runs **RORS31.335-58-1**, built **2024-02-20** - roughly 16 months
and several Unisoc monthly security patch rounds later.

The delta is visible in the 7 differing headers:

| header | public tree (2022-10) | shipping kernel (2024-02) | what it is |
|---|---|---|---|
| `include/linux/file.h` | - | `fget_many()`, `fput_many()` | upstream "fs: add fget_many() and fput_many()" (Jens Axboe) |
| `include/linux/fs.h` | `get_file_rcu(x) = atomic_long_inc_not_zero(...)` | `get_file_rcu_many()` | same series |
| `include/linux/rmap.h` | `anon_vma.degree` | `anon_vma.num_children` / `num_active_vmas` | upstream anon_vma rework (Jee Won, v6.9) |
| `include/linux/sipc.h` | plain `copy_from_user()` | `sbuf_copy_from_user()` with `check_copy_size()` + `kasan_check_write()` | **Unisoc-specific** SIPC (shared-memory IPC) hardening |
| `include/uapi/video/sprd_jpg.h` | no size define | `SPRD_JPG_MAP_SIZE 0x6000` | Unisoc JPEG UAPI change |
| `include/uapi/video/sprd_vsp.h` | `SPRD_VSP_MAP_SIZE 0xA000` | `0x14000` | Unisoc VSP memory-map size change |
| `include/uapi/video/sprd_sensor_k.h` | - | `SENSOR_IOC_PRIVATE_KEY 0x789A`, `SENSOR_IO_PRI_KEY` ioctl | Unisoc sensor driver change |

### Provenance of the hunks (verified against upstream)

Every hunk was matched against the upstream trees (fetched with
`raw.githubusercontent.com`, cached in `artifacts/kernel-src/upstream-check/`):

* `fget_many()` / `fput_many()` / `get_file_rcu_many()` - **byte-identical** to
  `linux-4.19.y` and `linux-5.10.y` stable (`include/linux/file.h`,
  `include/linux/fs.h`). Upstream added them in the "fs: add fget_many() and
  fput_many()" series and later dropped them again in 6.2, so they only exist
  in the stable branches that received the backport.
* `num_children` / `num_active_vmas` - the upstream "mm: change anon_vma degree
  to num_children" rework (v6.9, backported to `linux-4.19.y` /
  `linux-5.10.y` / `linux-6.1.y` as the `anon_vma->degree` ambiguity fix).
  Unisoc additionally moved the two counters **behind `rb_root`**, a layout
  that does not exist upstream - so this hunk is a vendor adaptation of the
  upstream patch.
* the four `include/uapi/**` and `include/linux/sipc.h` hunks are **Unisoc
  only** (no upstream equivalent exists).

### The backport

`patches/kernel-sprd/0001-sprd-backport-rors31.335-58-1-header-delta.patch`
(also applied automatically by `scripts/host/get_kernel_source.ps1` and
`scripts/host/apply_shipping_header_delta.py`) contains exactly these 7 files:

```
 include/linux/file.h               |  2 ++
 include/linux/fs.h                 |  4 +++-
 include/linux/rmap.h               | 17 +++++++++++-------
 include/linux/sipc.h               | 27 ++++++++++++++++++++++-----
 include/uapi/video/sprd_jpg.h      |  1 +
 include/uapi/video/sprd_sensor_k.h |  2 ++
 include/uapi/video/sprd_vsp.h      |  2 +-
```

After applying it the header comparison reports **0 differences** (4,852 of
4,852 identical). The Unisoc SIPC helper is consistent with the tree's own
`include/linux/uaccess.h`, which already uses the same hardened
`check_copy_size()` + `kasan_check_write()` pattern - so the backport compiles
against the public tree.

### The matching `.c` half (patch 0002)

The header delta alone does not build: `rmap.h` renames a field the tree's
`mm/rmap.c` still uses, and `file.h` declares two functions nobody defines.
The missing code was found in a **sibling vendor branch of the same tree**:

```
R-11-release-RONS  (tag MMI-RONS31.267-94-14)
   same base: 4.14.199 "Petit Gorille", Unisoc qogirl6, secured Android 11
```

`git diff R-11-release-RORS R-11-release-RONS -- mm/rmap.c fs/file.c
fs/file_table.c` is *nothing but* the missing changes, so patch
`patches/kernel-sprd/0002-sprd-backport-rors31.335-58-1-mc-delta.patch`
uses it verbatim:

| file | change |
|---|---|
| `mm/rmap.c` | `anon_vma->degree` -> `num_children` / `num_active_vmas`, incl. the corrected `anon_vma_clone()` reuse test (`num_children < 2 && num_active_vmas == 0`, upstream `2555283eb40d`) |
| `fs/file.c` | `__fget()` gains a `refs` argument, `fget_many()` added, and `__fget()` re-checks the fd slot after taking the refs |
| `fs/file_table.c` | `fput()` split into `fput_many(file, refs)` + `fput()` |

Two checks show RONS is the right source and not a lookalike:

* the shipped `System.map` has **`T fput_many`** and **`T fget_many`** as
  out-of-line global functions. Upstream 4.19 implements `fput_many()` as a
  `static inline` in `include/linux/fs.h`, which would leave no such symbol;
  the RONS split (`fs/file_table.c`) matches the shipped kernel exactly.
* `include/linux/fs.h` already provides `get_file_rcu_many()` from patch 0001,
  so `fs/file.c` needs no further header work.

### What the backport still does *not* give us

* the Unisoc SIPC/JPG/VSP/sensor **`.c`** changes are not published; only their
  UAPI/header side is visible. They are not needed to build the tree.
* the Mali `mali_kbase` module source (see below).

Not public at all:

* the **Mali `mali_kbase` module source** - the GPU driver is a prebuilt
  module (`/mnt/vendor/socko/mali_kbase.ko`), not part of the kernel tree; the
  Motorola repos `sprd-kernel-modules-gpu-sprd` / `-gpu-natt` contain only a
  README. (This is the driver our CVE-2021-28663 exploit targets; see
  `docs/01-mali-cve-2021-28663.md`.)
* the per-build history of the 2023/2024 patch rounds (Motorola publishes the
  *result*, not the per-build commits, for 4.14)

The module's `.modinfo` (pulled from the phone) is the only source fingerprint
the vendor left for the driver:

```
license=GPL
version=r28p0-01eac0 (UK version 11.29)
vermagic=4.14.199+-ab612c2 SMP preempt mod_unload modversions aarch64
name=mali_kbase
alias=of:N*T*Csprd,mali-natt
```

`vermagic` matches the running kernel's `UTS_RELEASE` exactly, so the driver
was built against this very kernel snapshot. The `.ko` is **stripped** (no
`.symtab`, no `.debug_*`), so nothing can be recovered from it beyond the
symbols it exports - the DDK r28p0 source is simply not public.

Unisoc's own public 4.14 tree (`sprd-linux/kernel4.14`, branch
`sprdroid10_trunk`) is **older** than Motorola's (4.14.133 vs 4.14.199) and
contains none of the 2023 markers, so it is not a source for the missing
patches either.

## Getting the exact source: what is actually possible

### 1. Use the public tree as the base (done)

`D:\AndroidSDKTools\kernel-sprd` @ `R-11-release-RORS` is the GPL source for
this platform and is verified against the phone on 5 axes (above).

### 2. Take the exact build inputs from the phone

These are ground truth and can be extracted from the device itself (no guessing):

| artifact | source on the phone | extracted to |
|---|---|---|
| exact build config | `/proc/config.gz` | `artifacts/kernel-config` |
| exact generated headers (incl. `autoconf.h`, `utsrelease.h`, `compile.h`, per-symbol `include/config/*`, `arch/arm64/include/generated/*`) | `insmod /vendor/lib/modules/kheaders.ko` -> `/sys/kernel/kheaders.tar.xz` | `artifacts/kheaders.tar.xz` -> `artifacts/kheaders_full/` (6,550 files) |
| exact device tree | `/proc/device-tree` | `artifacts/dt-live/` (943 nodes) |
| exact kernel binary + symbols | physical dump of the kernel Image | `artifacts/kimage_ok.bin`, `artifacts/System.map` (119,878 symbols) |

### 3. Apply the measured delta (done)

* headers: `patches/kernel-sprd/0001-sprd-backport-rors31.335-58-1-header-delta.patch`
  -> 4,852/4,852 identical, 0 differences
* the `.c` half: `patches/kernel-sprd/0002-sprd-backport-rors31.335-58-1-mc-delta.patch`
  (taken from the sibling branch `R-11-release-RONS`) -> `mm/rmap.c`,
  `fs/file.c`, `fs/file_table.c` now match the shipped symbols
* build config: `artifacts/kernel-src/reconstructed_release_diff_config`
  -> 0 conflicts, 0 uncovered symbols
* build fixes: `patches/kernel-sprd/0003-sprd-build-fix-devfreq-trace-include.patch`
  and `0004-sprd-build-fix-sfp-include-path.patch` (the vendor tree as
  published does not compile its own DDR-DFS tracepoint or its SFP driver)
* `0005-vhost-unsigned-ioctl-cmd.patch` - only needed with `CONFIG_VHOST`
  enabled (the phone has no vhost symbols in `System.map`, so the vendor never
  built that file); it matches the signature used by upstream and by Motorola's
  own android-14/15 trees

`scripts/host/apply_shipping_code_delta.py` applies 0002-0005 in order and is
idempotent (it reverse-checks first, so re-running is a no-op).

### 4. Close the remaining gap and *prove* it

The loop that turns "close" into "exact":

1. build the patched tree with the phone's exact `.config` (+ the release
   fragments + the reconstructed one), same toolchain (Android clang 11.0.1
   `r383902`, `ld.lld`);
2. compare the resulting `kallsyms` table against `artifacts/System.map`
   (names, addresses, sizes);
3. every symbol that is missing, extra or at a different address is a missing
   (or extra) patch. The first two candidates (`fget_many`/`fput_many`) are
   already resolved by patch 0002 - both are `T` symbols in the shipped
   `System.map`, so the RONS split matches the shipping build; the remaining
   known gap is the Unisoc SIPC/JPG/VSP/sensor `.c` side.

Unisoc publishes its monthly security bulletins (CVE lists with the affected
kernel areas); those plus the header delta are the shopping list for the
missing 2023-10 .. 2024-02 patch window.

### 5. Ask for the exact drop

Motorola tags every GPL release per firmware build (`MMI-<build>` tags, see
`git ls-remote --tags`). A compliance request for the exact
**RORS31.335-58-1** drop (build id `612c2`) is the only way to get the real
per-build tree - the 4.14 branch stopped being published after
`RORS31.193-14-6`.

### 6. Alternative: mainline kernel for the same SoC

`https://github.com/sprd-linux/ums9230-mainline-linux` (branch `ums9230`) is
Unisoc's upstream mainline (6.x) tree for UMS9230/T606 - useful for a modern,
patched kernel, but it is *not* the source of the shipped 4.14 kernel.
`https://github.com/sprd-linux/kernel4.14` (branch `sprdroid10_trunk`) is the
generic Unisoc 4.14 tree the Motorola tree is derived from.

## Building the tree

| item | value |
|---|---|
| host | Debian 13 x86_64 (clang + LLD, no cross-gcc required) |
| toolchain | upstream **clang/LLD 11.0.1** (`clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10`) - the same version as the `Android clang 11.0.1 r383902` / `LLD 11.0.1` that built the shipping kernel |
| config | `artifacts/kernel-config` (the phone's own `/proc/config.gz`) with every KVM option switched on |
| tree | `R-11-release-RORS` + patches 0001-0005 |
| script | `scripts/host/build_kernel_vps.sh` (applies the patches, sets the config, builds, prints the artifact sizes) |

```sh
make -j"$(nproc)" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     CC="clang --target=aarch64-linux-gnu-" LD=ld.lld \
     LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
     Image dtbs modules
```

### Build results (2026-10-30, Debian 13 x86_64)

The tree builds clean with patches 0001-0005 and the phone's own config
(`artifacts/kernel-config` + the KVM options enabled):

| artifact | size | note |
|---|---|---|
| `Image` | 25,907,216 B | uncompressed ARM64 kernel; sha256 `ecb8a9ff8e593c4004a53b8d4f68a66af1a26df3c0460a26d8bd4d23a4e8f21c` |
| `System.map` | 97,197 symbols | vs 94,911 in the shipped map: 93,488 common, 3,709 extra (extra built-ins such as KVM/vhost that our config enables), 1,423 only in the shipped build |
| `dtbs` | - | `ums9230-4h10*` devicetrees build |
| `modules` | - | all in-tree modules build |
| version banner | - | `Linux version 4.14.199+-ab612c2 (xscm@ontimbjlx020) ... #3 SMP PREEMPT Fri Oct 30 11:33:04 UTC 2026` |

The release string is reproduced exactly (`4.14.199+-ab612c2`) using a
`localversion` file containing `+` plus `CONFIG_LOCALVERSION="-ab612c2"`, so
vendor `.ko` files would at least pass the `vermagic` check.

Config parity was re-checked against the *shipping* config extracted from the
`IKCFG_ST` blob inside the stock `kernel.bin` (`artifacts/kernel-build/
stock_config.txt`): **0 differing entries** versus the config we build with, so
the build config is not a variable.

The built image header was decoded and is self-consistent with the stock one
(`0x00` `b stext`, `0x08` text_offset `0x80000`, `0x10` `_end-_text`
`0x1bb1000` vs stock `0x1b29000`, `0x18` flags `0xa`, magic `ARM\x64`).

**Booting it is the open problem.** `fastboot boot` is not a RAM-boot path on
this bootloader - it acknowledges any payload (including random bytes) and
reboots, so nothing in the image is ever executed. This was proven with
byte-patched stock controls; details and controls are in
[05-bootloader-unlock-research.md](05-bootloader-unlock-research.md) ("Can the
bootloader run a kernel from RAM?") and
[evidence/2026-10-30-fastboot-ram-boot-dead-end.txt](evidence/2026-10-30-fastboot-ram-boot-dead-end.txt).
Running the built kernel therefore needs a write to `boot_b` (restore image:
`artifacts/bootloader/bl3/boot_b.img`, sha256 `CCD0FAFF…`) - and that write is
also refused: `fastboot flash` rejects even the phone's own byte-identical stock
images with `Please verify the signature!` (tested on `boot_b`, `misc`,
`dtbo_a`; see [evidence/2026-10-30-flash-gate.txt](evidence/2026-10-30-flash-gate.txt)).
A `dd` write from rooted Android works in principle but is a one-way trip,
because nothing can be flashed back afterwards. The full boot-critical backup
(25 partitions, hash-verified) is in
`D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\`.

Known risk if it is flashed: the vendor modules (notably `mali_kbase.ko`) are
built against the shipping tree, and 125 of 282 `__crc_` values differ, so they
will refuse to load on our image - the GPU (and possibly the UI) may not come
up.

### The published tree does not compile as it stands

Three separate defects block a build; none of them is a difference against the
shipping kernel, they are just bugs in what Motorola published:

| # | symptom | cause | patch |
|---|---|---|---|
| 1 | `mm/rmap.c`: `anon_vma` has no member `degree`; `fget_many`/`fput_many` undeclared | only the header half of the 2024 backport was measured into the tree | 0001 + 0002 |
| 2 | `drivers/devfreq/sprd/sprd_dfs_auto_drv.c`: `'./sprd_dfs_trace.h' file not found` | `sprd_dfs_trace.h` uses `TRACE_INCLUDE_PATH .`, but the directory is not on the include path | 0003 |
| 3 | `drivers/staging/sprd/sfp/sfp_tuple.c`: `'sfp.h' file not found with <angled> include` | `#include <sfp.h>` where every sibling uses `"sfp.h"`, and no `-I$(src)` | 0004 |

A fourth stop only appears **because we enable KVM**: `CONFIG_VHOST=y` compiles
`drivers/vhost/vhost.c`, a file the phone never built (its `System.map` has no
`vhost_*` symbol). Modern clang rejects `switch (int ioctl)` over the unsigned
`_IOC()` command word under `-Werror`; patch 0005 changes the parameter to
`unsigned int`, which is what upstream and Motorola's own android-14/15 trees
use. This is a property of *our* config, not of the shipping kernel.

## Windows notes (checkout gotchas)

`get_kernel_source.ps1` sets these automatically; they are listed because a
plain `git clone` will silently produce a tree that no longer matches the
phone.

* `core.protectNTFS=false` - the tree contains `aux.h` / `aux.c`
  (`include/soc/arc/aux.h`, `drivers/gpu/drm/nouveau/nvkm/subdev/i2c/aux.*`),
  which are reserved device names on Windows; git refuses to create them.
  Those 3 files stay missing, they are irrelevant for this device.
* `core.autocrlf=false` - otherwise the checkout converts every file to CRLF
  and *no* header matches the phone's copy any more.
* `core.symlinks=false` - no symlink support on NTFS.
* NTFS is case-insensitive and the tree contains `xt_CONNMARK.h` **and**
  `xt_connmark.h` (different content) - one of them overwrites the other in
  the worktree. `compare_kernel_source.py` resolves such files straight from
  the git object store, so the comparison stays correct on Windows.
* Clone with `--filter=blob:none --no-checkout` (blobless): the local clone
  holds 17.5 GB of git objects (the pack is not repacked) and a 0.8 GB
  worktree.
* C: is nearly full - keep the tree on `D:\AndroidSDKTools`.

## Scripts and artifacts added

| file | purpose |
|---|---|
| `scripts/host/get_kernel_source.ps1` | clone + Windows-safe checkout + apply the deltas (header, `.c`, build fix) + optional verification |
| `scripts/host/compare_kernel_source.py` | config / Kconfig / header comparison tree vs phone |
| `scripts/host/apply_shipping_header_delta.py` | apply (or dry-run) the measured 7-header delta on a checkout |
| `scripts/host/apply_shipping_code_delta.py` | apply (or dry-run) patches 0002 + 0003, idempotent |
| `scripts/host/build_kernel_vps.sh` | full `Image dtbs modules` build on a Linux host with upstream clang/LLD 11.0.1 |
| `scripts/host/reconstruct_release_config.py` | reconstruct the unpublished release config fragment from `/proc/config.gz` |
| `scripts/host/extract_kheaders.py` | extract the IKHEADERS tarball on Windows (skips reserved names) |
| `scripts/host/compare_device_tree.py` | live `/proc/device-tree` vs public DTS |
| `scripts/device/dump_device_tree.sh` | dump `/proc/device-tree` from the phone (needs root) |
| `patches/kernel-sprd/0001-sprd-backport-rors31.335-58-1-header-delta.patch` | the measured header delta as a git patch |
| `patches/kernel-sprd/0002-sprd-backport-rors31.335-58-1-mc-delta.patch` | the matching `.c` half, taken verbatim from branch `R-11-release-RONS` |
| `patches/kernel-sprd/0003-sprd-build-fix-devfreq-trace-include.patch` | `ccflags-y += -I$(src)` for `drivers/devfreq/sprd` (the tree does not build as published) |
| `patches/kernel-sprd/0004-sprd-build-fix-sfp-include-path.patch` | `ccflags-y += -I$(src)` for `drivers/staging/sprd/sfp` (`<sfp.h>` cannot resolve otherwise) |
| `patches/kernel-sprd/0005-vhost-unsigned-ioctl-cmd.patch` | `unsigned int ioctl` in `vhost_vring_ioctl()` - required only when `CONFIG_VHOST` is on |
| `patches/kernel-sprd/reconstructed_release_diff_config` | the reconstructed production config fragment (Motorola/Unisoc format) |
| `patches/kernel-sprd/reconstructed_release.config` | the same fragment in classic diffconfig format |
| `artifacts/kernel-src/source_vs_device.md` | full comparison report (config + symbols + headers) |
| `artifacts/kernel-src/dt_vs_tree.md` | device tree vs DTS report |
| `artifacts/kernel-src/*.defconfig`, `*_diff_config` | the exact build inputs fetched from the public tree |

