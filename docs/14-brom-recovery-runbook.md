# 14 - BootROM recovery runbook (phone does not boot, no logo)

One page, copy-paste. Use this if the XT2227-1 stops booting after a bad
kernel/image and shows no logo, no backlight and no USB beyond `1782:4D00`.

Full analysis and reasoning: [13](13-recovery-bootrom.md).
Raw transcripts: [evidence/2026-10-30-brom-recovery.txt](evidence/2026-10-30-brom-recovery.txt).

Proven once, 2026-10-30: reset to Android in ~74 s, stock `boot_b` restored.

## 0. Preconditions

| Thing | Value |
|---|---|
| Phone connected | enumerates as `USB\VID_1782&PID_4D00` in Windows |
| Phone keys | Power + Vol Down, then cable in (only needed if it stops cycling by itself) |
| Firmware dir | `D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\withcboot\` |
| Tool | `D:\AndroidSDKTools\spd\spd_dump_LibUSB_Release\spd_dump.exe` |
| Backups | `D:\AndroidSDKTools\backups\hawaii-2026-10-30\backup\` |

The scripts verify these hashes themselves and abort on mismatch, so never
edit the payloads in place.

```
custom_exec_no_verify_65015f08.bin  32D8B796FF484C168D7FC63D9ED75D056D0833B55C7D65FBDAF2C548474F3C62
fdl1-dl.bin                         153F3A33074D6EE9AE22EBD9580ADDCBBA6970B45C5D6A6E6D5B23723C259C15
fdl2-dl.bin                         499F75FBC911CFFD8E44ED8E8F23F83C8090F677F79E3885FFD011FDCBA2F6BF
candidate_fdl2_readonly.bin         06ED520CB4B273782649B1481BC3860DB790BFFAC1594A6DC8180882A61D29C2
```

`fdl2-cboot.bin` must never be used: it is a persistent-unlock payload, not
a recovery tool.

## 1. Do not panic, do not reflash the bootloader

Two facts make most "fixes" unnecessary:

* The phone re-enumerates as BootROM **by itself** every 1–5 minutes. No
  unplug is needed; a node that has been sitting on the bus for minutes is
  dead and will only time out.
* The boot chain images (`splloader`, `uboot_a/b`, `sml_a/b`, `miscdata`)
  do not get damaged by a bad kernel. Only `misc` (A/B metadata) changes.

So the failure is almost always "no bootable slot", which is a 32-byte fix.

## 2. Fix: force slot `a`

```powershell
cd C:\Users\Creitin\moto-root-test
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\host\brom_set_slot.ps1 -Slot a -ConfirmWrite `
  -WaitMinutes 45 -MaxAttempts 20
```

What it does:

1. hash-checks the payloads, and requires the rollback dump
   `readback\misc.bin` to match `DFC266B5…50E01`;
2. fires on the next fresh `1782:4D00` window;
3. `exec_addr 0x65015f08` → `fdl1` → `fdl2` → `exec`
   (CVE-2022-38694 signature bypass, all in RAM);
4. `set_active a` — dump `misc`, patch 32 B at `+0x800`, write back;
5. `r misc` (read-back verification), then `reset`.

Expected output — this is a success, not an error:

```
FDL2: incompatible partition        (known, the patch lets it continue)
Write Part Done: misc, target: 0x100000, written: 0x100000
slot_suffix '_a'   slot a prio=15 tries=6 succ=0   slot b prio=14 tries=1 succ=0
crc verdict : VALID
boot order: a, b
```

Then: Android appears in ~60–90 s, on slot `_b`, with the stock kernel. The
`boot_a` rescue is doing its job — it rewrites `boot_b` from an embedded
stock image and reboots.

## 3. Verify

```powershell
& 'D:\AndroidSDKTools\adb\adb.exe' devices
& 'D:\AndroidSDKTools\adb\adb.exe' shell "uname -a; getprop ro.boot.slot_suffix; getprop ro.boot.verifiedbootstate"
```

Good state:

```
ZF523X9NXW  device
Linux 4.14.199+-ab612c2 #1 SMP PREEMPT Tue Feb 20 11:32:22 CST 2024 aarch64
_b
orange
```

Confirm the A/B block is the healthy steady state (root via
`/data/local/tmp/mali_kroot`, then `dd from /dev/block/by-name/misc`):

```
slot_suffix '_b'  slot a 0x008e (prio14 tries0 succ1)  slot b 0x00ef (prio15 tries6 succ1)
crc 0x49b9de16 -> VALID
```

## 4. After recovery: root still works, resume

The rescue writes a **stock** `boot_b`, so the Magisk patch and any custom
kernel are gone. That is the expected, safe outcome.

Runtime root is unaffected: `/data/local/tmp/mali_kroot` still elevates the
shell to `uid=0` on the stock kernel (confirmed after this recovery —
`id` shows `uid=0(root)`, SELinux `Permissive`, marker
`ROOTPROOF_0_Permissive`). That is enough to `dd` a new `boot_b`.

1. Confirm the stock boot is healthy (no re-root needed).
2. Resume the KVM kernel work in [12](12-slot-b-testing-channel.md).
3. Before flashing a new kernel to `boot_b`, keep the previous image on the
   device (`/data/local/tmp/boot_b.prev.img` was already there) so a bad
   build can be replaced without another BootROM session.

## 5. If step 2 does not boot

Run the read-only diagnostic instead of guessing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\host\brom_read_spl.ps1 -Parts "misc,uboot_a,uboot_b,sml_a,sml_b" `
  -MaxAttempts 20
python scripts\host\misc_ab.py D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\readback\misc.bin
```

* A/B block decodes VALID but still no boot → look at `uboot_log`
  (`python scripts\host\scan_bootlogs.py <file> --grep "enter mode"`).
  A new U-Boot session means the SPL is fine and the failing image is the
  kernel/boot.
* No new `uboot_log` session at all → the SPL is not getting to U-Boot.
  Confirm the images are byte-identical to the backups (they were here), then
  treat it as hardware (power/PMIC) and charge undisturbed for 2–3 h.

## 6. Rollback

`D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\readback_write\misc_before_setslot.bin`
is the exact pre-write image (SHA-256
`DFC266B5DD8975DEB176247B3A35189C2AA16209BBFE57386D2EF88941250E01`). The
phone now carries a different, proven-good block, so rollback is only needed
if you deliberately want the old counters back.

Note: writing the **pristine stock** `misc.img` back is not a fix — stock
marks slot `b` as successful at higher priority, i.e. it boots the broken
kernel again.