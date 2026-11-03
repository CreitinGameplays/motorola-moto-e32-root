// SPDX-License-Identifier: GPL-2.0
/*
 * gpu_dvfs_untrim - runtime GPU DVFS un-trim for the T606 (Moto E32)
 *
 * The stock vendor mali_kbase.ko (qogirl6 glue) trims the GPU DVFS table
 * on T606/T616 parts.  In mali_freq_init() the 768 MHz DTS level
 * (dvfs index 3, FIXED twpll-768M source, 800 mV) is overwritten with a
 * copy of the 850 MHz entry relabeled to 650 MHz (GPLL source, dvfs
 * index 4), and kbase_platform_limit_max_freq() disables the 768/850
 * OPPs and adds a 650 MHz one.
 *
 * This module restores the REAL 768 MHz level at runtime, in the memory
 * of the running vendor module, and re-enables the 768 OPP.  After that
 * the vendor devfreq path targets 768 MHz natively: set_freq_volt()
 * writes dvfs index 3 to the GPU DVFS APB INDEX_CFG register and the
 * topdvfs hardware performs the mux + voltage switch (CORE_INDEX3_MAP,
 * programmed per gpu_binning by the vendor clock_on code).  No clock
 * rates are poked; the GPLL power-on trim
 *     clk_set_rate(freq_list[last].clk_src, freq_list[last].freq * 1000)
 * becomes a no-op because the top entry's clk_src is repointed to the
 * fixed 768 MHz source.
 *
 * All struct offsets are disassembly- AND runtime-verified against the
 * vendor binary (md5 f218157090f91832550cdd76f469f355); the layout is
 * identical to our in-tree copy of the glue:
 *   struct gpu_dvfs_context: freq_list @ +64, freq_list_len @ +72,
 *     cur_index @ +76
 *   struct gpu_freq_info (stride 24): clk_src @ +0, freq(kHz) @ +8,
 *     volt(uV) @ +12, div @ +16, dvfs_index @ +20
 * Every value is validated before anything is written; a mismatch aborts
 * with no side effects.  Intermediate patch states are benign: the worst
 * case is one governor pass selecting a (label, hardware level) pair
 * that the hardware knows how to set.
 *
 * Usage (as root):
 *   echo 0 > /proc/sys/kernel/kptr_restrict            # kallsyms addrs
 *   ADDR=$(grep gpu_dvfs_ctx /proc/kallsyms | awk '{print $1}')
 *   echo 0x$ADDR > /sys/kernel/gpu_dvfs_untrim/ctx
 *   cat /sys/kernel/gpu_dvfs_untrim/state              # verify layout
 *   echo 1 > /sys/kernel/gpu_dvfs_untrim/untrim       # apply
 *   cat /sys/class/devfreq/23100000.gpu/available_frequencies
 *   echo 0 > /sys/kernel/gpu_dvfs_untrim/untrim       # revert
 *
 * Reference: docs/20-gpu-clock-dvfs.md,
 * docs/evidence/2026-11-03-gpu-untrim-attempts.txt.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/clk.h>
#include <linux/of.h>
#include <linux/pm_opp.h>
#include <linux/device.h>
#include <linux/platform_device.h>
#include <linux/kobject.h>
#include <linux/sysfs.h>
#include <linux/string.h>
#include <linux/errno.h>

#define CTX_FREQ_LIST_OFF	64
#define CTX_FREQ_LIST_LEN_OFF	72

#define ENTRY_STRIDE		24
#define ENTRY_FREQ_OFF		8
#define ENTRY_VOLT_OFF		12
#define ENTRY_DIV_OFF		16
#define ENTRY_DVFS_IDX_OFF	20

#define GPU_NODE_PATH	"/soc/mm/gpu@23100000"
#define GPU_DEV_NAME	"23100000.gpu"
#define CLK_IDX_768M	7		/* of_clk_get(gpu_node, 7) */
#define FREQ_768_KHZ	768000
#define FREQ_650_KHZ	650000
#define FREQ_UNTRIM_HZ	768000000UL

/* saved vendor freq_list[3] for revert */
static struct {
	u64	clk_src;
	u32	freq;
	u32	volt;
	u32	div;
	u32	dvfs_index;
} orig;
static bool applied;
static u64 ctx_addr;
static struct kobject *untrim_kobj;

static inline u32 rd32(u64 addr)
{
	return *(u32 *)(uintptr_t)addr;
}

static inline u64 rd64(u64 addr)
{
	return *(u64 *)(uintptr_t)addr;
}

static inline void wr32(u64 addr, u32 v)
{
	*(u32 *)(uintptr_t)addr = v;
}

static inline void wr64(u64 addr, u64 v)
{
	*(u64 *)(uintptr_t)addr = v;
}

static u64 entry_base(u64 list, int idx)
{
	return list + (u64)idx * ENTRY_STRIDE;
}

static struct device *gpu_dev_found;

static int find_gpu_dev(struct device *dev, void *data)
{
	if (!strcmp(dev_name(dev), GPU_DEV_NAME)) {
		gpu_dev_found = dev;
		return 1;
	}
	return 0;
}

static struct device *get_gpu_dev(void)
{
	gpu_dev_found = NULL;
	bus_for_each_dev(&platform_bus_type, NULL, NULL, find_gpu_dev);
	return gpu_dev_found;
}

static ssize_t state_show(struct kobject *k, struct kobj_attribute *a,
			  char *buf)
{
	int len = 0;
	int i;

	if (!ctx_addr) {
		len += scnprintf(buf + len, PAGE_SIZE - len,
				 "ctx not set - write the gpu_dvfs_ctx kallsyms address first\n");
		return len;
	}

	len += scnprintf(buf + len, PAGE_SIZE - len,
			 "ctx=0x%016llx applied=%d\n",
			 (unsigned long long)ctx_addr, applied);

	/* raw qwords around the ctx so layout drift is visible */
	for (i = 0; i <= 12; i++) {
		u64 addr = ctx_addr + (u64)i * 8;

		len += scnprintf(buf + len, PAGE_SIZE - len,
				 "+%03zx: %016llx\n", (size_t)(i * 8),
				 (unsigned long long)rd64(addr));
	}

	{
		u64 list = rd64(ctx_addr + CTX_FREQ_LIST_OFF);
		u32 list_len = rd32(ctx_addr + CTX_FREQ_LIST_LEN_OFF);
		int n = min(list_len, 5U);
		int i;

		len += scnprintf(buf + len, PAGE_SIZE - len,
				 "freq_list=0x%016llx len=%u\n",
				 (unsigned long long)list, list_len);

		if (list) {
			for (i = 0; i < n; i++) {
				u64 e = entry_base(list, i);

				len += scnprintf(buf + len, PAGE_SIZE - len,
						 "idx%d: clk_src=0x%016llx freq=%u volt=%u div=%u dvfs_index=%u\n",
						 i,
						 (unsigned long long)rd64(e),
						 rd32(e + ENTRY_FREQ_OFF),
						 rd32(e + ENTRY_VOLT_OFF),
						 rd32(e + ENTRY_DIV_OFF),
						 rd32(e + ENTRY_DVFS_IDX_OFF));
			}
		}
	}

	return len;
}

static ssize_t ctx_show(struct kobject *k, struct kobj_attribute *a,
			char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "0x%016llx\n",
			 (unsigned long long)ctx_addr);
}

static ssize_t ctx_store(struct kobject *k, struct kobj_attribute *a,
			 const char *buf, size_t n)
{
	u64 v;
	int ret;

	ret = kstrtoull(buf, 0, &v);
	if (ret)
		return ret;
	if (applied) {
		pr_err("gpu_dvfs_untrim: revert before changing ctx\n");
		return -EBUSY;
	}
	ctx_addr = v;
	return n;
}

static ssize_t untrim_show(struct kobject *k, struct kobj_attribute *a,
			   char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%d\n", applied);
}

static int validate_table(u64 list, u32 list_len)
{
	static const u32 expect[4] = { 384000, 512000, 614400, 650000 };
	int i;

	if (list_len != 4) {
		pr_err("gpu_dvfs_untrim: freq_list_len %u != 4 (layout drift?)\n",
		       list_len);
		return -EINVAL;
	}
	for (i = 0; i < 4; i++) {
		u32 f = rd32(entry_base(list, i) + ENTRY_FREQ_OFF);

		if (f != expect[i]) {
			pr_err("gpu_dvfs_untrim: freq_list[%d].freq=%u, expected %u - aborting\n",
			       i, f, expect[i]);
			return -EINVAL;
		}
	}
	if (rd32(entry_base(list, 3) + ENTRY_VOLT_OFF) != 800000) {
		pr_err("gpu_dvfs_untrim: top level volt %u != 800000 - aborting\n",
		       rd32(entry_base(list, 3) + ENTRY_VOLT_OFF));
		return -EINVAL;
	}
	return 0;
}

static int untrim_apply(void)
{
	u64 list, e3;
	struct device *gpu_dev;
	struct device_node *np;
	struct clk *clk768;
	u32 list_len;
	int ret;

	if (!ctx_addr)
		return -ENODEV;

	list = rd64(ctx_addr + CTX_FREQ_LIST_OFF);
	list_len = rd32(ctx_addr + CTX_FREQ_LIST_LEN_OFF);

	ret = validate_table(list, list_len);
	if (ret)
		return ret;

	e3 = entry_base(list, 3);

	/* the fixed 768 MHz source clock (DT clocks[7] = gc-pll #1) */
	np = of_find_node_by_path(GPU_NODE_PATH);
	if (!np) {
		pr_err("gpu_dvfs_untrim: %s not found\n", GPU_NODE_PATH);
		return -ENODEV;
	}
	clk768 = of_clk_get(np, CLK_IDX_768M);
	of_node_put(np);
	if (IS_ERR(clk768)) {
		pr_err("gpu_dvfs_untrim: of_clk_get(%s, %d) failed: %ld\n",
		       GPU_NODE_PATH, CLK_IDX_768M, PTR_ERR(clk768));
		return PTR_ERR(clk768);
	}
	if (clk_get_rate(clk768) != FREQ_UNTRIM_HZ) {
		pr_err("gpu_dvfs_untrim: clocks[7] rate %lu != 768 MHz\n",
		       (unsigned long)clk_get_rate(clk768));
		return -EINVAL;
	}

	/* save the trimmed entry for revert */
	orig.clk_src = rd64(e3);
	orig.freq = rd32(e3 + ENTRY_FREQ_OFF);
	orig.volt = rd32(e3 + ENTRY_VOLT_OFF);
	orig.div = rd32(e3 + ENTRY_DIV_OFF);
	orig.dvfs_index = rd32(e3 + ENTRY_DVFS_IDX_OFF);

	gpu_dev = get_gpu_dev();
	if (!gpu_dev) {
		pr_err("gpu_dvfs_untrim: platform device %s not found\n",
		       GPU_DEV_NAME);
		return -ENODEV;
	}

	/*
	 * Restore the true 768 MHz level in place:
	 *   clk_src    -> fixed 768 MHz source (power-on GPLL trim = no-op)
	 *   dvfs_index -> 3 (hardware: mux to twpll-768M + CORE_INDEX3_MAP)
	 *   freq       -> 768000 kHz (label, written last)
	 */
	wr64(e3, (u64)clk768);
	wr32(e3 + ENTRY_DVFS_IDX_OFF, 3);
	wmb();
	wr32(e3 + ENTRY_FREQ_OFF, FREQ_768_KHZ);

	ret = dev_pm_opp_enable(gpu_dev, FREQ_UNTRIM_HZ);
	if (ret) {
		pr_err("gpu_dvfs_untrim: dev_pm_opp_enable(768MHz) failed: %d - reverting\n",
		       ret);
		wr32(e3 + ENTRY_FREQ_OFF, FREQ_650_KHZ);
		wmb();
		wr32(e3 + ENTRY_DVFS_IDX_OFF, orig.dvfs_index);
		wr64(e3, orig.clk_src);
		return ret;
	}

	applied = true;
	pr_info("gpu_dvfs_untrim: 768 MHz level restored (was freq=%u dvfs_index=%u), OPP enabled - governor will pick it under load\n",
		orig.freq, orig.dvfs_index);
	return 0;
}

static void untrim_revert(void)
{
	u64 list, e3;

	if (!applied || !ctx_addr)
		return;

	list = rd64(ctx_addr + CTX_FREQ_LIST_OFF);
	e3 = entry_base(list, 3);

	/* back to the stock trimmed 650 MHz entry (label first) */
	wr32(e3 + ENTRY_FREQ_OFF, FREQ_650_KHZ);
	wmb();
	wr32(e3 + ENTRY_DVFS_IDX_OFF, orig.dvfs_index);
	wr64(e3, orig.clk_src);

	if (gpu_dev_found)
		dev_pm_opp_disable(gpu_dev_found, FREQ_UNTRIM_HZ);

	applied = false;
	pr_info("gpu_dvfs_untrim: reverted to the stock 650 MHz trim\n");
}

static ssize_t untrim_store(struct kobject *k, struct kobj_attribute *a,
			    const char *buf, size_t n)
{
	int v, ret;

	ret = kstrtoint(buf, 0, &v);
	if (ret)
		return ret;

	if (v == 1 && !applied) {
		ret = untrim_apply();
		if (ret)
			return ret;
	} else if (v == 0 && applied) {
		untrim_revert();
	} else {
		return -EINVAL;
	}

	return n;
}

static struct kobj_attribute state_attr = __ATTR_RO(state);
static struct kobj_attribute ctx_attr = __ATTR_RW(ctx);
static struct kobj_attribute untrim_attr = __ATTR_RW(untrim);

static struct attribute *untrim_attrs[] = {
	&state_attr.attr,
	&ctx_attr.attr,
	&untrim_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(untrim);

static int __init gpu_dvfs_untrim_init(void)
{
	untrim_kobj = kobject_create_and_add("gpu_dvfs_untrim", kernel_kobj);
	if (!untrim_kobj)
		return -ENOMEM;

	if (sysfs_create_groups(untrim_kobj, untrim_groups)) {
		kobject_put(untrim_kobj);
		return -ENOMEM;
	}

	pr_info("gpu_dvfs_untrim: ready - write the gpu_dvfs_ctx address from /proc/kallsyms to ctx, then 1 to untrim\n");
	return 0;
}

static void __exit gpu_dvfs_untrim_exit(void)
{
	untrim_revert();
	kobject_put(untrim_kobj);
}

module_init(gpu_dvfs_untrim_init);
module_exit(gpu_dvfs_untrim_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Runtime T606 GPU DVFS un-trim (restore the 768 MHz hardware level)");
