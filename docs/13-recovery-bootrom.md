# 13 - Recovering the phone: state of the boot chain

Status: **in progress. The read path is fully working. The flash contents are
proven intact, and `uboot_log` shows U-Boot DOES run (LCD init + backlight),
so the earlier "fault is below U-Boot" conclusion is superseded — see
[U-Boot does run](#correction-uboot-does-run-proven-from-uboot_log).**
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

Re-confirmed 18:16 against the node that had been sitting on the bus since
18:08: exactly ten `LIBUSB_ERROR_TIMEOUT` receives, then
`wrong command or wrong mode detected`. Nothing was sent to the phone and
nothing was written; the payload never left the host.

### The phone re-enumerates by itself

This is the useful part discovered on 18:16. The phone does not need to be
unplugged to produce a fresh BootROM: it repeatedly drops and re-adds the
`1782:4D00` node on its own.

```
18:16:35 REMOVE USB\VID_1782&PID_4D00\5&E7DA5E8&0&1
18:16:45 ADD    USB\VID_1782&PID_4D00\5&E7DA5E8&0&1
18:17:04 REMOVE USB\VID_1782&PID_4D00\5&E7DA5E8&0&1
```

Earlier cycles were seen at 17:54, 18:01, 18:06 and 18:08. Each `ADD` opens a
new reply window, so the host should fire *immediately* on the transition
instead of waiting for a manual unplug. `brom_read_spl.ps1` therefore has
`-MaxAttempts N`: it fires on each new enumeration, and if that window is
already dead (timeouts) it waits for the next one.

Whether a given `ADD` is a *responsive* BootROM is still unproven — the
18:16:45 window was only 19 s long and was never probed. The retry loop is
what settles it, because a live window answers `CHECK_BAUD` in under a
second.

## BREAKTHROUGH 18:19: the bypass works, FDL1 runs

An `ADD` at 18:18:00 was still answering at 18:19:18, and the full RAM
sequence ran. Transcript:

```
libusb_control_transfer ok
CMD_CONNECT bootrom
current exec_addr is 0x65015f08
SEND ...\fdl1-dl.bin to 0x65000800
SEND custom_exec_no_verify_65015f08.bin to 0x65015f08
EXEC FDL1
usb_recv failed : LIBUSB_ERROR_TIMEOUT
CHECK_BAUD FAIL
CHECK_BAUD FDL1
BSL_REP_VER: "Spreadtrum Boot Block version 1.1\0"
CMD_CONNECT FDL1
KEEP_CHARGE FDL1
usb_recv failed : LIBUSB_ERROR_PIPE
timeout reached
```

Consequences, in order of importance:

1. **The BootROM answers.** The board is not dead and the USB stack works.
2. **CVE-2022-38694 succeeds on this XT2227-1.** The payload at
   `0x65015f08` was sent and `EXEC FDL1` ran, after which the device came
   back as *FDL1* (`SPRD3` -> `Spreadtrum Boot Block version 1.1`). On
   unsigned/corrupt SPL this is the only way past the signature gate, and
   it worked.
3. `CHECK_BAUD FAIL` immediately after `EXEC FDL1` is normal — the same line
   appears in the upstream reference trace for a working device.
4. No `CHANGE_BAUD` line appears because that code is behind a non-libusb
   `#if` in `spd_dump`; the libusb build compiles it out. Not a fault.
5. The run then died in the **FDL2 bulk upload**, before `SEND fdl2-dl.bin`
   could be printed.

### Why the failure is in the FDL2 upload

From the tool source, `send_buf()` aborts with `ERR_EXIT("timeout reached")`
inside its chunk loop, and `send_file()` only prints `SEND <file> to 0x…`
*after* `send_buf()` returns. Since that line never appeared, the failure is
inside the FDL2 transfer itself, and `LIBUSB_ERROR_PIPE` means the device
stalled its IN endpoint there (a STALL, not a timeout).

The attempt had started 78 s into a window that had already produced one
`LIBUSB_ERROR_TIMEOUT`, so the most likely cause is an expired FDL1 session
rather than a bad address or a bad loader. The decisive test is the same
sequence fired on a *just-created* window, which is what `-MaxAttempts`
does.

### Consequence for the diagnosis

This retires hypothesis (a) "BootROM cannot init the UFS / dead hardware"
being the *only* remaining option, because the chip talks and executes
unverified code. It does not yet prove the UFS reads: that still needs FDL2
up and `p` / `r splloader`.

## Tool command-line parsing and `chip_uid`

The 17:06 fresh session answered CHECK_BAUD and CONNECT and then timed out
on `chip_uid`. That is expected: `chip_uid` is a legacy/debug command, not
the BootROM read API. Also, `sendcmdv` is a **runtime command**: it belongs
after the device connects, not in the initial command-line argument list.
Passing `sendcmdv ...` directly after `--wait` makes this `spd_dump` print
its usage and an interactive `BROM >` prompt; it does not execute those
reads. The earlier `0x07`/`0x2D` attempt therefore did not query the chip.

The correct BROM read commands are listed in `spd_cmd.h`:

| cmd | meaning | reply |
|---|---|---|
| `0x07` | READ_CHIP_TYPE | `0x94` |
| `0x0D` | READ_FLASH_INFO | `0x9B` |
| `0x2D` | READ_PARTITION | `0xBA` |
| `0x1A` | READ_CHIP_UID | `0xAB` |
| `0x19` | CHECK_ROOT | `0xA7` if rooted, else `0x80` |
| `0x35` | DUMP_UBOOT_LOG | `0xBB` |

The only read-only way supported by this `spd_dump` build to access the UFS
is to load an FDL1/FDL2 pair into RAM. A real-time report for the same
UMS9230-UFS family (XT2227-4, same RORS31.335-58-1 build) reports:

* `fdl1-dl.bin` SHA-256
  `153F3A33074D6EE9AE22EBD9580ADDCBBA6970B45C5D6A6E6D5B23723C259C15`;
  it reaches FDL1 on that phone.
* `fdl2-dl.bin` SHA-256
  `499F75FBC911CFFD8E44ED8E8F23F83C8090F677F79E3885FFD011FDCBA2F6BF`;
  it needs the documented patch at FDL2 file offset `0x7234` before the
  partition table works. This report also documented five NOPs at `0x812bc`.
* Its attached `fdl2-cboot.bin` is a separate persistent-unlock payload and
  is **not** part of recovery. It must not be loaded or written in this plan.

Those artifacts are staged under
`D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\`. The guarded offline
patcher verifies the known input bytes and writes a separate candidate
`candidate_fdl2_readonly.bin`. The read runner verifies all hashes, loads
only the CVE payload + FDL1-DL + FDL2-DL to RAM, then runs only `p` and
`r splloader`. It contains no write, erase, repartition, cboot or reset
operation. This is still untested on our XT2227-1, so treat it as a
controlled diagnostic, not a proven recovery.

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

## CORRECTION: U-Boot does run, proven from `uboot_log`

The `uboot_log` partition (4 MB) is a boot history, one session per 256 KB
slot. Read back at 18:27, it contains 16 sessions:

```
0x000000  U-Boot 2015.07-g0bc803f (Feb 20 2024)
0x040000  same
0x080000  same
...       same, through 0x2c0000
0x300000  uboot consume 2400ms, lcd init 1934ms, backlight on 3695ms   <- stops here
0x340000  uboot consume 2400ms, lcd init 1934ms, backlight on 3695ms   <- stops here
0x380000  U-Boot 2015.07 (Nov 11 2022)  = FDL download agent, dl_cmd_reboot()
0x3c0000  U-Boot 2015.07 (Nov 11 2022)  = FDL download agent, dl_cmd_reboot()
```

The four sessions at `0x200000`-`0x2c0000` go all the way through and print

```
enter mode normal, consume time: 5476ms, boot_reason: Reboot into normal
```

The two sessions at `0x300000` and `0x340000` stop immediately after

```
[sprdfb][set_backlight] ... brightness:25
uboot consume time:2400ms, lcd init consume:1934ms, backlight on time:3695ms
```

They never print `enter mode normal`. Those are the two custom-kernel
attempts: U-Boot started, parsed the panel devicetree, initialised the LCD,
turned the backlight on, and then stopped.

That kills the "zero logo means U-Boot never runs" inference. U-Boot runs,
reaches display init, and dies after it. The correct reading of the
symptom is: **the panel and backlight are initialised by U-Boot, so a dark
screen after that point is U-Boot failing later, not the SoC failing
before it.**

Note the two distinct U-Boot builds: `Feb 20 2024` is the device's real
U-Boot, `Nov 11 2022` is the download agent (FDL2) that logs into the same
partition, which is why two older-banner sessions appear at the end.

## What that means for the fix

`misc` differs from the pre-failure backup by exactly **6 bytes** — verified by
a full 1 MB comparison, not just the block:

```
0x80c  8e  (was 9e)   slot a: tries 1 -> 0
0x80e  0f  (was 9f)   slot b: tries 1 -> 0, successful_boot 1 -> 0
0x81c  dd be 17 46 (was cd 53 f1 45)   crc
```

Everything else in `misc`, including the BCB text `bootonce-bootloader` at
offset 0, is identical to the backup — so that text is not a change.

The live block still carries `slot_suffix = "_b"`. Slot `b` is the slot holding
the hung custom kernel and is now unbootable (`prio15 tries0 succ0`), while `a`
is bootable (`prio14 tries0 succ1`) and holds the proven rescue.

### The slot decision happens in the SPL, not in U-Boot

This is the part that took longest to see. The stock SPL binary
(`u-boot-spl-16k-ufs-sign.bin`, the same bytes in flash) contains the A/B
partition table and the `misc` partition name:

```
0x0e1e0  sml_a      0x0e1f0  sml_b
0x0e200  teecfg_a   0x0e210  teecfg_b
0x0e220  trustos_a  0x0e230  trustos_b
0x0e240  uboot_a    0x0e250  uboot_b
0x0e2d6  misc
```

So the SPL is what resolves slot suffix -> `uboot_X` / `sml_X` / `trustos_X` /
`teecfg_X` and jumps to U-Boot. A failure there happens **before** U-Boot
starts, which is exactly why `uboot_log` shows no new session even though the
phone keeps cycling (`uboot_log` re-read at 18:32 was byte-identical to the
18:27 copy).

That gives a coherent explanation of the whole timeline:

* While `b` was still bootable (`prio15 tries1 succ1`), the SPL loaded
  `uboot_b`, U-Boot ran, and the hung custom kernel produced the two log
  sessions that stop after `backlight on`.
* The first failed attempt consumed `b`'s retry and cleared its success flag.
  Now `b` is highest priority but *not* bootable, and because the suffix still
  says `_b`, the SPL has no usable U-Boot to load and falls back toward
  download mode. No U-Boot, no logo, no backlight.

`scripts/host/brom_set_slot.ps1 -Slot a -ConfirmWrite` forces
`slot_suffix = "_a"` with a fresh, CRC-valid block via the tool's own
`set_active` implementation:

* chosen slot: priority 15, tries 6, successful 0
* other slot : priority 14, tries 1, successful 0

Be aware what that command really does: `set_active` is implemented as a
read-modify-write of the **whole 1 MB `misc` partition** (dump to
`path`, patch 32 bytes at `+0x800`, write the partition back). `misc` is
scratch metadata, and the exact pre-write image is saved to
`readback_write\misc_before_setslot.bin`.

The write is low-risk in a specific, checkable way: `w_mem_to_part_offset`
writes sequentially from offset 0, so the 4 KB sector holding byte 0x800 is
written first; every later byte is identical to what is already in flash. The
runner also refuses to start unless the rollback dump matches the verified
live SHA-256 `DFC266B5…50E01`.

## Recovery ladder

1. **RAM-only FDL diagnostic.** Run `scripts/host/brom_read_spl.ps1`. It
   refuses to proceed unless the files match expected hashes, and it fires
   as soon as a fresh `1782:4D00` window appears (the phone re-enumerates on
   its own; see above). `-MaxAttempts N` retries across windows,
   `-AllowPresent` fires at whatever node is currently enumerated. It then
   executes only `p` and `r splloader`; inspect the saved SPL before
   considering any write.
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

- Can the matching FDL1-DL + patched FDL2-DL read this UFS on XT2227-1?
- Is the SPL partition still intact on flash, or was it damaged?
- Does the phone attempt a normal boot and stall silently (no USB) - i.e.
  is the SoC actually resetting on each Power press?
- What does `0x35 DUMP_UBOOT_LOG` return? If it returns bytes, U-Boot ran
  at some point; if empty, it never did.
