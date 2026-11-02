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

1. `incrementalfs`: rebuild from AOSP (source exists, small, self-contained,
   and its absence affects Play Store/app updates on /data). Quick win.
2. WiFi (`sprdwl_ng`): try source hunt (Transsion/HMD/realme UMS9230 drops,
   qogirl6 variant, SC2355 per the .ko strings). If found, port like mali.
   If not found, evaluate option 3 (force-load probe) carefully.
3. Camera (`sprd_camera` + `sprd_sensor` + `sprd_cpp` + `sprd_fd` +
   `sprd_flash_drv` + `flash_ic_ocp8135b`): biggest chunk; same source hunt
   (`sprd_camera` is the common Unisoc camera driver, the sensor-specific
   parts live in vendor trees).
4. BT (`sprdbt_sdio_tty`)/FM/SAR: likely die with WiFi (same WCN stack)
   or are trivial once the WCN bus hal matches.

## Verification data (from the running device)

- `/mnt/vendor/socko/` = 19 .ko files, dated 2024-02-20 (matches the build).
- The WCN bus (marlin/sdiohal) is in-tree and initializes fine
  (`marlin 87000000.sprd-marlin3`, `wcnmodem` firmware partition found,
  GNSS downloads at t+5.6 s) - so the WiFi failure is purely the
  `sprdwl_ng.ko` module load, not the bus.
- Camera rc: `/vendor/etc/init/camera.rc` insmods sprd_sensor ->
  sprd_flash_drv -> sprd_camera -> sprd_cpp -> mmdvfs -> sprd_fd in order,
  all failing on CRC.
