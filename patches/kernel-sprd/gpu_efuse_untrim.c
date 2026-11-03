// SPDX-License-Identifier: GPL-2.0
/*
 * Unisoc qogirl6 GPU DVFS un-trim for the Moto E32 (hawaii, UMS9230/T606).
 *
 * The Mali glue in both the vendor and our in-tree build trims the GPU
 * DVFS table per SoC by matching the /hwfeature/auto "efuse" string
 * against "T606"/"T612"/"T616" (mali_freq_init rewrites the 850 MHz DTS
 * level to the 650 MHz GPLL trim, drops the 768 MHz level, and
 * kbase_platform_limit_max_freq() disables the 768/850 OPPs).  That is
 * product segmentation: the boot DTS offers the full 5-level table
 * (384/512/614.4/768/850 MHz at 700/750/750/800/800 mV) and T615/T620 run
 * the two top levels on the same Mali-G57 MP1 silicon.
 *
 * The /hwfeature/auto node is injected by the SPL/U-Boot fixup, so it
 * cannot be changed in the dtbo.  Renaming the string in the unflattened
 * device tree (before any module loads) makes the glue keep the untrimmed
 * table.  Value is edited in place with the same length, so the DTB
 * structure does not change.
 *
 * Baseline and procedure: docs/20-gpu-clock-dvfs.md,
 * benchmarks/gpu/base_650mhz/BASELINE.md.
 */
#include <linux/init.h>
#include <linux/of.h>
#include <linux/string.h>
#include <linux/printk.h>

static int __init sprd_gpu_untrim_efuse(void)
{
	struct device_node *np;
	struct property *pp;

	np = of_find_node_by_path("/hwfeature/auto");
	if (!np)
		return 0;

	for (pp = np->properties; pp; pp = pp->next) {
		if (!strcmp(pp->name, "efuse") && pp->length >= 5 &&
		    pp->value && !strcmp(pp->value, "T606")) {
			memcpy(pp->value, "T60X", 5);
			pr_info("sprd-gpu-untrim: /hwfeature/auto efuse T606 -> T60X; the GPU glue keeps the DTS 768/850 MHz levels\n");
		}
	}
	of_node_put(np);
	return 0;
}
arch_initcall(sprd_gpu_untrim_efuse);
