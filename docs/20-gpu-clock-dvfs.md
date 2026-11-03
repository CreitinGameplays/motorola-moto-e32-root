# 20 - GPU clock: the 600 / 650 / 850 MHz question (Mali-G57 on T606)

State of the facts, gathered 2026-11-03 (no code changed yet). All file
references are the kernel tree (`~/kernel-sprd`, branch `hawaii-diag`).

## 1. What the device tree actually offers

The GPU node (`/soc/mm/gpu@23100000`, `compatible = "sprd,mali-natt"`) in
the boot image's DTB (recovered from the untouched `boot_b.img`, extracted
with `bootimg.py unpack` + `scripts/host/find_ikconfig.py`-style parsing of
the *dtb.bin*, which is an Android DT_TABLE, magic `0xd7b7ab1e`; entry 0 is
a plain FDT) carries a full 5-level DVFS table:

```
operating-points  = <384000 700000  512000 750000  614400 750000
                     768000 800000  850000 800000>   /* Hz / uV */
sprd,dvfs-lists   = <384000 700000 4 1  512000 750000 5 1  614400 750000 6 1
                     768000 800000 7 1  850000 800000 8 1>
sprd,dvfs-default = <0>
sprd,dvfs-scene-low/medium/high/extreme = <0 1 2 3>
sprd,dvfs-range-min/max = <0 4>
```

So the board tree offers **384 / 512 / 614.4 / 768 / 850 MHz** at
700 / 750 / 750 / 800 / 800 mV.  The two top levels (768, 850) run at the
same 800 mV.  There is also a `gpu-cooling0` power model and a
`gpu-thmzone` thermal zone, i.e. the thermal side is already wired for the
higher levels.

## 2. Why the shipping kernel says 650 MHz and ours says 600 MHz

Two completely independent mechanisms produce the two numbers:

1. **The per-SoC PLL trim (real frequency limit).**
   `drivers/gpu/arm/midgard/platform/qogirl6/mali_kbase_config_qogirl6.c`:

   ```c
   #define T606_GPLL_FREQ      650000000
   #define T616_GPLL_FREQ      750000000
   #define GPU_768M_FREQ       768000000
   #define GPU_850M_FREQ       850000000
   ...
   /* GPLL max frequency for T606/T612 is 650 MHz */
   gpu_dvfs_ctx.freq_list[len-1].freq = T606_GPLL_FREQ / FREQ_KHZ;
   /* drop the 768 MHz entry, keep 650 MHz in its place */
   memcpy(&freq_list[len-2], &freq_list[len-1], ...); len--;
   ```

   The trim is keyed on the efuse string from `/hwfeature/auto` in the
   runtime DT (T606/T612 -> 650 MHz, T616 -> 750 MHz, anything else keeps
   the DTS levels).  This is product segmentation on the same silicon
   family: the official Unisoc numbers are Mali-G57 MP1 @ 650 MHz (T606,
   T612), 750 MHz (T616), 850 MHz (T615/T620).  Our kernel runs this path:
   the probe log shows `clock_on: efuse=T606` and then
   `clk_set_rate(GPLL source, 650 MHz)`, so the runtime top level is
   already 650 MHz on the custom kernel, same as stock.

2. **The reported maximum (a compile-time constant).**
   `drivers/gpu/arm/midgard/platform/qogirl6/mali_kbase_config_platform.h`
   from the OSS drop:

   ```c
   #define GPU_FREQ_KHZ_MAX 600000   /* kHz, reported via KBASE gpuprops */
   #define GPU_FREQ_KHZ_MIN 256000
   ```

   `mali_kbase_gpuprops.c` exposes this verbatim through the
   `KBASE_GPUPROP_GPU_FREQ_KHZ_MAX` ioctl, which is what GPU-info apps
   read.  That is the "600 MHz" the modified kernel reports.  It is *not*
   the clock the GPU runs at - it is a stale/conservative constant in the
   published source.  The vendor's internal build (the module in
   `/mnt/vendor/socko/mali_kbase.ko`) reports 650 on the stock kernel, so
   their tree has `650000` here.

## 3. Options

* **(a) Align the reported max (safe, matches stock).**  Change
  `GPU_FREQ_KHZ_MAX` to `650000` in `mali_kbase_config_platform.h`.  Purely
  cosmetic - the runtime PLL trim already sets 650 MHz.
* **(b) Prove the runtime clock.**  Nothing currently re-checks the
  frequency after boot.  Verify with debugfs (`mount -t debugfs none
  /sys/kernel/debug` then `/sys/kernel/debug/clk/clk_summary | grep gpu`)
  or by adding a one-line probe log.  The glue's freq list after the trim
  is 384 / 512 / 614.4 / 650 MHz with 700/750/750/800 mV.
* **(c) Experimental: go past the T606 trim (768 or 850 MHz).**  Skip the
  trim (or read `nvmem "gpu_bin"` and act on it) so the DTS levels stay:
  768 and 850 MHz at 800 mV - the same silicon as T615/T620.  Risks:
  - the T606 bin may not be qualified for 850 MHz (that is exactly what the
    efuse segmentation is for); the DVFS voltage is the same 800 mV as
    768 MHz, so the extra margin is entirely frequency;
  - the E32 is a sealed budget phone: `gpu-thmzone` throttling must be
    verified before trusting sustained 850 MHz;
  - the GPLL divider chain is driven by `sprd,ums9230-gpu-clk`
    (`drivers/clk/sprd/ums9230-clk.c`) + mm-clk dividers; a wrong level can
    hang the GPU (recoverable, but a reboot is needed).
  Suggested test order: align to 650 first, verify with a GPU benchmark
  (e.g. 3DMark/GFXBench loop), then optionally try the 768 MHz level with
  the thermal zone active, 850 only if 768 is stable.
* **(d) Real DVFS.**  This r28p0 DDK core has no DVFS-table hook ("fixed
  board default, the r28p0 core has no DVFS table hook" in the glue), so
  the frequency is set once at `mali_clock_on` and never scales.  Wiring
  the glue's `freq_list` into a devfreq device (like the vendor module's
  `devfreq` stats) is a bigger project - only worth it if (c) pans out.

## 3b. Runtime confirmation (2026-11-03, compat kernel boot)

The in-tree mali probe logs the DDK's DVFS hook at boot:

    GPU_DVFS kbase_platform_modify_target_freq gpu_boost_level:0
    min_freq=384000 max_freq=650000 target_freq=384000000

So the runtime DVFS max is already 650 MHz (the T606 trim is applied) -
option (b) is confirmed by the boot log; only the *reported* constant
(a) remains to be changed.

## 3c. Experiment results (2026-11-03): both untrim attempts crash the board

Two independent attempts to lift the trim both hung the boot and needed
BROM recovery - details in
`docs/evidence/2026-11-03-gpu-untrim-attempts.txt`:

1. renaming the `/hwfeature/auto` efuse string (kernel early fixup) hangs
   the boot before post-fs-data (an unrelated early consumer keys on the
   same string);
2. loading our glue with the untrimmed 5-level table
   (`mali_kbase.untrim_gpll=1`) kills the board at probe.

So on this board 650 MHz is the qualified maximum with the current glue
path; the 768/850 MHz levels are not reachable without a different
approach (candidate: 768-only, post-boot, voltage maps kept - needs an
explicit go before trying; two BROM recoveries were needed today).

## 3d. Final results (2026-11-03 evening): the trim is enforced in HARDWARE

The "768-only, post-boot" candidate was executed three ways on the
running vendor driver (no boot-path changes, instant revert, sampler
logging; evidence: `docs/evidence/2026-11-03-gpu-untrim-attempts.txt`
section "Post-boot experiments"):

1. **GPLL re-rate to 768** (clk framework `clk_set_rate` on the 650
   source, plus a `PRE_RATE_CHANGE` notifier that vetoes the vendor
   power-on re-clamp): the rate was granted and held, but DevCheck got
   GPU 115 (pre-clamp run) and then GPU 69/71 with compute collapsed
   to 5.63 GFLOPS FP32 (baseline 8.23) - the GPU gets *slower*, not
   faster, when its GPLL parent is pushed out of the fused envelope.
2. **Runtime untrim** (`modules/gpu-dvfs-untrim/`): patches the
   running vendor module's `gpu_dvfs_ctx.freq_list[3]` back to the true
   DTS 768 entry (`dvfs_index` 4 -> 3, clk_src -> the fixed twpll-768M
   source) and re-enables the 768 MHz OPP.  This works perfectly on
   the software side - `available_frequencies` shows
   384/512/614.4/650/768, the governor targets 768 under load,
   `INDEX_CFG` reads 3, all through the vendor's own
   `kbase_platform_set_freq_volt()` path.  Benchmarks: GPU 69/71,
   Scene Render 3.06 -> 1.78 fps, FP32 8.23 -> 4.62 GFLOPS
   (`benchmarks/gpu/overclocked_768mhz_*/`).  Everything dropped
   ~42 % = **650 -> 384 MHz**: the hardware CGM drives the fixed
   twpll-768M source at half rate for DVFS index 3 on this fused
   grade.
3. **Register archaeology** (poker `rd`/`wr` attrs; MMIO reads on the
   GPU-gated DVFS APB only succeed while the GPU is clocked - several
   panic reboots proved the 50 ms idle gate is real):
   - `CGM_CFG_DBG` (0x23014034) at the 650 level: CORE_SEL=5,
     CORE_DIV=0, MEM_DIV=0, SYS_DIV=3; `INDEX_CFG`=4; voltage
     index 1 (800 mV).
   - the unnamed 0x68..0x88 gap of the DVFS APB is all zeros - the
     per-index clock table is not driver-visible there.
   - the topdvfs controller (`syscon@64014000`, always-on, safe to
     read; `scripts/device/gpu_dvfs_read.sh`) holds the fused rail
     tables: 0xe8 = `0x00020110` (bits 17+8+4) vs 0xf0 =
     `0x00020100` - bit 4 is the T606 voltage grade, exactly the
     value (272/0x110, mask 0x1FF) the vendor's
     `kbase_platform_limit_max_freq()` writes at probe for
     non-T616 binning-2 silicon (disassembly of
     `/mnt/vendor/socko/mali_kbase.ko`, md5 f2181570...).

**Verdict: 650 MHz is the hardware ceiling of this unit.** The 768/850
DTS levels exist because the same BSP ships on higher-graded
T615/T616/T620 parts; on the T606 the fused grade limits the 768
source to half rate and the GPLL trim to 650. No safe software path
around that exists - rewriting the fused grade registers would run
the PMIC rail outside the qualified envelope and is out of scope.

Kernel state: the `untrim_gpll` module parameter stays in the tree
(default 0 = stock trim, `dd6d10c79f5b` published 2026-11-03); the
default-ON experiment edit was reverted.

## 4. Recommendation

1. Do (a) + (b) in the next kernel build (one-line header change + a
   debugfs read) - the custom kernel then matches the stock kernel's
   reported 650 MHz.
2. Treat (c) as CLOSED: 650 MHz is the qualified maximum, now proven
   at the hardware level (section 3d).  Do not flash GPU-overclock
   test images on this unit.
