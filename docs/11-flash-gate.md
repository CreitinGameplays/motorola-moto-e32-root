# 11 - The fastboot flash/erase signature gate

Static analysis of the shipping bootloader (`hawaii-0bc803f`,
U-Boot `2015.07-g0bc803f`, `artifacts/bootloader/bl/uboot_b.img`).
Full annotated excerpts: [evidence/2026-10-30-flash-gate-decode.txt](evidence/2026-10-30-flash-gate-decode.txt).

## Why this matters

`fastboot flash boot_b` is the only remaining way to run the kernel we built,
and the bootloader refuses it - even for the phone's own byte-identical stock
images ([evidence/2026-10-30-flash-gate.txt](evidence/2026-10-30-flash-gate.txt)).
This document decodes the check that refuses it and answers whether it can be
opened from software.

## Address mapping

`uboot_b.img` starts with a 0x200-byte `DHTB` header, so

```
runtime VA  = 0x9efffe00 + file_offset
file_offset = runtime VA - 0x9f000000 + 0x200
```

Verified against the fastboot command registrar: `adrp x0,#0x9f0c3000 ;
add x0,x0,#0xb1f` == runtime `0x9f0c3b1f` == file `0xc3d1f` == `"flash:"`.
(Old notes in this repo quote file offsets as VAs; they are 0x200 high.)

## The gate

`gate(partname)` = runtime `0x9f08e280`, file `0x8e480`. Pseudo-code:

```c
int gate(char *partname) {
    if (efuse_query(2) == 0) {                 /* secure world says: no efuse */
        info("NON-efuse, Skip the signature!");
        return 1;                              /* ALLOW */
    }
    if (*(u8 *)0x9f70a001 == 0) {
        fail("Please verify the signature!");
        return 0;                              /* DENY  */
    }
    for (i = 0; i < 0x228 / 8; i++)
        if (!strncmp(whitelist[i], partname, strlen(whitelist[i])))
            return 1;                          /* ALLOW */
    info("Partition %s is not allow to flash/erase!!");
    return 0;                                  /* DENY  */
}
```

* `efuse_query` = runtime `0x9f08ee6c`, file `0x8f06c`. It issues SIP/SMC
  function `0xa` through the same trampoline as the `VerifiedBoot-*` calls in
  [06](06-secure-world-unlock-path.md) and returns
  `*(u32 *)0x9f70e000 != 1`. The mailbox is filled by the secure world; no
  U-Boot code writes it. On this phone it reports *secure*, which is why the
  first branch is never taken.
* `0x9f70a001` is a one-byte RAM flag in U-Boot's BSS ("fastboot session is
  licensed"). Zero at boot.
* The whitelist is a 69-entry table of partition-name pointers at runtime
  `0x9f0a15c0` (file `0xa17c0`). `boot_a`, `boot_b`, `vendor_boot_*`, `dtb_*`,
  `dtbo_*`, `vbmeta_*`, `super`, `misc`, `persist`, `uboot_*`, modem/NV
  partitions and `splloader` are all on it - so the name check is not the
  obstacle, the flag is.

Whitelist (69): `prodnv, miscdata, factory, misc, trustos_a, trustos_b, sml_a,
sml_b, uboot_a, uboot_b, uboot_log, logo, logo_lenovo, fbootlogo, l_fixnv1_a,
l_fixnv2_a, l_fixnv1_b, l_fixnv2_b, l_runtimenv2, gnssmodem_a, gnssmodem_b,
wcnmodem_a, wcnmodem_b, persist, l_modem_a, l_modem_b, l_deltanv_a,
l_deltanv_b, l_gdsp_a, l_gdsp_b, l_ldsp_a, l_ldsp_b, l_agdsp_a, l_agdsp_b,
pm_sys_a, pm_sys_b, teecfg_a, teecfg_b, boot_a, boot_b, vendor_boot_a,
vendor_boot_b, dtb_a, dtb_b, dtbo_a, dtbo_b, elabel, super, cache, socko_a,
socko_b, odmko_a, odmko_b, vbmeta_a, vbmeta_b, metadata, sysdumpdb,
vbmeta_system_a, vbmeta_system_b, vbmeta_vendor_a, vbmeta_vendor_b,
l_runtimenv1, vbmeta_system_ext_a, vbmeta_system_ext_b, vbmeta_product_a,
vbmeta_product_b, odm_res, userdata, splloader`.

## Both write commands go through it

| fastboot name | runtime handler | file | first thing it does |
|---|---|---|---|
| `flash:` | `0x9f0287c0` | `0x289c0` | `bl gate(partname)`; on 0 -> `Please verify the signature!` |
| `erase:` | `0x9f0276b4` | `0x278b4` | `bl gate(partname)`; on 0 -> `Please verify the signature!` |

`flash:` then re-asks the efuse state and, when secure, runs the write helper
`0x9f01d0a0` (which returns 1 on success, else `Secboot verify fail!`). So
there is a single gate call site per command and no second, ungated write path
in the fastboot command set. The `oem` subcommands are `get_identifier_token`,
`startup_core`, `unlock`/`lock`, `unlock_critical`/`lock_critical`,
`get_unlock_ability`, `get_unlock_bootloader_nonce`, `lock_bootloader`/
`unlock_bootloader`, `getsecurityversion`, `getversions`, `getlcs`, `setrma`,
`getsocid`, `frp-state`, `pull`, `dump`, `backupnv`, and the `upload_*` pair -
the `upload_*` ones are read-out paths (`get addr %llx size %llx`,
`upload partition fail.`), not writers.

## Can the flag be set?

Exhaustive scan of every instruction in the code region whose effective address
lands in `0x9f70a000`..: exactly two stores exist.

| store | runtime | function | notes |
|---|---|---|---|
| `strb w1,[0x9f70b000]` | `0x9f08dfb8` | file `0x8e080` | page B flag - never read anywhere |
| `strb w1,[0x9f70a001]` | `0x9f08e12c` | file `0x8e1d4` | the gate flag |

Both functions are the OEM password/licence handshake:

```
Start signature verify ...   ->  RSA/X.509 verify (0x9f08fbe8)
Signature verify successfully.
Start password verify ...    ->  strlen(password) == 10
Password verify successfully.
You can flash/erase partitions.
*(u8 *)0x9f70a001 = 1;
```

and **neither function is referenced anywhere in the image**: no `bl`, no `b`,
no absolute 64-bit handler pointer, no entry in the command table. They are
dead code in this build. The RSA verifier (`0x9f08fbe8`) is only called from
those two dead functions.

So there is no reachable code path that sets the flag, and no path that bypasses
the gate. The gate reduces to "is the chip efuse secure?", which the secure
world answers and which we cannot influence - the same secure world whose SIP
interface we already use for the unlock marker.

## What this means for our goal

1. `fastboot flash` of an unsigned (or even signed stock) image stays refused.
   The gate is content-independent and, being name-whitelisted, is not a
   signature check on the payload at all - it is a check that the *fastboot
   transport* is licensed.
2. Everything that can write flash is therefore: the bootloader's own flash
   command (gated), and a raw block write from a root shell (`dd`). The latter
   is not filtered by U-Boot.
3. The boot side does not re-check the image: U-Boot's boot-time verification
   returns early with `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!` when the
   lock state word (runtime `0x9f274810`) equals 2, which is exactly the state
   our `miscdata` unlock marker produces. So a `dd`-written unsigned boot image
   will be loaded and run.
4. The remaining risk is not verification, it is *recovery*: with `fastboot
   flash` closed there is no fastboot way back, and `adb reboot download` does
   not reach Unisoc download mode. The full 25-partition backup is the only
   road back if a raw write breaks boot - and it needs a booting Android to be
   useful.

## Next option this opens

Write the custom kernel to the **inactive slot** (`boot_a`) with `dd`, leaving
the stock `boot_b` untouched, and switch slots with `fastboot set_active a`
(a non-flash command, not gated). If the custom kernel fails, the fallback is
either the bootloader's A/B retry (U-Boot implements `ab_select_slot` /
`ab_slot_rollback`, strings at file `0xa41e0`/`0xa4230`) or a return to slot b.
This converts a one-way trip into a two-slot experiment, and is the only
remaining route to run [the built kernel](10-kernel-source.md).