# 13 - Recovering the phone: state of the boot chain

Status: **in progress. The phone does not boot; the fault is below U-Boot.**
Evidence: [evidence/2026-10-30-brom-recovery.txt](evidence/2026-10-30-brom-recovery.txt).

Context: root/unlock is already solved and documented (docs 06, 07, 09).
This file is only about getting the device booting again so the KVM
kernel work in [12](12-slot-b-testing-channel.md) can resume.

## What happened

Slot `b` was the test channel. `boot_stock_signed.img` booted Android on
`_b` in 25 s. The next image, the KVM-off control
`boot_diagstock_avb.img`, hung after the logo for 244 s. The slot block had
been set to give `b` a single attempt (`0x001f`), so after that failure `b`
became unbootable and the bootloader should have fallen back to slot `a`.

Slot `a` holds the proven restore rescue (`fc3ca0ef...44c0`), which repairs
`boot_b` from an embedded stock blob and reboots into Android. It was
verified end-to-end before this happened.

That fallback never completes. The phone is now permanently black.

## The decisive observation: no logo, ever

On this device the Motorola logo is drawn by the **bootloader (U-Boot)**
from the `logo` partition. The KVM-off hang itself proved it: logo, then
no adb. So *U-Boot running* and *logo visible* are the same event.

Since the hang the user has seen no logo, no backlight, not even a flicker,
on every attempt, including a 3-minute untouched Power-alone test.

Therefore U-Boot never starts, and the failure is one step earlier:

```
BootROM --(load + verify SPL from UFS)--> SPL/sml --> U-Boot --> boot.img
     ^------------------- we never get past here --------------------^
```

This is important because it **clears everything we modified**:

| suspect | verdict |
|---|---|
| `boot_b` (the hung kernel) | irrelevant - loaded by U-Boot, which never runs |
| `misc` A/B block / slot fallback | irrelevant - same reason |
| `boot_a` rescue | irrelevant - it is a `boot.img` too |
| `mali_kroot` / root changes | irrelevant - userspace never starts |
| stuck Volume Down key | ruled out - a stuck Vol-Down makes plain Power enumerate, and it does not |

If U-Boot *were* running, the exhausted slot `b` would send it to slot `a`,
the rescue would spend ~40-60 s black and then produce Android. Three
untouched minutes produced nothing.

## USB state

Two and only two nodes are ever seen, never adb, never fastboot:

```
USB\VID_1782&PID_4D00\5&E7DA5E8&0&1   Status OK, CM_PROB_NONE
                                     -> real Unisoc BootROM
USB\VID_0000&PID_0002\5&E7DA5E8&0&1   CM_PROB_FAILED_POST_START
                                     -> "Device Descriptor Request Failed"
```

Descriptors of the good node: `1782:4d00`, `bcdDevice 0x0202`, vendor
specific interface, bulk `0x85` IN / `0x06` OUT, 512 B, config
`bmAttributes 0xc0` (self powered), 100 mA.

So the BootROM is healthy and the USB link can be good. What varies is
whether the current node is *fresh*.

## Stale vs fresh BootROM

This cost the most time and is worth stating plainly:

* A BootROM node that has been on the bus for a while still **enumerates**,
  but its command handler is idle. `spd_dump` attaches (`libusb_control_transfer
  ok`) and then every receive times out, ending in
  `wrong command or wrong mode detected`.
* A **freshly entered** BootROM answers immediately:

```
libusb_control_transfer ok
CHECK_BAUD bootrom
BSL_REP_VER: "SPRD3\0"
CMD_CONNECT bootrom
```

So "wrong command or wrong mode" means *stale session*, not wrong chip and
not a dead phone. Each fresh session lasts only a couple of minutes, then
the node goes idle again.

## `chip_uid` is the wrong command at this stage

The 17:06 fresh session answered CHECK_BAUD and CONNECT and then timed out
on `chip_uid`. That is expected: `chip_uid` is an **FDL1/FDL2** command.
The BootROM-stage reads are (from `spd_cmd.h`):

| cmd | meaning | reply |
|---|---|---|
| `0x07` | READ_CHIP_TYPE | `0x94` |
| `0x0D` | READ_FLASH_INFO | `0x9B` |
| `0x2D` | READ_PARTITION | `0xBA` |
| `0x1A` | READ_CHIP_UID | `0xAB` |
| `0x19` | CHECK_ROOT | `0xA7` if rooted, else `0x80` |
| `0x35` | DUMP_UBOOT_LOG | `0xBB` |

Our earlier probes therefore proved nothing: they asked an FDL question at
the BootROM, or they asked anything at all of an idle node. The correct
read-only probe set has **not yet run on a fresh session**.

Commands that must *not* be sent are `0x2A` (SET_FIRST_MODE), `0x49`
(WRITE_PARTITION_VALUE) and `0x47` (WRITE_EFUSE): they touch `miscdata` or
efuses and can make a recoverable device unrecoverable.

## Current diagnosis, and the fork it creates

The BootROM is fine; it is not getting to U-Boot. Two candidate causes:

**(a) BootROM cannot initialise or read the UFS.** Power/PMIC marginal, or a
UFS/board fault. A brownout during UFS init looks exactly like this: the SoC
runs, USB works, but the flash never comes up, so no SPL is loaded. The
intermittent `VID_0000&PID_0002` descriptor failure is the same signature,
and so is "auto-disconnects after a few minutes".

**(b) UFS reads fine, but the SPL is corrupt or fails verification.** Then
the fix is a reflash of `uboot`/`sml`, which needs an FDL1/FDL2 for this
exact UMS9230-UFS build.

The probe set separates them:

* `0x0D` (flash info) / `0x2D` (partition table) **succeed** -> (b).
* they **fail or return errors** -> (a).

## Recovery ladder

1. **Fresh read-only BootROM probe.** The only action that produces new
   information. `scripts/host/brom_catch.ps1` waits for the stale node to
   vanish, then fires `0x07/0x0D/0x2D/0x1A/0x19` the moment a new
   `1782:4D00` appears.
2. **Rule out power.** Charge from a wall charger for 2-3 h, undisturbed,
   then Power alone, untouched for 3 min. Cheap, and (a) is a live
   hypothesis.
3. **If UFS reads but SPL is bad:** obtain this device's own firmware
   package (XT2227-1, Unisoc T606) and extract its FDL1/FDL2, then reflash
   `uboot`/`sml`. Do **not** try an FDL from a different SoC: on UFS a
   mismatched FDL bricks (TomKing062).
4. **If UFS does not read:** it is hardware. No software path remains.

## Things that are NOT fixes

* Writing the stock `misc.img` back as-is. Stock has *both* slots
  `successful=1` with slot `b` at the higher priority (14 vs 15), so it
  selects slot `b` = the hung kernel. Any restored block must force slot
  `a`. (Decoded in the evidence file.)
* `fastboot flash` of anything: the signature gate refuses even the
  phone's own byte-identical images ([11](11-flash-gate.md)).
* The CVE-2022-38694 FDL route: no FDL1/FDL2 exists for `ums9230`, only a
  96-byte `custom_exec_no_verify_65015f08.bin` and a stack-info CSV.
* `fastboot set_active a`: needs a working fastboot, which needs U-Boot,
  which does not run.
* `sml_a.img` / `uboot_a.img` / `trustos_a.img` as FDL candidates: all
  three are DHTB-wrapped (`4448544201000000`) and are loaded *by* the
  download, not used as FDL. `sml` is ARM Trusted Firmware.

## Open questions

- Does the BootROM read this UFS at all (`0x0D`, `0x2D`)?
- Is the SPL partition still intact on flash, or was it damaged?
- Does the phone attempt a normal boot and stall silently (no USB) - i.e.
  is the SoC actually resetting on each Power press?
- What does `0x35 DUMP_UBOOT_LOG` return? If it returns bytes, U-Boot ran
  at some point; if empty, it never did.