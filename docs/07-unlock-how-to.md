# 07 - Step-by-step: software-only bootloader unlock

This is the working procedure for the Moto E32 (`hawaii`, Unisoc T606,
Android 11, kernel 4.14.199) after the research in
`docs/06-secure-world-unlock-path.md`. Everything happens on-device: no
Motorola unlock code, no signed FDL, no BootROM exploit.

Result: `ro.boot.flash.locked=0`, `ro.boot.verifiedbootstate=orange`,
U-Boot prints `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!` on every boot,
and the state persists across reboots because the marker lives in `miscdata`.

## 0. Prerequisites

| what | where |
|---|---|
| runtime root exploit | `scripts/mali/mali_kroot.c` -> `artifacts/mali_kroot` |
| low-4GiB page pinner | `scripts/device/sip_page.c` -> `artifacts/sip_page` |
| SMC stub builder | `scripts/host/build_sip_ko.py` |
| module template | `artifacts/trace_runqlat_bytedancy.ko` |
| NDK clang (`aarch64-linux-android21`) | `D:\AndroidSDKTools\...` |

Build the two device binaries once:

```sh
NDK=D:/AndroidSDKTools/android-sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64/bin
$NDK/clang --target=aarch64-linux-android21 -O2 \
    -o artifacts/mali_kroot scripts/mali/mali_kroot.c
$NDK/clang --target=aarch64-linux-android21 -O2 \
    -o artifacts/sip_page scripts/device/sip_page.c
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
adb push artifacts/sip_page  /data/local/tmp/sip_page
adb shell 'chmod 755 /data/local/tmp/mali_kroot /data/local/tmp/sip_page'
```

> **Note (2026-10-31):** `/data/local/tmp` on the test device was cleaned up
> (2.67 GB -> 76 MB). The scratch files this procedure uses - `sip_page`,
> `sip31.ko`, `sipplain.bin`, `marker.bin`, `marker80.bin`, `signed.bin`,
> `verified.bin`, `siparena.bin`, `kroot.log` - are **not** on the device any
> more; they are pushed from the host `artifacts/` tree (or created by the
> steps themselves) exactly as shown. `artifacts/rescue/boot_rescue_restore.img`
> and `artifacts/mali_kroot` are the only copies that matter.

Two device facts shape the rest:

* **root is per-process.** Every `adb shell` is a fresh process, so each step
  re-runs `mali_kroot` first and then does its work in that same shell.
* **the SIP gateway truncates the buffer pointer to 32 bits**, so the scratch
  page must be a physical address below 4 GiB. `sip_page` applies memory
  pressure until the buddy allocator hands out a low page, `mlock`s it and
  prints `IDX`/`PA`.

## 1. Pin a scratch page below 4 GiB

```sh
adb shell 'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1;
  [ "$(id -u)" = 0 ] && break; done; echo uid=$(id -u);
  rm -f /data/local/tmp/siparena.bin /data/local/tmp/sippage.log;
  nohup /data/local/tmp/sip_page /data/local/tmp/siparena.bin \
      VerifiedBoot-UNLOCK > /data/local/tmp/sippage.log 2>&1 &'
sleep 30
adb shell 'tail -3 /data/local/tmp/sippage.log'
```

The log ends with

```
IDX=2290 CHUNK=0 VA=776d252000 PA=be7a1000 PRESENT=1 TEXT=VerifiedBoot-UNLOCK
VmLck:  65536 kB
```

Keep that process alive: it owns the page. Convert the PA to the kernel linear
alias, which is what the stub uses for cache maintenance:

```
va = 0xffffffc000000000 + (pa - 0x80000000)
```

(continued in the next section)

## 2. Mint the marker with SIP op `0x31`

The stub is grafted into a vendor `.ko` because the kernel has no build tree;
`build_sip_ko.py` patches the op, the physical address and the linear VA into
it, disables the template's relocations and renames the module so repeated
loads never collide.

```sh
python scripts/host/build_sip_ko.py \
    --out artifacts/sip31.ko --op 0x31 \
    --pa 0xbe7a1000 --va 0xffffffc03e7a1000 \
    --len 0x80 --name sip31 --dcache
adb push artifacts/sip31.ko /data/local/tmp/sip31.ko
```

Put the plaintext into the pinned page (the arena file *is* the page), load
the module, then read the page back:

```sh
adb shell 'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1;
  [ "$(id -u)" = 0 ] && break; done;
  dd if=/data/local/tmp/sipplain.bin of=/data/local/tmp/siparena.bin \
      bs=1 seek=$((2290*4096)) count=64 conv=notrunc 2>/dev/null;
  insmod /data/local/tmp/sip31.ko;
  dd if=/data/local/tmp/siparena.bin bs=4096 skip=2290 count=1 \
      of=/data/local/tmp/signed.bin 2>/dev/null;
  chmod 644 /data/local/tmp/signed.bin'
adb pull /data/local/tmp/signed.bin artifacts/signed.bin
```

Notes that matter:

* `--dcache` is **required**. Without it EL3 writes DRAM while Linux serves a
  stale dirty cache line, so the call "succeeds" and the buffer looks
  unchanged. The stub does `dc civac` + `dsb sy` before and after the SMC.
  `dc ivac` is not an option: it traps as an undefined instruction here.
* `--len 0x80` (or larger). `0x40` is refused by the mapper with `-14`.
* The first bytes of the page are the 64-byte marker; the stub's own return
  words sit at `+0x40`, so they overwrite part of the 0x80 output - that is
  fine, only the first 64 bytes are used.
* If the SMC returns `-14` (`ff ff ff f2` at `+0x40`), just load the module
  again under a different `--name`; the mapper refuses the first request and
  accepts the retry.

Expected marker (deterministic per device, from the chip-unique HUK key):

```
f5 53 44 ab 11 63 dd 2a 21 53 5f 77 db a1 7c 54
23 aa ad 81 5e dd be 88 42 fe e7 f2 f5 d0 71 76
9b b3 11 6f a0 7a 85 e4 66 9b 4c 56 a1 0f 5a 10
9b b3 11 6f a0 7a 85 e4 66 9b 4c 56 a1 0f 5a 10
```

## 3. Verify the marker the way U-Boot does

U-Boot copies 64 bytes into a 0x80 block and calls op `0x33` with len `0x80`;
TrustOS compares against its own encryption of `"VerifiedBoot-UNLOCK"` and
writes the verdict as a byte at `+0x40`. Move the stub's return words out of
the way with `--ret-off 0xF0` so that byte is observable.

```sh
python -c "open('artifacts/marker80.bin','wb').write(open('artifacts/marker.bin','rb').read()+bytes(64))"
python scripts/host/build_sip_ko.py --out artifacts/sip33.ko --op 0x33 \
    --pa 0xbe7a1000 --va 0xffffffc03e7a1000 --len 0x80 --name sip33 \
    --dcache --ret-off 0xF0
adb push artifacts/marker80.bin /data/local/tmp/marker80.bin
adb push artifacts/sip33.ko  /data/local/tmp/sip33.ko
```

```sh
adb shell 'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1;
  [ "$(id -u)" = 0 ] && break; done;
  dd if=/data/local/tmp/marker80.bin of=/data/local/tmp/siparena.bin \
      bs=1 seek=$((2290*4096)) count=128 conv=notrunc 2>/dev/null;
  insmod /data/local/tmp/sip33.ko;
  dd if=/data/local/tmp/siparena.bin bs=4096 skip=2290 count=1 \
      of=/data/local/tmp/verified.bin 2>/dev/null;
  chmod 644 /data/local/tmp/verified.bin'
adb pull /data/local/tmp/verified.bin artifacts/verified.bin
```

`verified.bin[0x40]` must be `1` and the return word at `+0xF0` must be `0`.
(`0x33` rewrites the first 16 bytes of the buffer while comparing, so re-write
the block before every trial.)

## 4. Write the marker to `miscdata`

Back up first, then write exactly 64 bytes at offset `0x2000`:

```sh
adb shell 'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1;
  [ "$(id -u)" = 0 ] && break; done;
  dd if=/dev/block/by-name/miscdata of=/data/local/tmp/miscdata.bak \
      bs=4096 count=64;
  dd if=/data/local/tmp/marker.bin of=/dev/block/by-name/miscdata \
      bs=1 seek=$((0x2000)) count=64 conv=notrunc;
  sync;
  dd if=/dev/block/by-name/miscdata of=/data/local/tmp/md.bin \
      bs=1 skip=$((0x2000)) count=64 2>/dev/null;
  chmod 644 /data/local/tmp/md.bin'
adb pull /data/local/tmp/md.bin artifacts/marker_readback.bin
```

Compare the read-back with `artifacts/marker.bin` - it must be identical.
The rest of the 512-byte block stays zero, which is how the device ships.

## 5. Wipe `/data` once and reboot

The existing `/data` was created under the old verified-boot state and cannot
be mounted afterwards, which shows up as a boot loop. Wipe it once (this is
the same thing a normal `fastboot oem unlock` does) - stock recovery needs no
signature:

1. Reboot into the bootloader (`adb reboot bootloader`, or Power + Vol Down).
2. Highlight **Recovery mode** with Volume Down, select with Power.
3. On the "No command" screen: hold **Power**, tap **Volume Up**, release.
4. **Wipe data/factory reset** -> confirm -> **Reboot system now**.

After the wipe the device reaches the setup wizard and stays unlocked.

## 6. Confirm

```sh
adb shell getprop ro.boot.flash.locked        # 0
adb shell getprop ro.boot.verifiedbootstate   # orange
```

and the boot log shows `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!`.
Reboot again and re-read `miscdata[0x2000]`: the marker is byte-identical, so
the state is permanent.

### The strongest check: boot a GSI

Properties can be argued about; a **foreign unsigned system image booting**
cannot. With the marker in place, an Android 15 GSI installs and boots on
this device (stock Motorola boot image and vendor stay in place - the GSI is
layered on as a userspace DSU):

```sh
# on the stock system, with USB debugging and the DSU-Sideloader app
# (https://github.com/VegaBobo/DSU-Sideloader) or the AOSP `gsi_tool`:
adb shell gsi_tool install --gsi-size 2g --userdata-size 4g gsi.img
adb shell gsi_tool enable            # sticky; omit for a single boot
adb reboot
adb shell getprop ro.build.fingerprint        # google/treble_arm64_bvS/...
adb shell getprop ro.boot.flash.locked        # 0
```

DSU itself refuses to work on a locked bootloader, so a GSI that boots is
an independent confirmation of the unlock. Details and the captured output:
[09-gsi-proof.md](09-gsi-proof.md).

## 7. One-command version

`scripts/host/unlock_marker.py` automates steps 1-4 (it re-roots for every
shell, retries the `-14` first-touch refusals, verifies with op `0x33` and
only then writes flash):

```sh
adb push artifacts/sip_page /data/local/tmp/sip_page
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
python scripts/host/unlock_marker.py            # dry run, leaves marker.bin
python scripts/host/unlock_marker.py --flash    # writes miscdata 0x2000
```

## 8. Rollback

Write 64 zero bytes back to `miscdata[0x2000]` (the device ships with that
block zeroed) and wipe `/data` again:

```sh
adb shell 'for i in 1 2 3; do /data/local/tmp/mali_kroot >/dev/null 2>&1;
  [ "$(id -u)" = 0 ] && break; done;
  dd if=/dev/zero of=/dev/block/by-name/miscdata bs=1 seek=$((0x2000)) \
      count=64 conv=notrunc; sync'
```

## 9. What this does *not* unlock

The marker only changes the **boot-time verified-boot policy**: U-Boot skips
AVB and reports the orange state. The fastboot download gate is separate and
still rejected unsigned requests when last probed, so flashing images from
fastboot kept failing with `Please verify the signature!`:

```
fastboot -w
  Erasing 'userdata' ... (bootloader) Please verify the signature!
  FAILED (remote: 'Please verify the signature!')
```

That probe predates the GSI test and has not been re-run since; treat the
fastboot download gate as **unverified after the unlock** rather than
proven-closed. What *is* proven is that the boot chain now accepts a system
image nobody signed - an Android 15 GSI boots (see
[09-gsi-proof.md](09-gsi-proof.md)).

Erasing/wiping from stock recovery works and is the recovery path if a
post-unlock boot ever loops again.

## 10. Notes on the GSI session

* The GSI is installed as a userspace DSU (`gsi_tool status` -> `[0] dsu`,
  `system_gsi` + `userdata_gsi`). The stock `system_b` partition stays in
  `super`, so a reboot returns to Android 11.
* `/metadata/gsi/dsu/one_shot_boot=1` means the GSI is single-boot. Use
  `gsi_tool enable` (sticky) before experimenting if you want reboots to
  stay in the GSI.
* A GSI is `userdebug`, so `adb root` works there and the Mali exploit is
  not needed. On the stock Motorola system `adb root` is refused and the
  runtime root from this repo is still the way in.
* The GSI's Quickstep launcher may crash (`MANAGE_ACTIVITY_TASKS` denial);
  that is an image defect, not an unlock problem. See
  [09-gsi-proof.md](09-gsi-proof.md).


