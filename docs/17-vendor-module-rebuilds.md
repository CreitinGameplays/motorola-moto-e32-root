# Vendor module rebuild for WiFi + camera on the custom kernel (plan, 2026-11-02)

State: the custom kernel boots Android fully (GPU via Magisk autoload), but
WiFi and camera are dead because their vendor kernel modules refuse to load:
every `insmod` from `/vendor/etc/init/*.rc` fails with
`disagrees about version of symbol module_layout` -> `Exec format error`
(the MODVERSIONS CRC mismatch: our kernel's `module_layout` CRC is
`0x22ad1303`, the vendor's is `0x36aac43d`; ~130/282 CRCs differ per module).

Full list of failing vendor modules (nolto dmesg, artifacts/kernel-build/nolto_dmesg_live.txt):

    incrementalfs (system/userdata incremental FS - also dead!)
    sprd_sensor, sprd_flash_drv, sprd_camera, sprd_cpp, mmdvfs, sprd_fd
    aw9610x_sar, flash_ic_ocp8135b
    sprdbt_sdio_tty (BT), sprd_sdio_fm (FM)
    sprdwl_ng (WiFi)
    mali_kbase (GPU - already replaced by the in-tree module)

## Source availability (checked 2026-11-02)

The OSS drop (`kernel-sprd` @ R-11-release-RORS) does NOT contain the
sources of most of these:

- `sprdwl_ng` (WiFi): no `drivers/net/wireless/sprd` at all; only
  `drivers/misc/sprdwcn_temp/` (SDIO/PCIE/SIPC bus hal + boot + gnss) and
  `drivers/misc/sprd_wcn_n6pro/` (wcn bsp sdio/pcie). No `sprdwl_ng` symbol
  anywhere in the tree.
- `sprd_camera`/`sprd_cpp`/`sprd_fd`/`sprd_sensor`/`mmdvfs`: no camera/
  sensor driver dirs exist in the drop (checked drivers/media/platform,
  drivers/iio, staging/sprd).
- `mali_kbase`: already solved in-tree (r28p0 DDK import).
- `incrementalfs`: AOSP's incrementalfs, source is in the AOSP tree
  (system/core/incremental_delivery/Incremental.cpp kernel module) - this
  one is rebuildable from AOSP, not from the vendor drop.

So a same-source rebuild is only possible for modules whose source exists.
For the rest the options are:

1. **Unisoc GPL drops from other T606/T612/T7600 phones** (the route that
   worked for mali): the DDK/WiFi/camera sources ship in some OEM drops
   (e.g. Transsion UMS9230, HMD, realme T7600). Need to hunt for
   `sprdwl_ng`/`sprd_camera` sources with matching UK versions
   (`vermagic` in the vendor .ko: `4.14.199+`... module date 2024-02-20).
2. **Rebuild with CRC stubs**: build the vendor tree's own
   `kernel-headers`-equivalent... not possible, sources missing.
3. **Disable MODVERSIONS in our kernel** (config-only): then ANY module
   with a matching vermagic loads, but the 130 differing CRCs mean
   silently-wrong struct layouts -> crashes. Rejected before (ABI-unsafe).
   Partial variant: keep MODVERSIONS but force-load specific modules with
   `insmod -f` (kernel accepts a CRC mismatch per-symbol when
   `CONFIG_MODULE_FORCE_LOAD=y`): same ABI risk, but contained to the
   module being forced, and reversible. Could be a quick probe for
   sprdwl_ng to see if it actually works despite the CRC differences.
4. **Paravirt approach**: build shims... overkill.

## Recommended order

1. `incrementalfs`: **already in the tree** (`fs/incfs`, `CONFIG_INCREMENTAL_FS=m`),
   and a 4.14.199+ vermagic-matching `incrementalfs.ko` is built in the VPS
   object tree - it just needs to be shipped in a Magisk module like mali.
   Quick win, unblocks Play/app incremental updates.
2. WiFi (`sprdwl_ng`): source located - the **mu300-linux** project keeps
   the Unisoc SC2355 "combo" WLAN driver alive
   (`upstream/modules/sprd_wlan_combo`, GPL-2.0 Unisoc 2021-2022 drop, the
   same sprdwl family with KERNEL_VERSION gates down to 4.14). The vendor
   `.ko` on the phone identifies as SC2355, and our tree already contains
   the WCN bus it plugs into (`drivers/misc/sprdwcn`, built-in: marlin
   probe + `include/misc/marlin_platform.h` + `mchn.h` + `wcn_bus.h` with
   `sprdwcn_bus_chn_init`), which the live dmesg shows initializing fine.
   **Imported into the kernel tree** as `drivers/net/wireless/sprd_wlan/`
   (common/ + sc2355/, SDIO variant, in-tree Kbuild/Kconfig, new
   `CONFIG_SPRD_WLAN_COMBO`), per the "put drivers in the custom kernel
   tree" rule. 4.14 port in progress (compile-fix rounds):
   - `nl80211.h`: the Android tree already has `NL80211_WAPI_VERSION_1`
     (no shim needed; mu300's compat header assumed mainline headers)
   - `timer_shutdown_sync` -> `del_timer_sync` (compat header)
   - `change_beacon`: 6.0 `cfg80211_ap_update` vs 4.14
     `cfg80211_beacon_data` (version-gated)
   - `set_wiphy_params`: 6.1 added `radio_idx` (version-gated)
   - `tdls_mgmt`: 6.6 added `link_id` (version-gated, .c+.h)
   - `sprd_wlan_remove`: void -> int (4.14 platform_driver)
   - `iface.c`: `wcn_mu300_recover` (mu300-only) stubbed out, missing
     `linux/of.h`/`etherdevice.h` includes added, `fallthrough` ->
     comment, `eth_hw_addr_set` -> `memcpy(dev->dev_addr)` (7 sites)
   - `npi.c`: genl 6.x split-ops -> 4.14 `struct genl_ops` with per-op
     `.policy` (family-level `.policy` is 6.x-only)
   - `report.c`/`scan.c`: `ktime_get_boottime_ts64` (5.0) ->
     `ktime_get_boot_ns` (4.14), version-gated
   - `sprd_wlan_power_status_sync` (mu300 helper, used by the driver's
     power paths): added to the in-tree WCN bus
     (`drivers/misc/sprdwcn/wcn_bus.c` + declaration in
     `include/misc/wcn_bus.h`) - built-in, so the kernel Image relink
     carries the export
   - `mm.h`: `linux/dma-direct.h` (5.x) -> `linux/dma-mapping.h`
   - `tx.c`: `sc2355_set_thread_uclamp` -> no-op (util clamp is 5.4+;
     the driver's RT priorities carry the intent)
   - `vendor.c`: 4.20+ `.policy`/`.maxattr` designators and
     `VENDOR_CMD_RAW_DATA` sentinel dropped (4.14
     `wiphy_vendor_command` has neither; the handlers parse with the
     policy tables themselves)
   - `sdio.c`: `fallthrough` -> comment
   - Kbuild: SC2355 + SDIO **and** PCIE objects are linked (the calls
     are guarded by runtime `hw_type == SPRD_HW_SC2355_PCIE` checks;
     dropping pcie.o left 29 undefined symbols)
   - Magisk module skeleton: `modules/sprd-wlan-combo/` (loads at
     post-fs-data after the Mali module; logs to
     `/data/local/tmp/wlan_module_load.log`), installer
     `scripts/host/install_wlan_magisk_module.ps1`

Port lessons (for the camera stack later): the mu300 tree's sources are
5.4-shaped with KERNEL_VERSION gates mostly for 5.15/6.x; 4.14 needs the
*older* API forms (genl per-op policy, no util clamp, no
`ktime_get_boottime_ts64`, `eth_hw_addr_set` by hand, `fallthrough`
comment, `.remove` returns int). All fixes are in-tree, gated where the
mu300 tree might be reused for newer kernels.
3. Camera (`sprd_camera` + `sprd_sensor` + `sprd_cpp` + `sprd_fd` +
   `sprd_flash_drv` + `flash_ic_ocp8135b`): same source hunt next; no
   candidate found yet (OSS drop has nothing).
4. BT (`sprdbt_sdio_tty`)/FM/SAR: mu300 also keeps `sprdbt_tty`; BT may
   follow the same route once WiFi works.

## Verification data (from the running device)

- `/mnt/vendor/socko/` = 19 .ko files, dated 2024-02-20 (matches the build).
- The WCN bus (marlin/sdiohal) is in-tree and initializes fine
  (`marlin 87000000.sprd-marlin3`, `wcnmodem` firmware partition found,
  GNSS downloads at t+5.6 s) - so the WiFi failure is purely the
  `sprdwl_ng.ko` module load, not the bus.
- Camera rc: `/vendor/etc/init/camera.rc` insmods sprd_sensor ->
  sprd_flash_drv -> sprd_camera -> sprd_cpp -> mmdvfs -> sprd_fd in order,
  all failing on CRC.

## 2026-11-03: the exact vendor build config was recovered (CRC breakthrough)

The vendor `.ko` files expect the CRCs of the *shipping* kernel build. That
build's exact `.config` was recovered from the kernel Image itself: the
IKCONFIG blob is a gzip stream in `.rodata` whose payload is the .config text
(`scripts/host/find_ikconfig.py`). Source images: the untouched day-one
dumps (`bootimg.py unpack <backup>/boot_a.img|boot_b.img`).

    boot_a.img -> 4.14.199+-abc1989, Jan 23 2024, xscm@ontimbjlx014  (old slot)
    boot_b.img -> 4.14.199+-ab612c2, Feb 20 2024, xscm@ontimbjlx020  (matches
                  /mnt/vendor/socko/*.ko: same vermagic + 2024-02-20 date)

Result, saved as `artifacts/kernel-build/stock_kernel_config.txt`
(1472 CONFIG lines). Applied to our tree, `make ARCH=arm64 olddefconfig`
changes only the three options we added (MALI_MIDGARD, SPRD_WLAN_COMBO,
SPRDBT_TTY) -> **the Motorola GPL drop matches the shipping build tree**.

### Why the CRC comparison matters

`module_layout` is exported as a *function*, not a struct:

    void module_layout(struct module *mod, struct modversion_info *ver,
                       struct kernel_param *kp, struct kernel_symbol *ks,
                       struct tracepoint *const *tp)

so its MODVERSIONS CRC covers the type graphs of struct module,
modversion_info, kernel_param, kernel_symbol and tracepoint.

Measured with `scripts/host/vps_module_crc.py` (validated by reproducing our
running custom kernel's known dmesg CRC exactly: 0x22ad1303):

    stock config, CFI on          module_layout = 0x36aac43d  <-- vendor value
    stock config, CFI off         module_layout = 0xec8a4bdb
    our custom #57 config         module_layout = 0x22ad1303
    vendor modules expect         module_layout = 0x36aac43d

**So the shipping kernel was a CFI build**, which the recovered config
confirms (CONFIG_CFI_CLANG=y).  CFI puts a `cfi_check_fn cfi_check;` field
into `struct module` (`include/linux/module.h`, after `num_syms`), and that
field is part of the `module_layout` type graph - hence the single CRC
difference.  The layout effect is visible in the modules themselves:

    vendor .ko relocations in .gnu.linkonce.this_module
        init    at 0x158, cleanup at 0x310   (CFI build: cfi_check at 0x150)
    our CFI-off build
        init    at 0x150, cleanup at 0x310

Ordinary exported symbols DO match the vendor exactly under the stock
config, e.g. kmalloc_caches 0xd2cd0418, msleep 0xf9a482f9,
mutex_lock 0x5e38de65, sprintf 0x91715312, kthread_create_on_node
0x2781fb6f, because CFI/LTO do not change ordinary type graphs.

The vendor modules also import `__cfi_slowpath`, confirming the CFI build.

### Consequence: the compat patch set

LTO/CFI stay off (both hang this board at boot), so only the *ABI effects*
of CFI are reproduced.  Two scripts:
`scripts/host/apply_vendor_module_compat.py` and `..._compat2.py`.

1. `include/linux/cfi.h` + `include/linux/module.h`: make the
   `cfi_check_fn` typedef and `struct module::cfi_check` unconditional so
   the kernel's `struct module` matches the vendor's (verified: our built
   modules now have `.gnu.linkonce.this_module` size 0x380 and
   init/cleanup relocations at 0x158/0x310, exactly like the vendor .ko).
2. `include/linux/timer.h`: make `void (*__function)(struct timer_list *)`
   unconditional.  **This one is easy to miss**: CFI increases
   `struct timer_list` by 8 bytes, and timer_list is embedded in
   `struct dev_pm_info`, which is embedded in `struct device`.  Without the
   field, every `struct device` field after `power` (`of_node`, `fwnode`,
   ...) is 8 bytes off for the CFI-built modules.  Both directions keep
   working: our kernel uses `timer->function`, a CFI module's inline
   setup_timer() stores `__timer_callback` in `function` + the real
   callback in `__function`, and the trampoline is module-local.
   (The only other CFI-conditional definition is
   `struct bpf_binary_header`'s `u32 magic`, which is BPF-JIT internal.)
2b. **Config additions can break the ABI too.**  For the camera-compat build
   the config is stock + only the MALI/WLAN/BT drivers; KVM is deliberately
   left out.  KVM selects `CONFIG_MMU_NOTIFIER` (adds
   `mmu_notifier_mm` to `struct mm_struct`) and
   `CONFIG_PREEMPT_NOTIFIERS` (adds `preempt_notifiers` to
   `struct task_struct`, after `sched_dl_entity`), neither of which the
   vendor kernel has.  Any vendor module touching those structs would then
   read wrong offsets.  Keep the KVM kernel separate (it is already
   verified) unless the vendor modules prove not to care.
3. `kernel/module.c`: `check_modstruct_version()` skips the `module_layout`
   CRC check.
4. `kernel/module.c`: `check_version()` logs a CRC difference at KERN_DEBUG
   and continues instead of refusing the module.
5. `kernel/module.c`: export a no-op `__cfi_slowpath(uint64_t, void *,
   void *)` - same prototype as `kernel/cfi.c`, so symbol lookup and its
   genksyms CRC match.  Nothing calls into the CFI shadow code without CFI.

Why relax all CRC checks instead of keeping them: genksyms' checksum is
computed over a type graph whose *internal numbering depends on parse
order*, so a CFI build and a non-CFI build of the same source produce
different CRCs for most struct-typed symbols even when layouts are
identical.  Measured on `mm/slab_common.c`:

    CFI on  (LTO+CFI flags)   kmalloc_caches = 0x59b0d708
    CFI off                   kmalloc_caches = 0x70422b89
    vendor modules expect     kmalloc_caches = 0xd2cd0418

and the preprocessed declaration is byte-identical in both
(`kmalloc_caches[NR_KMALLOC_TYPES][(12 + 1) + 1]`); only the CFI-only
`struct timer_list`/`cfi.h` text earlier in the unit differs.  The vendor
value is reproduced only by a *stock-config + CFI* build.  Since CFI cannot
boot here, CRC verification must be advisory - the layout patches carry the
ABI compatibility.

Vermagic: the vendor modules carry `4.14.199+-ab612c2 SMP preempt
mod_unload modversions aarch64`.  Build with
`make ... LOCALVERSION=+-ab612c2` (command-line make variable, exported to
`scripts/setlocalversion`) so `UTS_RELEASE` matches byte for byte; no
`.scmversion` is involved.  `CONFIG_MODVERSIONS=y` stays from the stock
config so the `modversions` token remains in the vermagic.

Build recipe: `scripts/host/vps_build_cameracompat.sh` (stock config +
MALI/WLAN/BT/KVM options, LTO/CFI off, `O=/tmp/kbuild`).

## Consequence: the compat patch set

LTO/CFI stay off (both hang this board at boot), so instead of rebuilding
with CFI we reproduce only the ABI effect that matters.
`scripts/host/apply_vendor_module_compat.py` applies three small patches:

1. `include/linux/cfi.h` + `include/linux/module.h`: make the
   `cfi_check_fn` typedef and `struct module::cfi_check` unconditional, so
   the kernel's `struct module` has the vendor's layout (init at 0x158,
   cleanup at 0x310, section size 0x380).
2. `kernel/module.c`: `check_modstruct_version()` accepts the
   `module_layout` CRC difference (returns 1, one pr_info).  Every other
   imported symbol is still CRC-checked, so a real mismatch still fails
   loudly with the symbol name.
3. `kernel/module.c`: export a no-op `__cfi_slowpath(uint64_t, void *,
   void *)` - same prototype as the real handler in `kernel/cfi.c`, so both
   the symbol lookup and its genksyms CRC match.  Without CFI nothing calls
   into the CFI shadow code.

Vermagic: the vendor modules carry `4.14.199+-ab612c2 SMP preempt
mod_unload modversions aarch64`.  Build with
`make ... LOCALVERSION=+-ab612c2` (command-line make variable, exported to
`scripts/setlocalversion`) so `UTS_RELEASE` matches byte for byte; there is
no `.scmversion` involved.  `CONFIG_MODVERSIONS=y` is kept from the stock
config so the `modversions` token stays in the vermagic.

Build recipe: `scripts/host/vps_build_cameracompat.sh` (stock config +
MALI/WLAN/BT/KVM options, LTO/CFI off, `O=/tmp/kbuild`).  Its
`Module.symvers` is checked against all 649 vendor import records (351
unique symbols) with `scripts/host/compare_vendor_crcs.py`.

Then test the vendor camera stack (sprd_sensor -> sprd_flash_drv ->
sprd_camera -> sprd_cpp -> mmdvfs -> sprd_fd); the vendor modules live in
`/mnt/vendor/socko/` and are insmod'ed by `/vendor/etc/init/camera.rc`.
