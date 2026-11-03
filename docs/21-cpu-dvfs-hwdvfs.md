# 21 - CPU DVFS on the T606 (sprd-hwdvfs): architecture, register map, and the 1612 -> 1820 MHz question

Status: research complete (2026-11-03 evening), OC experiment ready but NOT
yet executed.  All register values in this document were read live from the
device (`scripts/device/cpu_dvfs_dump.sh`, poker module `base` 2/3/4) and
verified against the vendor disassembly / DT / driver source.

## 1. Cluster and clock topology

The UMS9230 (qogirl6/T606) CPU complex:

| cluster | cores | cpufreq node | live OPP table (kHz) | DCDC rail | MPLL |
|---|---|---|---|---|---|
| lit (A55) | cpu0-5 (6) | `cpufreq-clus0` | 614400 768000 884000 1040000 1228800 1378000 1536000 1612000 | DCDC_CPU0 | MPLL0 "ananke" (0x645a0000+0xa8) |
| big (A75) | cpu6-7 (2) | `cpufreq-clus1` | 768000 1040000 1228800 1404000 1536000 1612000 | DCDC_CPU1 | MPLL1 "prometheus" (0x64580000+0x78) |

MPLL2 "scu" (0x645a0000+0xec) clocks the SCU/interconnect.  The mpll
"slot" registers hold ICP (bits 0-2), postdiv flag (bit 3) and the PLL
N-divider (bits 4-14, 11 bits) - CPU frequency = N x 26 MHz:

| slot | ananke (lit) N -> MHz | prometheus (big) N -> MHz |
|---|---|---|
| 0 | 34 -> 884 | 40 -> 1040 |
| 1 | 40 -> 1040 | 54 -> 1404 |
| 2 | 53 -> 1378 | 62 -> **1612** |
| 3 | 62 -> **1612** | 65 -> 1690 |
| 4 | 66 -> 1716 | 70 -> **1820** |
| 5 | 70 -> **1820** | 73 -> 1898 |
| 6 | 75 -> 1950 | 75 -> 1950 |
| 7 | 77 -> 2002 | 77 -> 2002 |

**All slots are programmed at boot by `sprd_mpll_table_init()` from the
static table in `drivers/cpufreq/sprd-hwdvfs-archdata.c`
(`ums9230_mpll_index_tbl`)** - the 1.82 GHz (N=70) entries exist in the
hardware right now; the T606 map tables simply never select them.
Verified live: prometheus slot 4 = `0x64580000+0x88 = 0x00000464` (N=0x46=70).

## 2. The sprd-hwdvfs autonomous DVFS engine

CPU DVFS is NOT clk-framework based.  `drivers/cpufreq/sprd-hwdvfs-normal.c`
programs register tables into the always-on apcpu DVFS block
(0x64018000) at probe, and a hardware FSM performs every transition
(voltage first via the topdvfs/PMIC path, then mpll + CGM mux/div):

```
0x64018000 (apcpu dvfs, AON - safe to read/write any time)
  0x30-0x50   per-sub-device live state: sel/div/volt per cpu/ace/scu/gic
  0x60-0x88   lit cluster map table, 11 rows (row 0 = 26 MHz XTL)
  0xa0-0xc4   big cluster map table, 10 rows
  0x214       lit cluster work index (4 bits, written by the governor)
  0x218       lit cluster idle index
  0x224       big cluster work index
  0x228       big cluster idle index
```

The per-row map register packs 7 DT columns (lit: `column-entry-start-bit
= <0 2 15 5 9 18 12>`, masks `<3 7 7 f 7 7 7>`; big: bits <0 2 15 5 9 21 12>):

| column | bits | live-decoded meaning |
|---|---|---|
| c0 | 0-1 | source class (2/3 = mpll path rows) |
| c1 | 2-4 | (sub-dev config / interconnect sel) |
| c2 | 15-17 | **voltage grade** (index into the per-rail fused grade table) |
| c3 | 5-8 | DCDC transition parameter (opaque; verbatim per variant) |
| c4 | 9-11 | (sub-dev config) |
| c5 | 18-20 | tuning (DT says 5; big-cluster rows show 0 live) |
| c6 | 12-14 | **MPLL slot index** |

The live big rows carry extra bits 21/23 beyond the DT packing (SPL/FSM
runtime state) - any row rewrite must preserve them.

Verified: the packing math reproduces the LIVE lit-cluster registers
byte-exact from `lit-core-dvfs-tbl-T606-2` (all 11 rows MATCH), and the
big-cluster registers from `big-core-dvfs-tbl-T606-2` modulo the extra
bits 18-23.  **This phone is binning 2 (T606-2).**

The voltage grades (topdvfs 0x64014000, per-rail, 9-bit fields,
3.125 mV/step, sc2730 PMIC):

| grade | DCDC_CPU0 (lit, 0xf4-0xfc) | DCDC_CPU1 (big, 0x100-0x108) |
|---|---|---|
| 0 | 700 mV | 750 mV |
| 1 | ~ (TBD) | 800 mV |
| 2 | ~ (TBD) | 850 mV |
| 3 | ~ (TBD) | 900 mV  <- big 1612 MHz runs here |
| 4 | ~ (TBD) | **950 mV** <- big 1820 MHz target |
| 5 | ~ (TBD) | 1000 mV |
| 7 | 1000 mV | 1000 mV |

## 3. Why the T606 stops at 1612 MHz: product/binning table selection

The DTS ships one map table per product AND per binning
(`sprd,multi-version`, nvmem `dvfs_bin`):
`big-core-dvfs-tbl-{T606,T606-1..4,T612,T612-1..4,T616,...}[-65]`.
The driver picks one at probe
(`sprd_cpudvfs_index_tbl_update()` + `dvfs_map_tbl_init()`) and writes
it into the registers above.

Key rows of the shipped variants (this device = T606-2):

| variant | top row (c0..c6) | meaning |
|---|---|---|
| T606-2 (live) | [3, 0, 3, 8, 4, 5, 2] | 1612 MHz (prometheus s2), grade 3 (0.90 V) |
| T612-2 r6 | [3, 0, 3, 8, 4, 5, 3] | 1690 MHz (prometheus s3), grade 3 |
| T612-2 r7/8/9 | [3, 0, 4, 10, 4, 5, 4] | **1820 MHz (prometheus s4), grade 4 (0.95 V)** |
| T616-2 r7/8/9 | [3, 0, 6, 10, 4, 5, 6] | 1950 MHz (prometheus s6), grade 6 |

Same die family, same BSP, same register format: the T612/T616 phones
ship with rows the T606 never uses.  The DT `cpufreq-clus1` OPP tables
confirm the pairing (`operating-points-T612-2` tops at 1820000 kHz @
0.97 V).

The cpufreq layer mirrors the selected table:
`scaling_available_frequencies` (cpu6) = 768/1040/1228.8/1404/1536/1612.
Governor -> `sprd_cpudvfs_set_target(opp_idx)` -> work index =
`opp_idx + 1` (row 0 is the 26 MHz XTL entry).  Max OPP (idx 5) -> work
index 6.  **Rows 7/8/9 exist in hardware but no cpufreq OPP maps to
them** - the governor can never reach them, and a manual
`echo N > /sys/devices/system/cpu/cpufreq/cpudvfs/cpu6/target`
(`set_dvfs_work_index`, the driver's own FSM handshake) can.

The driver also exposes live state per sub-device
(`/sys/devices/system/cpu/cpufreq/cpudvfs/<dev>/{sel,div,voted_volt,target}`)
and per-DCDC state machines (`dcdc/DCDC_CPU{0,1}/{apcpu,top}_dvfs_state`).

## 4. The OC plan (runtime-only, zero persistence risk)

Everything below is register writes into AON blocks + the driver's own
sysfs.  The DT/`map_tbl_init` rewrites all of it at every boot - a
reboot fully reverts, no boot path is touched.

### Phase 1 - big cluster (A75, cpu6-7): 1612 -> 1820 MHz

1. Write the OC row into big map rows 7/8/9 (0xbc/0xc0/0xc4):
   derived from the LIVE top row 0x00a1a903, changing only
   c2: 3->4 (grade 4 = 0.95 V), c3: 8->10 (the T612 transition param),
   c6: 2->4 (prometheus slot 2 -> 4 = 1820 MHz), preserving live bits
   21/23 and c5=0:  **0x00A24943**.
   (T612-2's DT row packs to 0x00164943; the live-derived value keeps
   the runtime bits - identical in every DT-defined field.)
2. `echo 7 > /sys/devices/system/cpu/cpufreq/cpudvfs/cpu6/target`
   -> FSM raises DCDC_CPU1 to grade 4, switches prometheus to slot 4.
3. Verify: `cpu6/target/sel/div/voted_volt`, a timed busy loop pinned
   to cpu6 (taskset), thermal zones.
4. Revert: `echo 6 > cpu6/target`, restore 0x00A1A903 to 0xbc/0xc0/0xc4.

### Phase 2 - lit cluster (A55, cpu0-5): 1612 -> 1820 MHz

T612-2 lit rows (the live lit registers match the DT byte-exact, so
the DT packed values are used directly):
- r9 (0x84) = 0x00174923 (T612-2's intermediate 1716 MHz level, ananke s4)
- r10 (0x88) = **0x0017D943** (1820 MHz, ananke s5 = N=70, grade 7)

`echo 10 > .../cpu0/target` -> A55s @ 1.82 GHz (T612 ships exactly this).
Revert: `echo 8 > cpu0/target`, restore 0x0016B903 to 0x84/0x88.

### Risks

* Binning: T606-2 silicon at 1.82 GHz @ 0.95 V is NOT qualified by
  Unisoc for this SKU (the T612 bin is).  Worst case = crash/hang ->
  panic reboot restores everything (the GPU experiments today survived
  8 such reboots; boot_b/Magisk are unaffected).
* The governor may re-target the work index (performance governor holds
  its max OPP = work 6/8); watch `target` and re-echo if it drifts.
* Thermal: the driver's 65 C temp threshold and the thermal zones stay
  active; watch the CPU thermal zone during sustained load.
* The DCDC transition protocol is executed by the vendor FSM with
  vendor-shipped row values - no custom voltages or timings are invented.

## 5. Tooling

* `modules/gpu-gpll-poker/` `base` 0-5 + `rd`/`wr`/`dump`: raw register
  access (0 = GPU DVFS APB - the only power-gated, fault-prone one;
  1 = topdvfs 0x64014000, 2 = apcpu dvfs 0x64018000,
  3 = glbregs 0x645a0000 [ananke], 4 = glbregs 0x64580000 [prometheus],
  5 = aon-apb 0x64000000 [module enables]).  Bases 1-5 are AON, safe
  any time.  Also `mon` (us-resolution FSM transition capture) and
  `clkwalk` (kernel clock tree walk) - see section 7a.
* `scripts/device/cpu_dvfs_dump.sh`: full CPU DVFS state dump.
* `scripts/device/cpu_oc_test.sh`: the phase-1 experiment (bench, write,
  flip, bench, revert) with results in /data/local/tmp/cpu_oc.log.
* `scripts/device/cpu_freq_probe.c`: freestanding aarch64 frequency
  probe (raw syscalls, CLOCK_MONOTONIC, 400M dependent adds, ~1.3 s at
  1.6 GHz) - build with the VPS clang
  (`--target=aarch64-linux-gnu -ffreestanding -nostdlib -static -O2
  -Wl,-e,_start`; add `-DITERS_M=20` for the 20M-iteration calibration
  variant), pin with `taskset <decimal-mask>` (toybox has no
  -c and rejects 0x masks; cpu6 = mask 64, cpu0 = mask 1).  Note: its
  ms print underflows (prints 18446744074xxx) when the run crosses a
  second boundary - just re-run for a clean sample.

## 6. EXPERIMENT RESULTS (2026-11-03): the frequency is fused-capped

All experiments ran with vendor-shipped T612-2 field values, the
driver's own cpudvfs sysfs handshake, and reverted cleanly (reboot also
fully reverts).  Measurements via the pinned cpu_freq_probe:

| test | work index | voltage grade readback | probe (ms) |
|---|---|---|---|
| big (A75) stock | 6 | 3 | 1334, 1334 |
| big, T612-2 row verbatim (c2=4, c3=10, c6=4) | 7 | **4 (applied!)** | 1334, 1334 |
| big, c3=8 + c6=4 (T606 trans code, 1820 slot) | 7 | 3 | 1334, 1334 |
| lit (A55) stock | 8 | 5 | 1245, 1244 |
| lit, T612-2 r10 verbatim (c2=7, c3=10, c6=5) | 10 | **7 (applied!)** | 1245, 1245 |

Every combination: **the map rows ARE honored** (the voltage grades
change exactly as the rows request), but the **CPU clock never changes**
- the probes are identical to stock in all cases, the live PLL
registers (0x64580000+0x54 etc.) never move, and the mpll slot
registers are never selected.  The CGM sel toggles transiently
(3 -> 0 -> 3) during the switch attempts - the FSM tries, then
restores the old clock while keeping the requested voltage.

### Verdict

The T606's CPU frequency ceiling (1612 MHz on both clusters) is
enforced inside the fused DVFS engine, the same mechanism family that
caps the GPU at 650 MHz (docs/20 section 3d): the DTS/T612 map-table
rows, the mpll slot ladders (1716/1820/2002 MHz entries all programmed
at boot) and the voltage grades are common BSP content, but the
fused per-product tables the FSM actually consults for the frequency
top out at the product grade.  Software cannot lift it - the T606 is
the binned-down SKU of the qogirl6 die (T612/T616 = the full-fat
parts).

CPU overclock: CLOSED.  Stock state fully verified after revert
(work indexes 6/8, stock map rows, probes back to 1334/1245 ms).

### The strongest proof: the hardware's own native rows (2026-11-03)

A full dump of the apcpu DVFS block (0x64018000, 0x1000 bytes; only
0x000-0x2fc is nonzero) revealed five extra map rows the driver never
initialises (the DT lit table stops at 0x88): registers 0x8c-0x9c =
lit work-index rows 12-16, all pre-loaded by the SPL/hardware with
`[c0=3, c2=7, c3=9, c4=5, c5=5, c6=4]` = **grade 7 (1.0 V) + ananke
slot 4 = 1716 MHz** - the hardware's own above-stock config, in its
own registers.

- The driver's sysfs `target` rejects index 12 outright (bounds check
  at the DT row count - the target attr bounced back to 8).
- Writing the work-index REGISTER directly (`0x214 = 12`) bypasses
  that: the FSM accepted it (target read 12) and **applied the row's
  voltage grade 7** - but the probe stayed at 1249/1247 ms, identical
  to the 1612 MHz stock baseline (1716 would read ~1170 ms).

So even the hardware's own native higher row, driven through the
hardware's own index register, gets its voltage honoured and its
frequency ignored.  The frequency gate is fused; nothing upstream of
it matters.

### Online research (2026-11-03): no public T606 OC exists

* XDA "Overclocking unisoc t606" (2024): the question exists, no
  answers; userspace OC apps can only touch governors (matches our
  findings).  The "2 GHz / 750 MHz GPU" variant the asker saw is the
  T616 - the same die family with the full fuse grade.
* The most rigorous public Unisoc OC work is TheGammaSqueeze's
  UnisocBypass `oc/` research (RG Vita, UMS512/T618 - a friendlier
  die): CPU OC 2002->2100 MHz via DTB worked at the DVFS level but
  delivered **zero sustained throughput** (thermal budget); GPU OC
  850->900 MHz delivered **+1.57 %** real throughput; **DT voltage
  requests above the fused ceiling are silently ignored by the
  hardware DVFS path** (their voltage-ceiling-hunt).  Their honest
  recommendation: stock, or stock CPU + GPU OC for stability only.
* No public T616/T612/UMS9230 DVFS OC exists; the ums9230-mainline
  u-boot/linux projects do not touch DVFS.

Our UMS9230 results are one wall further in than the UMS512 story:
on qogirl6 the FREQUENCY itself is fused-capped (not just the
voltage), which is why even the UMS512-style DTB/OPP edits are
futile here - proven with the hardware's own rows (above).

## 7. Direct inspection of the blocker (2026-11-03, late session)

Full evidence file: `docs/evidence/2026-11-03-cpu-fsm-inspection.txt`.
This session mapped the transition machinery itself and drove every
remaining register surface, to locate the clamp at the hardware level.

### 7a. Tools built for the inspection

* poker module extensions (`modules/gpu-gpll-poker/`):
  - `mon` - us-resolution change-detecting sampler over the work
    index, per-cpu sel/volt regs, relock enables and BOTH mpll shadow
    regs; writes a work index as the trigger (or triggerless).
  - `clkwalk`/`clkaddr` - resolves `__clk_lookup`/`__clk_get_name` by
    address from kallsyms (neither is exported) and prints any
    clock's full parent chain with the kernel-computed rates.
  - base 5: the aon-apb glbregs at 0x64000000 (module enables).
* `scripts/device/cpu_freq_probe.c` gained a 20M-iteration build
  variant (`-DITERS_M=20`, binary `cpu_freq_probe20`) for
  low-frequency runs; the 400M default binary is unchanged so all
  prior measurements stay comparable.
* `scripts/device/calibrate.sh` - absolute frequency calibration via
  the XTL row; `live_probe.sh` - live mpll regs under load;
  `slot_rewrite_lit.sh`/`slot_test2.sh` - the slot-rewrite attack;
  `fsm_reinit_test.sh` - the module_eb toggle (crashed; see 7e).

### 7b. The claimed table is physically real (calibration)

Pinning the lit cluster on the XTL row (target 0, sel=0, exactly
26 MHz) calibrates the probe: the dependent-add loop runs at
CPI = 5.0 exactly, and every claimed table frequency checks out
(row 1 = 614.4 kHz claim -> 165 ms for 20M = CPI 5 x 614.4 MHz;
row 8 = 1612 claim -> 62 ms; twpll = 1536 in the kernel clock tree
matches row 7's sel-2 claim).  The vendor's "1612 MHz" is the real
physical frequency - there is no hidden down-rating.

### 7c. The CCF-visible PLL config is a parked shadow

The kernel clock tree (clkwalk) computes mpll0 = 962 MHz and
mpll1 = 1482 MHz from the analog-block config registers - yet the
clusters demonstrably run at 1612.  Capturing those registers idle
vs loaded shows only the lock bit (bit 17) toggling; the N value
never changes with the DVFS state (idle shadow: N=74 integer /
nint 69.231 SDM = exactly 1800.0 MHz for ananke; N=57 / 76.923 =
exactly 2000.0 MHz for prometheus).  => the engine configures the
PLL through a private path; the MMIO config regs and the CCF rates
computed from them are a parked shadow.

### 7d. The slot-rewrite attack: the engine ignores the slot files

The archdata-written slot ladders in the analog blocks are the FULL
FAMILY ladder on this unit (ananke: 884 1040 1378 1612 1716 1820
1950; prometheus: 1040 1404 1612 1690 1820 1898 1950 2002) - not
trimmed per product.  Rewriting ananke slot 3 (the 1612 slot loaded
by lit row 8) with slot 5's verbatim 1820 config (N=62 -> 70), and
row 8's volt column to grade 7 (1.0 V): the FSM executed the
transition, applied the grade-7 voltage (voted_volt = 7) - and the
CPU still ran at exactly 1612 (62 ms / 20M).  The engine does not
read the MMIO slot files for its frequency decision; combined with
the native-rows result (idx 4/5 -> 1612 despite the untrimmed
ladder), the engine's per-mpll-idx frequency table is internal and
never sourced from MMIO - the boot-cache theory is thereby
disproven (a cache of the untrimmed ladder would have delivered
1716/1820).

### 7e. Runtime engine re-init is impossible (kernel panic)

Forcing an FSM re-init via the driver's own module enable
(aon-apb 0x64000000 + 0x4 bit 7, off 1 s / on) panics the kernel
immediately: `reason: bad mode` (pstore console-ramoops captured,
sprd-sysdump flow, clean reboot ~10 s later).  The engine owns the
running clock path; it cannot be disabled under a live CPU.  DO NOT
retry this at runtime.  (A boot-time rewrite of the slot ladder
before the engine reads its tables would require modifying the SPL/
bootloader - outside the software attack surface.)

### 7f. Verdict of the direct inspection

The 1612 MHz ceiling is enforced by the DVFS engine's internal,
fused per-product frequency table.  Everything software can reach -
DT rows, apcpu map tables, analog slot ladders, the work-index
register, the engine's own transition machinery - is honored for
VOLTAGE and ignored for FREQUENCY above the product grade, and the
engine cannot be re-initialized while the system runs.  Same silicon
story as the GPU cap (docs/20 sec. 3d): the T606 is the fused-down
qogirl6 grade.  CPU overclock: CLOSED at the deepest level software
can reach.

## 6. Sources

* `drivers/cpufreq/sprd-hwdvfs-normal.c` (3164 lines): map table
  init/packing, `set_dvfs_work_index`, work-index register flow,
  sysfs via `sprd-sysfs-normal.c`.
* `drivers/cpufreq/sprd-hwdvfs-archdata.c`: `ums9230_mpll_index_tbl`
  (all slot N values), `ums9230_volt_grades_tbl` (grade register map),
  pmic step 3125 uV (sc2730).
* stock boot DTS (`/tmp/stock_b.dts` on the VPS): `cpudvfs-dev@64018000`
  cluster nodes, per-variant map tables, `cpufreq-clus{0,1}`
  operating-points per product/binning.
* Live register dumps: `docs/evidence/2026-11-03-cpu-dvfs-map.txt`
  (see below), pstore panic traces from the GPU experiments
  (docs/evidence/2026-11-03-gpu-untrim-attempts.txt).
