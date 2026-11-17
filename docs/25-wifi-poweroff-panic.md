# Wi-Fi power-off panic (2026-11-17): our in-tree sprdwl_ng had no SDIO teardown

Turning Wi-Fi off on the phone rebooted the kernel with
`kernel_panic,fatal_exception_in_interrupt` ~0.2 s after the module was
unloaded. The cause was ours, not the vendor's: the in-tree SC2355 port called
`sprd_iface_remove()` only for the PCIe variant, so the SDIO variant's
recovery watchdog survived the module and `__run_timers` wrote into freed
module memory.

Fixed in the kernel tree by commit `fd15bc439` ("net: wireless: sprd_wlan -
tear down the SDIO variant on remove", pushed to `origin/4.14`).
Evidence: `docs/evidence/2026-11-17-wifi-poweroff-panic.txt`.

## 1. Reproduce / observe

The phone boots with the Magisk-provided in-tree module
(`/data/adb/modules/sprd-wlan-combo/sprdwl_ng.ko`, "Ver. v1.0"); the vendor
HAL leaves it alone while `wlan.driver.status=ok`.

```
adb shell svc wifi disable      # or the Quick Settings tile
adb devices                     # device drops off, then comes back after reboot
adb shell getprop ro.boot.bootreason
  kernel_panic,fatal_exception_in_interrupt
```

The previous boot's panic is in `/sys/fs/pstore/console-ramoops-0`:

```
[ 7222.093118] wlan0: Power off WCN (1 time)
[ 7222.129907] WCN SDIO: sdiohal_remove remove card successful
[ 7222.130300] mmc2: card 8800 removed
[ 7222.184731] sprd-wlan: sprd_wlan_remove sprd,sc2355-wifi 2.
[ 7222.421539] Unable to handle kernel paging request at virtual address ffffff8001048458
[ 7222.421563] swapper pgtable: 4k pages, 39-bit VAs
[ 7222.421576] Internal error: Oops: 96000047 [#1] PREEMPT SMP
[ 7222.422075] Modules linked in: ... [last unloaded: sprdwl_ng]
[ 7222.422215] pc : run_timer_softirq+0x20c/0x718
[ 7222.422227] lr : run_timer_softirq+0x6c/0x718
[ 7222.426241] Call trace:
[ 7222.426257]  __do_softirq+0x16c/0x330
[ 7222.426274]  irq_exit+0xf0/0xfc
[ 7222.452027] Kernel panic - not syncing: Fatal exception in interrupt
```

`96000047` = data abort, write (`WnR=1`), translation fault level 3: a write
into an unmapped module-area page. `ffffff8001048458` is inside the
`MODULES_VADDR..MODULES_END` window of the 39-bit VA layout, i.e. a
module's freed memory, not RAM.

## 2. Root cause

The Wi-Fi off sequence is:

1. framework -> vendor `android.hardware.wifi@1.0-service` ->
   `DriverTool::UnloadDriver()` -> `delete_module("sprdwl_ng")`
   (the string `delete_module` is in `/vendor/lib64/libwifi-hal.so`);
2. module exit -> `platform_driver_unregister()` -> `sprd_wlan_remove()`;
3. meanwhile the HAL's earlier power-off had already powered WCN down, which
   removed the SDIO card (`sdiohal_remove`, `mmc2: card 8800 removed`).

`sprd_wlan_remove()` in `drivers/net/wireless/sprd_wlan/common/sprd_wlan.c`
had:

```c
if (p_match_data->hw_type == SPRD_HW_SC2355_PCIE)
        sprd_iface_remove(pdev);
```

The SDIO path was skipped, so `iface_wd_stop()` never ran. `iface_wd` is a
static `struct` holding a `delayed_work` that re-arms itself every second
(`iface_wd_tick`), with its timer living in the module's data. After the rmmod
freed the module, the next expiry had the timer wheel detach a timer whose
`timer_list` sat in the freed area -> write fault in `run_timer_softirq`,
fatal in interrupt.

This is exactly the MU300/PCIe bug documented in the existing comment
(issue #146): the fix was applied for PCIe only, and the SDIO variant this
phone uses was left out. Both variants are created by `sprd_iface_probe()`,
so both need `sprd_iface_remove()`.

## 3. Fix and test

```c
if (p_match_data->hw_type == SPRD_HW_SC2355_PCIE ||
    p_match_data->hw_type == SPRD_HW_SC2355_SDIO)
        sprd_iface_remove(pdev);
```

The first Wi-Fi off now tears the SDIO state down properly and the power
counts balance: remove powers WCN on (0 -> 1) so `iface_core_deinit()` can
close the interface, then powers it off (1 -> 0):

```
[   50.144083] sprd-wlan: sprd_wlan_remove sprd,sc2355-wifi 2.
[   50.144093] sprd-wlan: sprd_iface_remove\x0a wlan driver remove.
[   50.144105] sprd-wlan: Power on WCN (0 time)
[   50.165427] WCN SDIO: sdiohal_scan_card          <- the power-on re-probes the card
[   50.680506] sprd-wlan: Power off WCN (1 time)
[   50.724342] WCN SDIO: sdiohal_remove remove card successful
```

No panic; the device stayed up (`uptime` kept increasing). Wi-Fi on
afterwards loaded a driver and reconnected; `svc wifi disable`/`enable` was
repeated 3 more times with no reboot.

## 4. Note: after the first toggle the vendor module takes over

After the first Wi-Fi off unloads our module, the HAL's next
`wifi_load_driver` `finit_module`s `/mnt/vendor/socko/sprdwl_ng.ko`; with the
vendor-module-compat patches that module now loads too (the HAL logs
`wifi_load_driver success`). `/proc/modules` shows it by size 409600 vs the
in-tree port's 708608. Its own remove path is the vendor's and is safe -
the 4-cycle test above alternated both modules.

So the in-tree module (Magisk, boot) and the vendor module (after a toggle)
can coexist; the crash was only in our port's `.remove`.
