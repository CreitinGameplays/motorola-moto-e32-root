# 09 - GSI boot as independent proof of the unlock

The unlock in [06](06-secure-world-unlock-path.md) was verified with
`getprop` and with the U-Boot command line. A stronger, harder-to-fake
proof is booting a **foreign, unsigned system image**: a Generic System
Image has no Motorola signature at all, so if it boots, the bootloader
provably skipped the verified-boot policy for it.

That was done on 2026-10-29: an Android 15 GSI installed with
[DSU-Sideloader](https://github.com/VegaBobo/DSU-Sideloader) boots on the
device. Captured data is in
[evidence/2026-10-29-gsi-boot.txt](evidence/2026-10-29-gsi-boot.txt).

## Why a GSI proves the unlock

DSU-Sideloader lists **"Unlocked Bootloader"** as a hard requirement, and
Android's `gsid` will not install or boot a DSU image on a locked
bootloader - only OEM-signed GSIs are allowed there. The failure mode on a
locked device is exactly the one we would expect: the GSI boots and then
fails verification, or never boots at all.

Our unlock marker changes the boot-time verified-boot policy
(`ro.boot.flash.locked=0`, `ro.boot.verifiedbootstate=orange`,
`androidboot.vbmeta.device_state=unlocked`), which is precisely the
condition the GSI needs. So a booting GSI is an *independent* confirmation
of the same state, reached through a completely different code path
(Android's own bootloader-state check plus the boot chain's tolerance of an
unsigned system).

## What is running

| property | value |
|---|---|
| `ro.build.fingerprint` | `google/treble_arm64_bvS/tdgsi_arm64_ab:15/AP4A.241205.013.C1/250106:userdebug/test-keys` |
| `ro.product.model` | `TrebleDroid_vanilla` (Android 15, sdk 35) |
| `ro.bootimage.build.fingerprint` | `motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys` |
| `ro.vendor.build.fingerprint` | `motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys` |
| `ro.boot.flash.locked` | `0` |
| `ro.boot.verifiedbootstate` | `orange` |
| `ro.boot.vbmeta.device_state` | `unlocked` |

The stock Motorola **boot** image and **vendor** are untouched; the GSI is
layered on top as a *userspace DSU*:

```
gsi_tool status
  running
  installed
  disabled
  [0] dsu
  installed: userdata_gsi
  AVB public key (sha1): [NONE]
  installed: system_gsi
  AVB public key (sha1): cdbb77177f731920bbe0a0f94f84d9038ae0617d
```

with `ro.gsid.image_running=1`, `ro.gsid.dsu_slot=dsu` and
`vold.has_adoptable=1`. The stock `system_b` partition is still in
`super`, so the original Android 11 is one reboot away.

`/metadata/gsi/dsu/one_shot_boot` is `1` and `install_status` is
`disabled`: the DSU is **single-boot**, not sticky. A plain reboot returns
to the stock Motorola system; to stay in the GSI use `gsi_tool enable`
(sticky) or `gsi_tool enable -s` (single boot) from the stock system, or
the DSU notification in the stock system's shade.

## Back to stock: the unlock survives the whole session

Rebooting out of the single-boot DSU returns the device to the stock
Motorola Android 11, and it comes back **still unlocked**:

```
ro.build.fingerprint     = motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys
ro.build.version.release = 11
ro.boot.flash.locked     = 0
ro.boot.verifiedbootstate= orange
```

The marker in `miscdata[0x2000]` read back after that reboot is
byte-identical to the one that was written (`artifacts/marker.bin` ==
`artifacts/marker_readback_after_gsi.bin`), and the `uboot_log` partition
still carries `androidboot.vbmeta.device_state=unlocked`. The GSI session
touches neither the marker nor the stock partitions, so trying GSIs is
reversible - as long as the DSU is single-boot (or is wiped with
`gsi_tool wipe`).

## U-Boot's view

From the live `uboot_log` partition of the GSI boot:

```
avb_slot_verify.c:1609: DEBUG: avb_slot_verify() avb slot verify OK!
g_sprd_vboot_cmdline is androidboot.vbmeta.device=PARTUUID=1.0
  androidboot.vbmeta.avb_version=1.1 androidboot.vbmeta.device_state=unlocked
  androidboot.vbmeta.size=18944 androidboot.vbmeta.digest=50535c59a5...
  androidboot.vbmeta.invalidate_on_error=yes androidboot.veritymode=enforcing
g_sprd_vboot_cmdline is ... androidboot.vbmeta.device_state=unlocked ...
  androidboot.vbmeta.size=45888 androidboot.vbmeta.digest=2610ae5728...
set_root_of_trust succeeded.
```

Two vbmeta descriptors show up - the stock 18944-byte one and the GSI's
45888-byte one - and both are accepted while `device_state=unlocked`. The
boot chain that ran is the stock Motorola one (`ro.hardware=ums9230_4h10`,
Unisoc T606); only the system image is foreign.

## Side effect: the GSI is userdebug

The GSI is a `userdebug`/`test-keys` build, so root is available without
the Mali exploit:

```
adb root
  restarting adbd as root
id
  uid=0(root) gid=0(root) groups=0(root),... context=u:r:su:s0
```

This only exists while the GSI is running. The stock Motorola system is a
`user/release-keys` build, where `adb root` is refused and the runtime
root from this repo is still the way in.

## The Quickstep launcher crash is a GSI bug, not an unlock problem

The GSI's home app (`com.android.launcher3`, the Quickstep launcher)
crashes on startup:

```
java.lang.SecurityException: Permission Denial: getRootTaskInfo() from
  pid=2704, uid=10105 requires android.permission.MANAGE_ACTIVITY_TASKS
  at com.android.launcher3.uioverrides.QuickstepLauncher
```

Measured on the device:

| check | result |
|---|---|
| launcher location | `/system/system_ext/priv-app/Launcher3QuickStep/Launcher3QuickStep.apk` (privileged app) |
| launcher signature | `signatures:[d7f1f224]` |
| platform signature | `signatures:[b4addb29]` |
| privapp allowlist for the launcher | none (no launcher file among the 30 XMLs in `/system/etc/permissions/`) |
| `ro.control_privapp_permissions` | `log` |
| `pm grant com.android.launcher3 android.permission.MANAGE_ACTIVITY_TASKS` | `SecurityException: ... is not a changeable permission type` |
| `cmd package resolve-activity -c android.intent.category.HOME` | `No activity found` |

`MANAGE_ACTIVITY_TASKS` is `signature|privileged`. The launcher is a
privileged app but carries a **different key than the platform**, so the
signature match fails, and the GSI ships no privapp allowlist entry to
grant it another way. It is a platform (signature) permission, so it
cannot be granted at runtime either. The result is a launcher with no home
activity at all.

This is a property of the image, not of the unlock: a stock Motorola
`com.motorola.launcher3` works fine, and the crash reproduces on any
device running that GSI.

**Workarounds**

1. Sideload a different launcher APK (this GSI has no Play Store -
   `com.android.vending` is absent), e.g.
   `adb install Lawnchair.apk` or `adb install KISSLauncher.apk`, then
   `adb shell cmd package set-home-activity <component>`.
2. Reboot back into the stock Motorola system (the DSU is single-boot) and
   use `com.motorola.launcher3`.
3. Keep the DSU and make it sticky (`gsi_tool enable`) before experimenting
   with the GSI, so a reboot does not drop you back to stock.

## What this changes in the previous write-ups

* [06](06-secure-world-unlock-path.md): the unlock is no longer only
  "the properties say unlocked" - a foreign unsigned system image boots.
* [07](07-unlock-how-to.md): the "what this does *not* unlock" section
  needs the DSU/GSI case spelled out - the boot-time AVB policy change is
  exactly what lets a GSI boot; the fastboot *download* gate is a separate
  mechanism and was still rejecting unsigned requests when last probed.
* The debloat list in [08](08-debloat.md) applies to the stock system. The
  GSI has its own package set (9 Google apps + launcher3 + a handful of
  AOSP apps); the user-0 removals done earlier still apply to the stock
  system because they live in `/data`.
