// SPDX-License-Identifier: GPL-2.0
/*
 * gpu-gpll-poker: runtime GPU clock-source re-rater for the Unisoc
 * qogirl6 (UMS9230/T606) Mali-G57 platform glue.
 *
 * Does NOTHING at load.  After insmod it exposes
 * /sys/kernel/gpu_gpll_poker/:
 *
 *   clocks   (ro)  every "clocks" entry of the gpu@ DT node with its rate
 *   index    (rw)  which clock index to operate on (default: last = the
 *                  top GPLL source the DVFS top level muxes in)
 *   rate     (rw)  read the current rate; write a rate in Hz to re-rate
 *                  the source (e.g. echo 768000000 > rate)
 *   rd       (rw)  write a hex offset (0x00-0xfc) to read one GPU DVFS
 *                  APB register; read shows "0xNN: 0xVVVVVVVV".  Only
 *                  while the GPU is powered (under load)!
 *   wr       (wo)  write "0xNN 0xVVVVVVVV" to set one GPU DVFS APB
 *                  register.  Only while the GPU is powered!
 *   guard    (rw)  arm the PRE_RATE_CHANGE notifier that vetoes the
 *                  vendor power-on 650 MHz GPLL re-clamp (0 = disarm)
 *
 * Rationale: the vendor mali glue clamps the top GPLL source to 650 MHz
 * (the T606 product trim) on every GPU power-on.  Re-rating the source
 * while the system runs turns the software "650 MHz" DVFS level into a
 * faster physical clock without touching any boot path - and it is
 * instantly reversible by writing the old rate back.
 *
 * Reference: docs/20-gpu-clock-dvfs.md,
 * docs/evidence/2026-11-03-gpu-untrim-attempts.txt,
 * TheGammaSqueeze/UnisocBypass (UMS512 OC research).
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/clk.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/kobject.h>
#include <linux/sysfs.h>
#include <linux/io.h>
#include <linux/uaccess.h>
#include <linux/clk.h>

#define GPU_DVFS_APB_PHYS	0x23014000
#define GPU_DVFS_APB_SIZE	0x100
#define TOPDVFS_PHYS		0x64014000
#define TOPDVFS_SIZE		0x200
#define APCPU_DVFS_PHYS		0x64018000	/* CPU DVFS map tables (AON) */
#define APCPU_DVFS_SIZE		0x1000
#define GLBREGS_5A_PHYS		0x645a0000	/* CPU mpll slot regs (AON) */
#define GLBREGS_5A_SIZE		0x300
#define GLBREGS_58_PHYS		0x64580000	/* mpll-prometheus analog (AON) */
#define GLBREGS_58_SIZE		0x300
#define AON_APB_PHYS		0x64000000	/* aon apb glbregs (module enables) */
#define AON_APB_SIZE		0x1000

#define POKER_MAX_CLOCKS 12

static struct clk *clks[POKER_MAX_CLOCKS];
static int nclks;
static int cur_index = -1;	/* default: last clock = top GPLL source */

static struct kobject *poker_kobj;

static ssize_t clocks_show(struct kobject *k, struct kobj_attribute *a,
			   char *buf)
{
	int i, len = 0;

	for (i = 0; i < nclks; i++)
		len += scnprintf(buf + len, PAGE_SIZE - len,
				 "%d %lu%s\n", i,
				 (unsigned long)clk_get_rate(clks[i]),
				 i == cur_index ? " <- selected" : "");
	return len;
}

static ssize_t index_show(struct kobject *k, struct kobj_attribute *a,
			  char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%d\n", cur_index);
}

static ssize_t index_store(struct kobject *k, struct kobj_attribute *a,
			   const char *buf, size_t n)
{
	int v, ret;

	ret = kstrtoint(buf, 0, &v);
	if (ret)
		return ret;
	if (v < 0 || v >= nclks)
		return -EINVAL;
	cur_index = v;
	return n;
}

static ssize_t rate_show(struct kobject *k, struct kobj_attribute *a,
			 char *buf)
{
	if (cur_index < 0)
		return -ENODEV;
	return scnprintf(buf, PAGE_SIZE, "%lu\n",
			 (unsigned long)clk_get_rate(clks[cur_index]));
}

static ssize_t rate_store(struct kobject *k, struct kobj_attribute *a,
			  const char *buf, size_t n)
{
	unsigned long hz;
	int ret;

	if (cur_index < 0)
		return -ENODEV;
	ret = kstrtoul(buf, 0, &hz);
	if (ret)
		return ret;

	ret = clk_set_rate(clks[cur_index], hz);
	if (ret) {
		pr_err("gpu_gpll_poker: clk_set_rate(%lu) failed: %d\n", hz, ret);
		return ret;
	}
	pr_info("gpu_gpll_poker: requested %lu Hz on clock %d, now %lu Hz\n",
		hz, cur_index, (unsigned long)clk_get_rate(clks[cur_index]));
	return n;
}

static struct kobj_attribute clocks_attr = __ATTR_RO(clocks);
static struct kobj_attribute index_attr = __ATTR_RW(index);
static struct kobj_attribute rate_attr = __ATTR_RW(rate);

/* Generic GPU DVFS APB (0x23014000) register access for mapping out the
 * hardware DVFS state.  Per the auto-generated register map:
 *   0x2c VOLTAGE_DBG, 0x34 CGM_CFG_DBG (live SYS_DIV[2:0] MEM_DIV[5:3]
 *   CORE_DIV[11:9] CORE_SEL[14:12]), 0x38 STATE_DBG, 0x48..0x64
 * CORE_INDEXn_MAP (VOL_INDEXn[20:18]), 0x8c INDEX_CFG, and the unnamed
 * gap 0x68..0x88 which likely holds the per-index CGM tables
 * (SEL_INDEXn[2:0], CORE_DIV_INDEXn[5:3], MEM_DIV_INDEXn[19:17],
 * SYS_DIV_INDEXn[24:22]).
 * WARNING: any read faults (panic) when the GPU power domain is gated -
 * only read while the GPU is under load. */
static void __iomem *dvfs_reg_base;
static void __iomem *topdvfs_reg_base;	/* likely AON: fused grade tables */
static void __iomem *apcpu_reg_base;	/* CPU DVFS map tables (AON) */
static void __iomem *glb5a_reg_base;	/* mpll-ananke/scu slots (AON) */
static void __iomem *glb58_reg_base;	/* mpll-prometheus slots (AON) */
static void __iomem *aonapb_reg_base;	/* aon apb glbregs (module enables) */
static int reg_base_sel;	/* 0 = gpu dvfs apb, 1 = topdvfs,
				 * 2 = apcpu dvfs, 3 = glbregs 0x645a0000,
				 * 4 = glbregs 0x64580000, 5 = aon apb 0x64000000 */

static void __iomem *sel_base(unsigned long *size)
{
	switch (reg_base_sel) {
	case 1:
		*size = TOPDVFS_SIZE;
		return topdvfs_reg_base;
	case 2:
		*size = APCPU_DVFS_SIZE;
		return apcpu_reg_base;
	case 3:
		*size = GLBREGS_5A_SIZE;
		return glb5a_reg_base;
	case 4:
		*size = GLBREGS_58_SIZE;
		return glb58_reg_base;
	case 5:
		*size = AON_APB_SIZE;
		return aonapb_reg_base;
	default:
		*size = GPU_DVFS_APB_SIZE;
		return dvfs_reg_base;
	}
}

static u32 last_rd_off, last_rd_val;

static ssize_t rd_show(struct kobject *k, struct kobj_attribute *a,
		       char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "0x%02x: 0x%08x\n",
			 last_rd_off, last_rd_val);
}

static ssize_t rd_store(struct kobject *k, struct kobj_attribute *a,
			const char *buf, size_t n)
{
	unsigned long off, size;
	void __iomem *base;
	int ret;

	ret = kstrtoul(buf, 0, &off);
	if (ret)
		return ret;

	base = sel_base(&size);
	if (!base || off >= size || (off & 3))
		return -EINVAL;

	last_rd_off = off;
	last_rd_val = readl_relaxed(base + off);
	pr_info("gpu_gpll_poker: rd(%d) 0x%02x = 0x%08x\n", reg_base_sel,
		last_rd_off, last_rd_val);
	return n;
}

static ssize_t wr_store(struct kobject *k, struct kobj_attribute *a,
			const char *buf, size_t n)
{
	unsigned long off, val, size;
	void __iomem *base;
	int ret;

	ret = sscanf(buf, "%lx %lx", &off, &val);
	if (ret != 2)
		return -EINVAL;

	base = sel_base(&size);
	if (!base || off >= size || (off & 3))
		return -EINVAL;

	writel_relaxed(val, base + off);
	pr_info("gpu_gpll_poker: wr(%d) 0x%02x = 0x%08x\n", reg_base_sel,
		off, (u32)val);
	return n;
}

static ssize_t base_show(struct kobject *k, struct kobj_attribute *a,
			 char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%d\n", reg_base_sel);
}

static ssize_t base_store(struct kobject *k, struct kobj_attribute *a,
			  const char *buf, size_t n)
{
	int v, ret;

	ret = kstrtoint(buf, 0, &v);
	if (ret)
		return ret;
	if (v < 0 || v > 5)
		return -EINVAL;
	reg_base_sel = v;
	return n;
}

static struct kobj_attribute rd_attr = __ATTR_RW(rd);
static struct kobj_attribute wr_attr =
	__ATTR(wr, 0600, rd_show, wr_store);
static struct kobj_attribute base_attr = __ATTR_RW(base);

static ssize_t dump_show(struct kobject *k, struct kobj_attribute *a,
			 char *buf)
{
	unsigned long size;
	void __iomem *base;
	int len = 0;
	int off;

	base = sel_base(&size);
	if (!base)
		return -ENODEV;

	/* PAGE_SIZE buffer: 8 hex chars + space per word = ~500 words */
	for (off = 0; off < size && len < PAGE_SIZE - 16; off += 4) {
		len += scnprintf(buf + len, PAGE_SIZE - len, "%03x:%08x\n",
				 off, readl_relaxed(base + off));
	}
	return len;
}

static struct kobj_attribute dump_attr = __ATTR_RO(dump);

/*
 * ---- transition monitor --------------------------------------------
 * The sprd-hwdvfs engine is a hardware FSM: software writes a work
 * index and the engine performs the whole transition by itself.  This
 * change-detecting sampler triggers a work-index write and records
 * every register change around it, so the engine's own sequence
 * (sel -> safe, mpll reprogram, relock, sel back) becomes visible
 * and the failing step can be identified directly.
 *
 * mon write: "GO <idx-reg> <value> [duration_ms]"
 *   idx-reg: 0x214 (lit) or 0x224 (big); value = work index to poke.
 * mon read:  lines "regid t_ns val" (regid indexes mon_regs below).
 */
static const struct {
	int base;			/* 2 apcpu, 3 ananke, 4 prometheus */
	u32 off;
} mon_regs[] = {
	{2, 0x214},	/* lit work index */
	{2, 0x224},	/* big work index */
	{2, 0x38},	/* cpu0 sel(div pack */
	{2, 0x30},	/* cpu0 volt grades */
	{2, 0x244},	/* ananke relock/pd enable */
	{3, 0x84},	/* mpll0 live cfg reg0 (N @ bits5-15, lock @ bit17) */
	{3, 0x88},	/* mpll0 live cfg reg1 (kint/nint) */
	{4, 0x54},	/* mpll1 live cfg reg0 */
	{4, 0x58},	/* mpll1 live cfg reg1 */
};
#define MON_NREGS	ARRAY_SIZE(mon_regs)
#define MON_ENTRIES	2048

struct mon_ent {
	u64 t;
	u32 reg;
	u32 val;
};
static struct mon_ent mon_ring[MON_ENTRIES];
static int mon_count;
static bool mon_ran;

static void __iomem *mon_base(int base)
{
	switch (base) {
	case 3:
		return glb5a_reg_base;
	case 4:
		return glb58_reg_base;
	default:
		return apcpu_reg_base;
	}
}

static u32 mon_read(int i)
{
	return readl_relaxed(mon_base(mon_regs[i].base) + mon_regs[i].off);
}

static ssize_t mon_store(struct kobject *k, struct kobj_attribute *a,
			  const char *buf, size_t n)
{
	unsigned long idx_reg, val, dur_ms = 300;
	u32 last[MON_NREGS];
	u64 t0, t;
	int i, ret;

	ret = sscanf(buf, "%lx %lx %lu", &idx_reg, &val, &dur_ms);
	if (ret < 2)
		return -EINVAL;
	if (idx_reg != 0x214 && idx_reg != 0x224 && idx_reg != 0)
		return -EINVAL;

	mon_count = 0;
	mon_ran = false;
	memset(last, 0, sizeof(last));

	/* initial snapshot */
	t0 = ktime_get_ns();
	for (i = 0; i < MON_NREGS; i++) {
		last[i] = mon_read(i);
		if (mon_count < MON_ENTRIES) {
			mon_ring[mon_count].t = 0;
			mon_ring[mon_count].reg = i;
			mon_ring[mon_count].val = last[i];
			mon_count++;
		}
	}

	/* trigger: write the work index directly (the engine reacts).
	 * idx_reg == 0 means triggerless: just sample for the duration. */
	if (idx_reg)
		writel_relaxed(val, apcpu_reg_base + idx_reg);

	while (mon_count < MON_ENTRIES) {
		t = ktime_get_ns() - t0;
		if (t > dur_ms * 1000000UL)
			break;
		for (i = 0; i < MON_NREGS; i++) {
			u32 v = mon_read(i);

			if (v != last[i]) {
				last[i] = v;
				mon_ring[mon_count].t = t;
				mon_ring[mon_count].reg = i;
				mon_ring[mon_count].val = v;
				mon_count++;
				if (mon_count >= MON_ENTRIES)
					break;
			}
		}
		cpu_relax();
	}
	mon_ran = true;
	return n;
}

static ssize_t mon_show(struct kobject *k, struct kobj_attribute *a,
			char *buf)
{
	int len = 0;
	int i;

	if (!mon_ran)
		return scnprintf(buf, PAGE_SIZE, "no capture\n");
	for (i = 0; i < mon_count && len < PAGE_SIZE - 48; i++)
		len += scnprintf(buf + len, PAGE_SIZE - len,
				 "%u %llu %08x\n",
				 mon_ring[i].reg,
				 (unsigned long long)mon_ring[i].t,
				 mon_ring[i].val);
	return len;
}

static struct kobj_attribute mon_attr = __ATTR_RW(mon);

/*
 * ---- clk tree walk -----------------------------------------------
 * Resolves __clk_lookup / __clk_get_name via kallsyms (addresses are
 * passed in from userspace - neither is EXPORT_SYMBOL'd) and prints
 * a clock's full parent chain with the rates the kernel computes.
 * clkaddr write: "0x<__clk_lookup> 0x<__clk_get_name>"
 * clkwalk write: "<clk name>"; clkwalk read: the cached chain.
 */
typedef struct clk *(*clk_lookup_fn)(const char *);
typedef const char *(*clk_getname_fn)(const struct clk *);

static clk_lookup_fn do_clk_lookup;
static clk_getname_fn do_clk_getname;
static char clkwalk_buf[1536];
static int clkwalk_len;

static ssize_t clkaddr_store(struct kobject *k, struct kobj_attribute *a,
			     const char *buf, size_t n)
{
	unsigned long a1, a2;
	int ret;

	ret = sscanf(buf, "%lx %lx", &a1, &a2);
	if (ret != 2 || !a1 || !a2)
		return -EINVAL;
	do_clk_lookup = (clk_lookup_fn)a1;
	do_clk_getname = (clk_getname_fn)a2;
	return n;
}
static struct kobj_attribute clkaddr_attr =
	__ATTR(clkaddr, 0600, rd_show, clkaddr_store);

static ssize_t clkwalk_store(struct kobject *k, struct kobj_attribute *a,
			     const char *buf, size_t n)
{
	struct clk *c;
	char name[64];
	int len;

	if (!do_clk_lookup || !do_clk_getname)
		return -ENODEV;
	if (sscanf(buf, "%63s", name) != 1)
		return -EINVAL;

	clkwalk_len = 0;
	clkwalk_buf[0] = '\0';
	c = do_clk_lookup(name);
	if (!c)
		return -ENOENT;

	while (c && clkwalk_len < sizeof(clkwalk_buf) - 96) {
		len = scnprintf(clkwalk_buf + clkwalk_len,
				sizeof(clkwalk_buf) - clkwalk_len,
				"%s %lu\n", do_clk_getname(c),
				(unsigned long)clk_get_rate(c));
		clkwalk_len += len;
		c = clk_get_parent(c);
	}
	return n;
}

static ssize_t clkwalk_show(struct kobject *k, struct kobj_attribute *a,
			    char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%s", clkwalk_buf);
}

static struct kobj_attribute clkwalk_attr = __ATTR_RW(clkwalk);


/* The vendor glue re-clamps the GPLL to 650 MHz (the T606 trim) on every
 * GPU power-on via clk_set_rate().  The clk core honors PRE_RATE_CHANGE
 * aborts (drivers/clk/clk.c: "abort rate change if a driver returns
 * NOTIFY_BAD"), so a notifier that vetoes the 650 MHz request keeps the
 * GPLL at the overclocked rate permanently - no polling, no oscillation.
 * The glue ignores clk_set_rate() errors, so the veto is silent. */
static unsigned long keep_rate;		/* 0: disarmed */
static unsigned long blocked_rate = 650000000UL;

static int rate_guard_nb_fn(struct notifier_block *nb, unsigned long event,
			    void *data)
{
	struct clk_notifier_data *cnd = data;

	if (event == PRE_RATE_CHANGE && keep_rate &&
	    cnd->new_rate == blocked_rate) {
		pr_info("gpu_gpll_poker: vetoed the %lu Hz trim re-clamp (target %lu Hz)\n",
			(unsigned long)cnd->new_rate, keep_rate);
		return NOTIFY_BAD;
	}
	return NOTIFY_OK;
}

static struct notifier_block rate_guard_nb = {
	.notifier_call = rate_guard_nb_fn,
};

static ssize_t guard_show(struct kobject *k, struct kobj_attribute *a,
			  char *buf)
{
	return scnprintf(buf, PAGE_SIZE, "%lu %lu\n", keep_rate,
			 rate_guard_nb.notifier_call ? 1UL : 0UL);
}

static ssize_t guard_store(struct kobject *k, struct kobj_attribute *a,
			   const char *buf, size_t n)
{
	unsigned long hz;
	int ret;

	ret = kstrtoul(buf, 0, &hz);
	if (ret)
		return ret;

	if (hz == 0) {
		/* disarm: restore the stock trim rate */
		if (keep_rate) {
			clk_notifier_unregister(clks[cur_index], &rate_guard_nb);
			clk_set_rate(clks[cur_index], blocked_rate);
		}
		keep_rate = 0;
		return n;
	}

	/* arm with the requested overclock rate */
	keep_rate = hz;
	clk_set_rate(clks[cur_index], keep_rate);
	ret = clk_notifier_register(clks[cur_index], &rate_guard_nb);
	if (ret) {
		pr_err("gpu_gpll_poker: notifier registration failed: %d\n", ret);
		return ret;
	}
	pr_info("gpu_gpll_poker: guard armed: GPLL %lu Hz, vetoes %lu Hz re-clamps\n",
		(unsigned long)clk_get_rate(clks[cur_index]), blocked_rate);
	return n;
}

static struct kobj_attribute guard_attr = __ATTR_RW(guard);
static struct attribute *poker_attrs[] = {
	&clocks_attr.attr,
	&index_attr.attr,
	&rate_attr.attr,
	&base_attr.attr,
	&rd_attr.attr,
	&wr_attr.attr,
	&dump_attr.attr,
	&mon_attr.attr,
	&clkaddr_attr.attr,
	&clkwalk_attr.attr,
	&guard_attr.attr,
	NULL,
};

static const struct attribute_group poker_group = {
	.attrs = poker_attrs,
};

static int __init gpll_poker_init(void)
{
	struct device_node *np;
	struct clk *c;
	int i, ret;

	dvfs_reg_base = ioremap(0x23014000, 0x100);
	if (!dvfs_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap the GPU DVFS APB\n");
		return -ENOMEM;
	}
	topdvfs_reg_base = ioremap(TOPDVFS_PHYS, TOPDVFS_SIZE);
	if (!topdvfs_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap the topdvfs controller\n");
		return -ENOMEM;
	}
	apcpu_reg_base = ioremap(APCPU_DVFS_PHYS, APCPU_DVFS_SIZE);
	if (!apcpu_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap the apcpu dvfs block\n");
		return -ENOMEM;
	}
	glb5a_reg_base = ioremap(GLBREGS_5A_PHYS, GLBREGS_5A_SIZE);
	if (!glb5a_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap glbregs 0x645a0000\n");
		return -ENOMEM;
	}
	glb58_reg_base = ioremap(GLBREGS_58_PHYS, GLBREGS_58_SIZE);
	if (!glb58_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap glbregs 0x64580000\n");
		return -ENOMEM;
	}
	aonapb_reg_base = ioremap(AON_APB_PHYS, AON_APB_SIZE);
	if (!aonapb_reg_base) {
		pr_err("gpu_gpll_poker: cannot ioremap aon apb glbregs\n");
		return -ENOMEM;
	}

	np = of_find_compatible_node(NULL, NULL, "sprd,mali-natt");
	if (!np) {
		pr_err("gpu_gpll_poker: gpu node (sprd,mali-natt) not found\n");
		return -ENODEV;
	}

	for (i = 0; i < POKER_MAX_CLOCKS; i++) {
		c = of_clk_get(np, i);
		if (IS_ERR(c)) {
			nclks = i;
			break;
		}
		clks[i] = c;
	}
	of_node_put(np);

	if (!nclks) {
		pr_err("gpu_gpll_poker: no clocks on the gpu node\n");
		return -ENODEV;
	}
	cur_index = nclks - 1;

	poker_kobj = kobject_create_and_add("gpu_gpll_poker", kernel_kobj);
	if (!poker_kobj)
		return -ENOMEM;

	ret = sysfs_create_group(poker_kobj, &poker_group);
	if (ret) {
		kobject_put(poker_kobj);
		return ret;
	}

	pr_info("gpu_gpll_poker: %d clocks, default index %d (rate %lu Hz); controls in /sys/kernel/gpu_gpll_poker/\n",
		nclks, cur_index,
		(unsigned long)clk_get_rate(clks[cur_index]));
	return 0;
}

static void __exit gpll_poker_exit(void)
{
	int i;

	if (keep_rate) {
		clk_notifier_unregister(clks[cur_index], &rate_guard_nb);
		clk_set_rate(clks[cur_index], blocked_rate);
		keep_rate = 0;
	}
	if (topdvfs_reg_base)
		iounmap(topdvfs_reg_base);
	if (apcpu_reg_base)
		iounmap(apcpu_reg_base);
	if (glb5a_reg_base)
		iounmap(glb5a_reg_base);
	if (glb58_reg_base)
		iounmap(glb58_reg_base);
	if (aonapb_reg_base)
		iounmap(aonapb_reg_base);
	if (dvfs_reg_base)
		iounmap(dvfs_reg_base);
	if (poker_kobj) {
		sysfs_remove_group(poker_kobj, &poker_group);
		kobject_put(poker_kobj);
	}
	for (i = 0; i < nclks; i++)
		clk_put(clks[i]);
}

module_init(gpll_poker_init);
module_exit(gpll_poker_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("runtime GPU GPLL source re-rater (Unisoc qogirl6, Moto E32)");
