# 21 - Modern-kernel research: how new can the Moto E32 go? (6.x / 7.x)

Date: 2026-11-04. Research only - nothing built or flashed yet.

## TL;DR

| question | answer |
|---|---|
| Absolute ceiling on this device? | None that matters. The boot chain (SPL/U-Boot loads a raw relocatable arm64 `Image` per the boot-img header + passes DTB) is version-agnostic, and the boot interfaces are all stable: **PSCI 0.2** (confirmed in the live DT), **GIC-v3**, arm64 Image protocol. Mainline **7.3.1 stable / 7.4-rc1** would boot in principle once the SoC software is in place. |
| **Proven max on this exact SoC** | **Linux 7.x**. The community fork `codeberg.org/ums9230-mainline/linux` (branch `ums9230`) is a **7.1-rc1** base (May 2026); postmarketOS packages it as **7.2.0-rc6** (Aug 2026) and it is **daily-driven on the Jolla C2 - a Unisoc UMS9230 / T606 phone**, i.e. the same SoC as this device (FOSDEM 2026 talk, Jan 2026). |
| Best official base | Unisoc's own `github.com/sprd-linux/ums9230-mainline-linux` (branch `ums9230`): **6.19-rc2** base with full SoC support, last updated Dec 2025. |
| What mainline (kernel.org) has today | No UMS9230 DTS (sprd DTS list stops at UMS9620), but **panfrost already supports the Mali-G57** (`GPU_MODEL(g57, 0x9001)` in mainline 7.3), and the sprd serial/PMIC blocks are upstream. The community fork is exactly this delta, maintained. |

## Evidence trail

* kernel.org (2026-11-04): mainline **7.4-rc1** (2026-11-01), stable **7.3.1**,
  longterm 6.18.60 / 6.12.115 / 6.6.161.
* `sprd-linux/ums9230-mainline-linux`, branch `ums9230`:
  `VERSION=6 PATCHLEVEL=19 SUBLEVEL=0 EXTRAVERSION=-rc2`, tip
  2025-12-28. Contains:
  * `arch/arm64/boot/dts/sprd/ums9230.dtsi` - a **full SoC dtsi**:
    PSCI 0.2, GIC-v3 @ 0x10000000, UARTs at 0x200a0000..,
    `gpu@23100000` with `compatible = "sprd,ums9230-mali", "arm,mali-valhall-jm"`
    (the **panfrost** binding; the node address matches this phone's
    `23100000.gpu` devfreq exactly),
    `dpu@31000000` + `dsi@31100000` (mainline-style display pipeline).
  * board file `ums9230-reeder-s19mps.dts` - the Reeder S19 Max Pro S,
    i.e. the **Jolla C2** hardware (same SoC, different board than ours).
  * drivers: `drivers/gpu/drm/sprd` (DPU/DSI), `drivers/net/wireless/unisoc`
    (SC2355 family), `drivers/tty/serial/sprd_serial.c` - and **no
    `drivers/gpu/arm` vendor blob**: the GPU is meant to run on panfrost.
* `codeberg.org/ums9230-mainline/linux`, branch `ums9230`:
  `VERSION=7 PATCHLEVEL=1 SUBLEVEL=0 EXTRAVERSION=-rc1`; recent commits are
  "WIP: arm64: dts: sprd: add device tree for UMS9230 SoC / SC2730 PMIC /
  Reeder S19 Max Pro S". Panfrost in the fork is stock mainline (no
  Unisoc GPU-ID quirk), i.e. the T606's G57 uses a standard ID.
* postmarketOS: package `linux-postmarketos-unisoc-ums9230`
  (**7.2.0_rc6_git20260807-r0** at the time of capture), wiki page
  `Jolla_C2_(jolla-c2)`.
* FOSDEM 2026 (2026-01-31), "Running mainline Linux on the Unisoc-based
  Jolla C2" (Affe Null): Jolla C2 = Reeder S19 Max Pro S rebadge,
  UMS9230 (T606/T7200); the speaker **daily-drives** the mainline port;
  "some things are still not working" (video + slides linked from the
  event page).
* Device side (read-only checks on this phone):
  * `/proc/device-tree/psci/compatible` = `arm,psci-0.2`
  * `chosen/bootargs`: `console=null` - **no serial console at all**
    (UART is unwired), which is why our on-panel indicator matters for
    any new kernel; `lcd_base=0x9e000000`, `lcd_name=lcd_nt36525c_boe_mipi_fhd`
  * `reserved-memory` carries `logobuffer@9e000000` (our indicator
    target), `ramoops@fff80000`, `tos-mem`, `sml-mem`, `sipc-mem`, ...
    all the nodes a modern kernel's ramoops/logging needs.
  * PMIC: `androidboot.pmic.chipid=2730` = SC2730 - the fork has an
    upstreaming WIP for exactly this PMIC.

## What a 6.19 / 7.x tree gives us for free

* CPU clusters (4x A75 + 4x A55, DynamIQ) - supported since forever.
* PSCI SMP/suspend, GIC-v3, arch timers - stock arm64.
* **KVM** - mainline arm64 KVM on A75/A55 + GIC-v3 is standard
  (this device already runs KVM on our 4.14, so EL2 is reachable).
* **GPU: panfrost** for the Mali-G57 - no vendor kbase blob, no
  20-million-line DDK, mainline devfreq/thermal integration.
* Display: `drm/sprd` DPU+DSI host drivers (mainline-style).
* WiFi: `drivers/net/wireless/unisoc` (SC2355; firmware can be taken
  from the stock vendor image like we did on 4.14).
* PMIC (SC2730): MFD/RTC/charger/ADC support upstreaming in the fork.

## What we would have to do (per base choice)

1. **Community fork (codeberg, 7.1/7.2-rc, tracks mainline)** - the
   "max version" path, proven on the SoC by the Jolla C2:
   * port our board: `ums9230-4h10` board DTS (from the 4.14 vendor
     tree's `ums9230-4h10-overlay.dts`) onto the fork's SoC/PMIC dtsi;
   * panel driver for the **Novatek NT36525C** (720x1600, MIPI-DSI;
     mainline has other Novatek `panel-novatek-*` drivers as templates,
     and the 4.14 tree has the vendor panel code);
   * touchscreen, sensors (ltr569 light), NFC-less - board-level work,
     same as the Jolla C2 port had;
   * port our **on-panel boot indicator** (the v5 portrait/2160 bar) for
     hang diagnosis - the fork gives us no console either;
   * ramoops works via the existing reserved-memory node.
2. **Unisoc 6.19 (sprd-linux)** - the "official vendor style" path:
   same board/port work, plus rebasing their 6.19-rc2 SoC delta if we
   want to move forward from 6.19 (6.19 is not a longterm; 6.18.60 is).
3. **Pure mainline 7.3/7.4** - cherrypick the fork's sprd patches;
   cleanest, most work, same result as (1) minus the fork's lag.

## Known gaps (all three paths)

* **Modem** (SIPC/marlin, calls + data): hardest part of every Unisoc
  port; the Jolla C2 port lists it as incomplete too. WiFi first.
* **Audio codec** path, camera, video codecs - WIP upstream, board work.
* **Android 11 userspace on 7.x**: binder/binderfs is mainline, but the
  prebuilt vendor modules (camera/BT/FM/GPU blobs) are built for 4.14
  ABI and will never load on 7.x. A modern-kernel daily driver means a
  Linux userland (postmarketOS/Sailfish style) or a GKI-style Android
  rebuild - the 4.14 custom kernel remains the Android vehicle.
* Panel/touch quirks of OUR exact LCD (nt36525c) are not in any tree;
  the 4.14 vendor driver is the reference.

## Recommended experiment order (when we start)

1. Clone the codeberg fork; build `Image` with the Reeder board DTS
   (closest working board) - boot into our boot-img container with the
   stock ramdisk replaced by a tiny initramfs, indicator ported,
   `boot_a` rescue + slot-b one-attempt as always.
2. First milestone: indicator reaches "do_basic_setup" + ramoops
   readable back on the 4.14 boot - proves 7.x boots at all on our unit.
3. Then port the 4h10 board DTS + panel, aiming for panfrost on our G57
   and DSI panel output (a real console/UI without the boot logo trick).
4. Keep the 4.14 kernel as the Android boot; the 7.x kernel is the
   experimentation vehicle (KVM, modern features, mainline GPU).

## References

* https://codeberg.org/ums9230-mainline/linux (community fork, 7.1-rc1+)
* https://github.com/sprd-linux/ums9230-mainline-linux (Unisoc 6.19-rc2)
* https://fosdem.org/2026/schedule/event/9KYVGM-jolla-c2/ (talk, slides,
  video; Jolla C2 = UMS9230)
* https://wiki.postmarketos.org/wiki/Jolla_C2_(jolla-c2)
* https://forum.sailfishos.org/t/mainline-linux-kernel-for-the-jolla-c2/21382
* https://www.kernel.org/ (7.4-rc1 mainline, 7.3.1 stable at capture time)
* device DT evidence: `docs/10-kernel-source.md` and the checks above
