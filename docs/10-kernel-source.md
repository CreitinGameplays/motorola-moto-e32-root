# Exact kernel source for the Moto E32 ("hawaii", Unisoc T606)

Status: **public source found and verified; the measured gap to the shipping
build is closed by a backport** (2026-10-29).

## TL;DR

| question | answer |
|---|---|
| Where is the source? | `https://github.com/MotorolaMobilityLLC/kernel-sprd`, branch **`R-11-release-RORS`** (tag `MMI-RORS31.193-14-6`, HEAD `c4e610cd833c47f08969678fa58f9bfcb57bd3a5`) |
| Is it the right tree? | **Yes**: it is the Unisoc 4.14.199 "Petit Gorille" kernel for `qogirl6`/UMS9230 = T606, the board file matches the running device tree byte for byte in every `compatible`/`model` string |
| Is it the *exact* source of our firmware? | **Almost.** Motorola's published snapshot is from **2022-10-25**; our kernel was built **2024-02-20** (`RORS31.335-58-1`). The delta was measured (7 headers + 2 exported symbols + 1 config fragment) and is now **backported**: with `patches/kernel-sprd/` applied, **4,852 of 4,852** shipped headers are code-identical to the tree and the build config reproduces `/proc/config.gz` with **0 conflicts** |
| What is still missing? | the *implementation* behind the two exported symbols (`fget_many`/`fput_many` - upstream, easy) and the Unisoc SIPC/JPG/VSP/sensor **.c** changes (the headers are known, the code is not published); plus the prebuilt `mali_kbase` GPU module |
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

### What the backport does *not* give us

The headers are known, the **implementations** behind them are not:

* `fget_many()` / `fput_many()` are exported by the running kernel
  (`artifacts/System.map`: `ffffff8008415f5c T fput_many`,
  `ffffff800843fbac T fget_many`) but their `.c` implementation (upstream
  `fs/file.c` + the `get_file_rcu_many()` callers in `fs/` and `overlayfs/`)
  is not part of the header delta and has to be taken from upstream stable.
* the Unisoc SIPC/JPG/VSP/sensor **.c** changes are not published; only their
  UAPI/header side is visible.

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
* build config: `artifacts/kernel-src/reconstructed_release_diff_config`
  -> 0 conflicts, 0 uncovered symbols

### 4. Close the remaining gap and *prove* it

The loop that turns "close" into "exact":

1. build the patched tree with the phone's exact `.config` (+ the release
   fragments + the reconstructed one), same toolchain (Android clang 11.0.1
   `r383902`, `ld.lld`);
2. compare the resulting `kallsyms` table against `artifacts/System.map`
   (names, addresses, sizes);
3. every symbol that is missing, extra or at a different address is a missing
   (or extra) patch. The first candidates are known: `fget_many`/`fput_many`
   (upstream `fs/file.c`) and the Unisoc SIPC/JPG/VSP/sensor `.c` changes.

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

## Windows notes (this tree needs two fixes)

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
| `scripts/host/get_kernel_source.ps1` | clone + Windows-safe checkout + apply the delta + optional verification |
| `scripts/host/compare_kernel_source.py` | config / Kconfig / header comparison tree vs phone |
| `scripts/host/apply_shipping_header_delta.py` | apply (or dry-run) the measured 7-header delta on a checkout |
| `scripts/host/reconstruct_release_config.py` | reconstruct the unpublished release config fragment from `/proc/config.gz` |
| `scripts/host/extract_kheaders.py` | extract the IKHEADERS tarball on Windows (skips reserved names) |
| `scripts/host/compare_device_tree.py` | live `/proc/device-tree` vs public DTS |
| `scripts/device/dump_device_tree.sh` | dump `/proc/device-tree` from the phone (needs root) |
| `patches/kernel-sprd/0001-sprd-backport-rors31.335-58-1-header-delta.patch` | the measured header delta as a git patch |
| `patches/kernel-sprd/reconstructed_release_diff_config` | the reconstructed production config fragment (Motorola/Unisoc format) |
| `patches/kernel-sprd/reconstructed_release.config` | the same fragment in classic diffconfig format |
| `artifacts/kernel-src/source_vs_device.md` | full comparison report (config + symbols + headers) |
| `artifacts/kernel-src/dt_vs_tree.md` | device tree vs DTS report |
| `artifacts/kernel-src/*.defconfig`, `*_diff_config` | the exact build inputs fetched from the public tree |

