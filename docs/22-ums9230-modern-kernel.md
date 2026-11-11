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

## First boot on the device (2026-11-04)

The fork was cloned to the VPS (`~/linux-ums9230`, branch `hawaii-test`),
the 4.14 v5 on-panel indicator ported (`include/linux/diag_stage.h`,
`head.S` pre-MMU bar in the new `primary_entry`/PI layout, `setup.c` and
`main.c` hooks; `dcache_clean_inval_poc()` replaces `__flush_dcache_area`),
config = postmarketOS ums9230 config (`KVM=y`, MUSB/gadget, PANFROST=m),
toolchain Debian clang/lld 19.

* **Attempt 1** (`boot_71_test.img`, minimal mainline 4h10 DTB) died in
  the **bootloader** (< 1 s power-off, BROM recovery). Three causes,
  all ours: the `--dtb` override had stripped the 64-byte Unisoc
  pre-header (magic `0xd7b7ab1e`) that `dtb_size` includes; the Image
  header said `text_offset=0x0` (stock is `0x80000`, and RAM base hosts
  `ddrbist-mem`); and the 175 KiB vendor DTB was replaced wholesale.
  `pack_and_sign_boot.py` now keeps the pre-header for `--dtb`
  (`wrap_sprd_dtb()`) and gained `--text-offset`.
* **Attempt 2** (`boot_71_test2.img`: stock DTB + stock ramdisk
  byte-identical, only the kernel payload swapped, `text_offset=0x80000`)
  **booted the 7.1 kernel** - the bar appeared and moved. Boot then hung
  at the logo with no adb (expected: stock Android ramdisk, no vendor
  modules - the same terminal state as the mali-less 4.14 images).
  Evidence was lost: the recovery was a cold power cycle, wiping the
  ramoops DRAM; the vendor kernel's pstore only holds the previous
  *warm-reset* boot's log.
  Two more facts: the stock DT reserves only `0xab00` (43 KB) of the
  3.4 MB logo scanout buffer, so the allocator corrupts the bar
  mid-boot ("renders quite poorly"); and this SoC's USB is **MUSB**
  (`usb@64900000` "sprd,qogirl6-musb" + hsphy "sprd,qogirl6-phy"),
  not dwc3 - mainline `musb/sprd.c` matches only "sprd,musb", so USB
  needs a one-line compatible addition (milestone 2).
* **Attempt 3** (`boot_71_test3.img`, kernel-only): reserve the scanout
  buffer (`memblock_reserve(0x9e000000, 4 MiB)`), and a **boot watchdog**
  (`hawaii.selfreset=`, default 150 s, 0 = off; PSCI warm reset via
  `emergency_restart()`, 4.14 commit 0dbefb998's pattern) so a hung test
  boot self-recovers: ramoops survives, the slot fallback boots the stock
  image, and the next boot's pstore holds the 7.1 kernel's log.

## Plan change: console-first bring-up (2026-11-04, after tests 4-5)

Tests 4 and 5 both booted the kernel fully (12-segment bar in the full-white
shade = do_basic_setup complete) but produced **no working console channel**:
no USB gadget ever enumerated (capture_ttygs.py saw nothing on 0525:a4a7),
the PSCI boot watchdog fired without resetting the board (this firmware
ignores PSCI SYSTEM_RESET), and the AON-watchdog self-reset built for test 5
did not fire either (user waited > 3 min).  The panel status grid (test 5)
was unreadable: the bar itself rendered with artifacts and the squares never
appeared - CONFIG_DRM_SPRD=y binding the vendor DPU node mid-boot is the
prime suspect for fighting the bootloader scanout.  Every iteration cost a
BROM session.  Conclusion: stop panel-based debugging; get a real console
first (user decision).

### Research results

* **codeberg ums9230-mainline/linux issue #20 "USB bring up"** (the fork we
  build): USB works on UMS9230 phones (Realme C35 needed only
  `&hsphy/&usb { status = "okay"; }` + `dr_mode = "peripheral"`, which the
  vendor DTB effectively already provides).  The maintainer's warning:
  *"the USB driver is still partially broken... worked only for a short
  time or didn't work at all when booted from download mode... **If an FDL
  runs before the kernel, it seems to mess up USB***"* and *"USB is
  probably the easiest as long as the kernel gets to initialize it
  first."*  **Every one of our 7.1 test boots so far was a warm reboot
  chain that started from a BROM/FDL recovery session** - the stock kernel
  tolerates that state (vendor musb/usbpinmux drivers fully re-init),
  mainline does not.
* **Unisoc pad mux (`usbpinmux`)**: the USB-C D+/D- pads double as the
  factory UART/JTAG interface.  The vendor driver
  (drivers/soc/sprd/usbpinmux/sprd_usbpinmux.c on 4.14) reads the
  "usb_uart_jtag_mux" field - syscon aon_apb@0x64000000 offset **0x374,
  mask 0x0f** - and when it is non-zero (mux open, e.g. set by the BootROM
  in download mode) enables the vddusb33 regulator and routes UARTs onto
  the pads via pinctrl states `uart_inf_sel0/1`
  (QOGIRL6_UART_INF9_SYS_SEL=1, QOGIRL6_UART_INF1_SYS_SEL=8; the fork's
  serial driver has earlycon support for the vendor "sprd,sc9836-uart"
  nodes, serial1 = 0x200b0000).  This is a hardware console channel that
  needs no working USB stack - rejected for now (user has no USB-UART
  adapter), but it is the documented fallback.
* The fork's ums9230 clock/gate tables match the vendor DTB indices
  exactly (OTG gate 0x18 = CLK_OTG_UTMI_EB; wdt gates 0x38/0x42 =
  CLK_APCPU_WDG_EB/CLK_AC_WDG_RTC_EB), and sprd_clk_regmap_init supports
  the vendor's sprd,syscon phandle style - nothing statically wrong with
  the clock chain.

### Test 6 (boot_71_test6.img): the cold-boot experiment

DRM_SPRD off (stop touching the display pipeline), SERIAL_SPRD_CONSOLE=y
(inert while the pads are muxed to USB, ready for the UART route).
Everything else as test 5 (status hooks, AON watchdog, g_serial CDC-ACM
console with console=ttyGS0).  New procedure via
`run_boot_b_test.ps1 -ColdBoot`: flash boot_b, arm one attempt, then
**power the phone OFF** instead of rebooting; the user presses POWER so
the 7.1 kernel is the first thing after a full power cycle (no BROM/FDL
state, no warm reboot chain).  Outcomes:
- USB gadget enumerates on the cold boot -> CDC-ACM console attaches on
  the PC, full kernel log streams -> the mystery is over;
- still nothing -> the FDL-state theory is dead; next step is the
  hardware UART route (needs a USB-UART adapter) or configfs/adbd.

## Plan change 2: kexec + the mainline DT (2026-11-05, after tests 6-8)

Test 6 (cold boot) produced no USB either, so the FDL-state theory is dead.
Tests 7 and 8 attacked the self-recovery instead (4.14-exact AON watchdog
arm, then the vendor SC2730 PMIC soft reset via a new `sprd-adi` restart
handler): neither produced a reset, and each cost another BROM recovery.
The bootloader's own log (`/dev/block/by-name/uboot_log`) then showed why:
it prints `Watch Dog Trace: WDG_TimerStop` before every kernel handoff, and
the stock bootargs carry `androidboot.wdten=0`.  The "+1 min auto reboot"
we remembered from 4.14 is an AP-side kthread
(`CONFIG_SPRD_NATIVE_HANG_MONITOR`) that panics, and the panic only resets
because the *vendor* kernel registers the ADI handler.  Full write-up:
`docs/evidence/2026-11-05-uboot-log-and-new-approach.txt`.

Two conclusions:

1. **The vendor DTB was the wrong input all along.**  It describes the
   hardware with vendor bindings (`sprd,ufshc`, `sprd,qogirl6-musb`,
   `sprd,qogirl6-phy`), while mainline drivers match
   `sprd,ums9230-ufs`, `sprd,musb`, `sprd,ums9230-hsphy`.  So on every test
   the UFS host never probed (**no block device at all**, a prime suspect
   for the init hang) and the USB glue never got its phy.  The fork already
   ships `ums9230.dtsi` + a working `ums9230-reeder-s19mps` board; our
   `ums9230-4h10.dts` (UFS/uart/ramoops/logobuffer, real memory map) is the
   board to use, and it is built at
   `arch/arm64/boot/dts/sprd/ums9230-4h10.dtb`.
2. **kexec removes the flash/BROM cost and the DTB is now a userspace
   parameter.**  The proven 4.14 on slot `_b` loads the 7.1 `Image` plus any
   DTB and jumps: the slot is never touched, a hang costs a power cycle,
   and DT experiments (USB, phy, pinmux, ramoops) need no reflash either.

Log channel: `pstore` registers its own console
(`CON_PRINTBUFFER|CON_ENABLED|CON_ANYTIME`) as soon as `ramoops` probes, so
every printk lands in the 256 KiB DRAM zone at 0xfff80000, and the next
boot shows the dead kernel's log in `/sys/fs/pstore/console-ramoops-0`
(verified: a vendor log survived our BROM recoveries).  No UART and no USB
needed.

Workflow:

```bash
# once: 4.14 with CONFIG_KEXEC=y (build.sh) flashed to boot_b
python scripts/host/build_kexec.sh          # static aarch64 kexec
adb push kexec-build/kexec /data/local/tmp/kexec

# every test: load + jump into 7.1 with the mainline board DT
python scripts/host/kexec_test.py \
    --image <Image 7.1> --dtb <ums9230-4h10.dtb> --execute

# the test kernel resets itself (see below), so no power cycle is needed:
python scripts/host/kexec_test.py --collect docs/evidence/<date>-pstore.txt
```

### Measured limitation: pstore needs a *warm* reset

A full power-off wipes DRAM on this board, so the ramoops log is gone
after "hold POWER" (measured 2026-11-05: a `PSTORE-SURVIVAL-MARKER` written
before the power cycle was gone afterwards, while the backend probed
normally on the new boot).  The vendor log seen earlier survived only
because the boot after it was a warm reboot.

So the test kernel must reset itself, and the reset must not cut DRAM
power.  The vendor's SC2730 PMIC soft reset over ADI is exactly that (the
bootloader log's `rst_mode 0x80` / `(c)-(kernel_crash)` boots prove it).
Our 7.1 port of it (test 8) never fired because the mainline DT binds
`adi@64200000` to `"sprd,ums512-adi"`, whose driver data has **no restart
callback**.  The board DTS now overrides it:

    &adi_bus {
        compatible = "sprd,qogirl6-adi", "sprd,ums9230-adi";
    };

and `init/main.c`'s boot watchdog (`hawaii.selfreset=<s>`) now uses a
deadline that is bumped at the start of the initcalls and again just
before `/init` is exec'd, then calls `do_kernel_restart(NULL)` when the
boot stops making progress.  A hung 7.1 boot therefore ends in a warm
reset, the bootloader starts the untouched 4.14 on `boot_b`, and that
boot's `/sys/fs/pstore/console-ramoops-0` holds the 7.1 log.

Next steps from here: get the 7.1 log via kexec, then work the list it
reveals (UFS bind, USB glue + hsphy, then init).  DT variants are free now,
so USB (`&usb`/`&hsphy` okay + `dr_mode = "peripheral"`) can be tried
directly in the mainline DT instead of shimming vendor nodes.

## 2026-11-05 (2): the kexec handoff is boot-age dependent

Tests 9-13.  Evidence: `docs/evidence/2026-11-05-kexec-*.txt`; deep
research and mechanism analysis: `docs/22-kexec-hang-research.md`.

- The known-good 4.14 self-test combo boots via kexec from a 96 s-old
  boot but hangs from a ~13 min idle boot (test 13, panic-knob
  instrumented: no panic -> the loading kernel's shutdown and the PSCI
  CPU_OFF of all 7 secondaries completed; the target dies right after
  entry).  **The 7.1 image is exonerated** - tests 11/12 failed on launch
  conditions, not on their content.
- PSCI SYSTEM_RESET (SMC) from a kexec'd kernel entry is fatal (tests
  9/10); the AON WDT with RST_EN never resets the SoC; the PMIC watchdog
  is a wdten-gated SIPC string to a coprocessor - none of them can rescue
  a hung test kernel.  The `hawaii.selfreset` watchdog only helps if the
  7.1 kernel boots far enough to bump its deadline, so it never fired in
  tests 11/12 (the target died at entry, exactly like test 13).
- Self-recovery that needs no hardware reset: the kexecback initramfs
  (`scripts/host/kexecback.c` -> `71_testramfs.cpio.gz`) kexeces the
  phone back into the working 4.14 when the test kernel reaches `/init`.
  A target that dies at entry never gets that far - the handoff itself
  must be fixed first.
- Workaround under test (test 14): offline CPUs 1-7 from userspace
  before `kexec -e` (`scripts/host/kexec_jump_offline.sh`;
  `CONFIG_HOTPLUG_CPU=y`) - the standard normalization for this kexec
  bug class (powerpc "orphaned offline CPUs", LKML arm64 kexec threads;
  see docs/22).  If even `maxcpus=1` targets hang, abandon kexec
  iteration in favor of the community's flash-based loop + simplefb
  earlycon (Jolla C2 method) or the ums9230-mainline U-Boot chain.
- Workflow update: never jump with a bare `kexec -e` - use
  `scripts/host/kexec_jump_offline.sh` (panic instrumentation + CPU
  offlining + jump) after `kexec_test.py` has loaded the image.
- Segment placement measured with the debug kexec-tools build
  (`kexec -d -l`): all segments land bottom-up in the first memory bank,
  far below the ramoops ring at 0xfff80000 - kexec loads do NOT
  endanger the ring, and no DTB carve-out is needed.  The empty pstore
  after the successful self-test jump needs a different explanation;
  collect pstore right after the next successful jump to decide it.



## 2026-11-11: the 7.1 tree is published as branch "7.1"

The 7.1-rc1 bring-up tree (VPS `~/linux-ums9230`, upstream base
`codeberg.org/ums9230-mainline/linux` branch `ums9230`) is now published
as the **`7.1` branch** of
<https://github.com/CreitinGameplays/motorola-moto-e32-kernel> (the
vendor 4.14 daily-driver tree stays on the `4.14` branch of the same
repository).

What the branch carries:

* all 18 hawaii commits: display bring-up (sprd DRM/DPU/DSI/panel/DPHY),
  USB gadget + phy power, the UFS host port, the panel-log console and
  the boot-watchdog policy, plus the `dm-default-key` port.
* `arch/arm64/configs/hawaii71_defconfig` (canonical savedefconfig of
  the tested configuration) and `arch/arm64/configs/hawaii71.config`
  (the full `.config` for byte-exact reproduction).
* `H71-README.md` - what the tree is, how to build it, what works
  (display end to end, USB gadget with live serial shell, UFS), what
  does not yet (Novatek touch over SPI, PMIC EIC gpio-keys, the
  metadata-encrypted /data behind a keymaster-wrapped key, the
  parked-boot hang) and where the flash harness and the full journal
  live.

Build (VPS):

```sh
make O=$HOME/l71out ARCH=arm64 LLVM=1 -j$(nproc) Image
```

### Publishing caveat: the published history is rooted at a synthetic commit

The local clone of the upstream snapshot is **shallow** (`.git/shallow`
at the upstream commit `4a5b97b8`), and GitHub's receive-pack does not
accept shallow pushes - a first attempt failed with
`remote: fatal: did not receive expected object b9d32493...`, i.e. the
missing parent of the shallow boundary.  The published branch therefore
starts with a **synthetic root commit** carrying the upstream tree of
`4a5b97b8` (upstream history deliberately not mirrored - it stays
available at codeberg), followed by the 18 hawaii commits replayed on
top.  The tree content is byte-identical to the working branch.

### .gitignore review

The tree had **no untracked and no ignored files** (everything is
tracked, the biggest tracked file is 23 MB - under GitHub's 100 MB
per-file limit), and the builds happen out-of-tree in `~/l71out`, so
nothing stale or cache-like was published.  The appended local section
covers what the hawaii workflow could drop into the tree (in-tree
`.config`, `out/`, `build/`, `l71out/`, patch/diff/editor leftovers).
It deliberately does **not** repeat upstream's `tags`/`TAGS`/`cscope`
rules: upstream pairs `tags` with a `!tags/` re-include for tracked
directories of that name, and duplicating the plain `tags` rule made
`tools/testing/selftests/arm64/tags/` appear ignored (verified with
`git ls-files -i -c --exclude-standard`: back to the single
pre-existing upstream case, `Documentation/.renames.txt`).
