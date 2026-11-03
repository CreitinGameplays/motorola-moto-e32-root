#!/usr/bin/env python3
"""Add the `untrim_gpll` module parameter to the qogirl6 Mali glue.

The Unisoc glue trims the GPU DVFS table per SoC: on T606/T612 the GPLL
source is clamped to 650 MHz (the 850 MHz DTS level is rewritten to 650,
the 768 MHz level is dropped, and the 768/850 OPPs are disabled).  That is
product segmentation - the DTS offers 768/850 @ 800 mV and T615/T620 run
them on the same Mali-G57 MP1.

This adds `mali_kbase.untrim_gpll` (bool, default 0 = stock behavior):

  * mali_freq_init:            keep the full 5-level DTS table
  * mali_clock_on:             request the DTS rate for the top GPLL source
                               (instead of clamping it to 650 MHz) and log
                               the rate the clock framework actually granted
  * kbase_platform_limit_max_freq: keep the 768/850 OPPs enabled

Test procedure and baseline: docs/20-gpu-clock-dvfs.md,
benchmarks/gpu/base_650mhz/BASELINE.md.
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/kernel-sprd")
p = os.path.join(root, "drivers/gpu/arm/midgard/platform/qogirl6/"
                       "mali_kbase_config_qogirl6.c")
s = open(p).read()
bs = chr(92)


def rep(old, new):
    global s
    if new in s and old not in s:
        print("already patched:", old[:60].replace("\n", " "))
        return
    if old not in s:
        raise SystemExit("pattern not found:\n" + old[:200])
    s = s.replace(old, new, 1)
    print("patched:", old.strip().splitlines()[0][:60])


# 0. the module parameter (after the existing #defines)
rep(
    """#define GPU_768M_FREQ       768000000
#define GPU_850M_FREQ       850000000
""",
    """#define GPU_768M_FREQ       768000000
#define GPU_850M_FREQ       850000000

/*
 * Experimental: keep the untrimmed DTS DVFS levels (768/850 MHz @ 800 mV,
 * the T615/T620 table) instead of the T606/T612 650 MHz GPLL trim.
 * Default 0 = exactly the stock behavior.  See docs/20-gpu-clock-dvfs.md.
 */
static bool untrim_gpll;
module_param(untrim_gpll, bool, 0444);
MODULE_PARM_DESC(untrim_gpll,
		 "keep the DTS 768/850 MHz GPU levels (skip the T606 GPLL trim)");
""",
)

# 1. mali_freq_init: keep the full table
rep(
    """	if (auto_efuse && (!strcmp(auto_efuse, "T606") ||
			   !strcmp(auto_efuse, "T612"))) {
		/* GPLL max frequency for T606/T612 is 650 MHz */
		gpu_dvfs_ctx.freq_list[gpu_dvfs_ctx.freq_list_len - 1].freq =
			T606_GPLL_FREQ / FREQ_KHZ;
""",
    """	if (!untrim_gpll && auto_efuse &&
	    (!strcmp(auto_efuse, "T606") || !strcmp(auto_efuse, "T612"))) {
		/* GPLL max frequency for T606/T612 is 650 MHz */
		gpu_dvfs_ctx.freq_list[gpu_dvfs_ctx.freq_list_len - 1].freq =
			T606_GPLL_FREQ / FREQ_KHZ;
""",
)

# 2. mali_clock_on: request the DTS rate for the top source when untrimmed
rep(
    """	if (auto_efuse && gpu_dvfs_ctx.freq_list_len) {
		int last = gpu_dvfs_ctx.freq_list_len - 1;

		if (!strcmp(auto_efuse, "T606") ||
		    !strcmp(auto_efuse, "T612") ||
		    !strcmp(auto_efuse, "T616"))
			clk_set_rate(gpu_dvfs_ctx.freq_list[last].clk_src,
				     (unsigned long)gpu_dvfs_ctx.freq_list[last].freq *
					     FREQ_KHZ);
	}
""",
    """	if (auto_efuse && gpu_dvfs_ctx.freq_list_len) {
		int last = gpu_dvfs_ctx.freq_list_len - 1;
		unsigned long want = (unsigned long)
			gpu_dvfs_ctx.freq_list[last].freq * FREQ_KHZ;
		unsigned long got;

		if (untrim_gpll) {
			/* experimental: ask for the DTS rate (850 MHz on
			 * T606) and log what the PLL actually grants */
			got = clk_set_rate(gpu_dvfs_ctx.freq_list[last].clk_src,
					   want);
			dev_info(gpu_dvfs_ctx.dev,
				 "mali: untrim_gpll: requested %lu Hz on the top GPLL source, granted %lu Hz\\n",
				 want, got);
		} else if (!strcmp(auto_efuse, "T606") ||
			   !strcmp(auto_efuse, "T612") ||
			   !strcmp(auto_efuse, "T616")) {
			clk_set_rate(gpu_dvfs_ctx.freq_list[last].clk_src, want);
		}
	}
""",
)

# 3. kbase_platform_limit_max_freq: keep the 768/850 OPPs
rep(
    """	if (auto_efuse && (!strcmp(auto_efuse, "T606") ||
			   !strcmp(auto_efuse, "T612") ||
			   !strcmp(auto_efuse, "T616"))) {
		dev_pm_opp_disable(dev, GPU_768M_FREQ);
		dev_pm_opp_disable(dev, GPU_850M_FREQ);
""",
    """	if (!untrim_gpll && auto_efuse &&
	    (!strcmp(auto_efuse, "T606") || !strcmp(auto_efuse, "T612") ||
	     !strcmp(auto_efuse, "T616"))) {
		dev_pm_opp_disable(dev, GPU_768M_FREQ);
		dev_pm_opp_disable(dev, GPU_850M_FREQ);
""",
)

open(p, "w").write(s)
print("ok")
