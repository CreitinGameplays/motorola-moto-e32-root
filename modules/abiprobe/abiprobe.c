// ABI offsets probe: prints offsetof()/sizeof() for the structs the
// vendor modules share with the kernel.  Load it on the reference
// (vendor-module-compat, no-KVM) kernel and on the KVM kernel; the two
// listings must be identical, otherwise the KVM config changes struct
// layouts the CFI-built vendor modules depend on.
//
// Build as an external module against a prepared kernel build dir:
//   make O=<builddir> M=<this dir> modules
#include <linux/module.h>
#include <linux/sched.h>
#include <linux/mm_types.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/netdevice.h>
#include <linux/skbuff.h>
#include <linux/platform_device.h>
#include <linux/dma-buf.h>
#include <linux/timer.h>
#include <linux/pm.h>
#include <linux/hrtimer.h>
#include <linux/iova.h>
#include <linux/completion.h>
#include <linux/mutex.h>
#include <linux/semaphore.h>
#include <linux/preempt.h>
#include <linux/mmu_notifier.h>

#define E(x) { #x, (unsigned long)(x) }

static const struct { const char *name; unsigned long val; } tbl[] = {
	/* struct module (also the CFI-compat field) */
	E(offsetof(struct module, mkobj)),
	E(offsetof(struct module, num_syms)),
	E(offsetof(struct module, cfi_check)),
	E(offsetof(struct module, kp)),
	E(offsetof(struct module, num_kp)),
	E(offsetof(struct module, init)),
	E(offsetof(struct module, core_layout)),
	E(offsetof(struct module, init_layout)),
	E(offsetof(struct module, arch)),
	E(offsetof(struct module, taints)),
	E(offsetof(struct module, args)),
	E(sizeof(struct module)),

	/* struct timer_list (the other CFI-compat field) */
	E(offsetof(struct timer_list, entry)),
	E(offsetof(struct timer_list, expires)),
	E(offsetof(struct timer_list, function)),
	E(offsetof(struct timer_list, data)),
	E(offsetof(struct timer_list, flags)),
	E(offsetof(struct timer_list, __function)),
	E(sizeof(struct timer_list)),

	/* struct device + dev_pm_info (timer_list is embedded in PM) */
	E(offsetof(struct device, parent)),
	E(offsetof(struct device, kobj)),
	E(offsetof(struct device, driver)),
	E(offsetof(struct device, platform_data)),
	E(offsetof(struct device, driver_data)),
	E(offsetof(struct device, power)),
	E(offsetof(struct device, pm_domain)),
	E(offsetof(struct device, of_node)),
	E(offsetof(struct device, fwnode)),
	E(offsetof(struct device, dma_mask)),
	E(sizeof(struct device)),
	E(offsetof(struct dev_pm_info, suspend_timer)),
	E(offsetof(struct dev_pm_info, timer_expires)),
	E(offsetof(struct dev_pm_info, work)),
	E(offsetof(struct dev_pm_info, wait_queue)),
	E(offsetof(struct dev_pm_info, wakeirq)),
	E(offsetof(struct dev_pm_info, usage_count)),
	E(offsetof(struct dev_pm_info, child_count)),
	E(sizeof(struct dev_pm_info)),

	/* struct task_struct (KVM adds preempt_notifiers) */
	E(offsetof(struct task_struct, pid)),
	E(offsetof(struct task_struct, tgid)),
	E(offsetof(struct task_struct, comm)),
	E(offsetof(struct task_struct, mm)),
	E(offsetof(struct task_struct, files)),
	E(offsetof(struct task_struct, real_parent)),
	E(offsetof(struct task_struct, group_leader)),
	E(offsetof(struct task_struct, on_cpu)),
	E(offsetof(struct task_struct, state)),
	E(offsetof(struct task_struct, stack)),
#ifdef CONFIG_PREEMPT_NOTIFIERS
	E(offsetof(struct task_struct, preempt_notifiers)),
#endif
	E(offsetof(struct task_struct, thread)),
	E(sizeof(struct task_struct)),

	/* struct mm_struct (KVM adds mmu_notifier_mm) */
	E(offsetof(struct mm_struct, mmap)),
	E(offsetof(struct mm_struct, mm_users)),
	E(offsetof(struct mm_struct, mm_count)),
	E(offsetof(struct mm_struct, pgd)),
	E(offsetof(struct mm_struct, exe_file)),
	E(offsetof(struct mm_struct, tlb_flush_pending)),
	E(offsetof(struct mm_struct, uprobes_state)),
	E(offsetof(struct mm_struct, binfmt)),
#ifdef CONFIG_MMU_NOTIFIER
	E(offsetof(struct mm_struct, mmu_notifier_mm)),
#endif
	E(sizeof(struct mm_struct)),

	/* struct file */
	E(offsetof(struct file, f_path)),
	E(offsetof(struct file, f_inode)),
	E(offsetof(struct file, f_op)),
	E(offsetof(struct file, f_count)),
	E(offsetof(struct file, f_flags)),
	E(offsetof(struct file, f_mode)),
	E(offsetof(struct file, f_pos)),
	E(offsetof(struct file, private_data)),
	E(sizeof(struct file)),

	/* struct net_device (watchdog_timer embeds a timer_list) */
	E(offsetof(struct net_device, name)),
	E(offsetof(struct net_device, mem_end)),
	E(offsetof(struct net_device, watchdog_timer)),
	E(offsetof(struct net_device, num_tx_queues)),
	E(offsetof(struct net_device, ifindex)),
	E(offsetof(struct net_device, flags)),
	E(offsetof(struct net_device, mtu)),
	E(offsetof(struct net_device, type)),
	E(offsetof(struct net_device, hard_header_len)),
	E(offsetof(struct net_device, netdev_ops)),
	E(offsetof(struct net_device, ethtool_ops)),
	E(offsetof(struct net_device, features)),
	E(offsetof(struct net_device, hw_features)),
	E(sizeof(struct net_device)),

	/* struct sk_buff */
	E(offsetof(struct sk_buff, next)),
	E(offsetof(struct sk_buff, prev)),
	E(offsetof(struct sk_buff, sk)),
	E(offsetof(struct sk_buff, dev)),
	E(offsetof(struct sk_buff, cb)),
	E(offsetof(struct sk_buff, head)),
	E(offsetof(struct sk_buff, data)),
	E(offsetof(struct sk_buff, tail)),
	E(offsetof(struct sk_buff, end)),
	E(offsetof(struct sk_buff, len)),
	E(offsetof(struct sk_buff, data_len)),
	E(offsetof(struct sk_buff, users)),
	E(sizeof(struct sk_buff)),

	/* struct platform_device */
	E(offsetof(struct platform_device, name)),
	E(offsetof(struct platform_device, id)),
	E(offsetof(struct platform_device, resource)),
	E(offsetof(struct platform_device, num_resources)),
	E(offsetof(struct platform_device, dev)),
	E(sizeof(struct platform_device)),

	/* struct dma_buf */
	E(offsetof(struct dma_buf, size)),
	E(offsetof(struct dma_buf, file)),
	E(offsetof(struct dma_buf, ops)),
	E(offsetof(struct dma_buf, priv)),
	E(sizeof(struct dma_buf)),

	/* struct wakeup_source (module passes these by pointer) */
	E(offsetof(struct wakeup_source, name)),
	E(offsetof(struct wakeup_source, entry)),
	E(offsetof(struct wakeup_source, timer)),
	E(offsetof(struct wakeup_source, wakeup_count)),
	E(sizeof(struct wakeup_source)),

	/* struct iova_domain (timer_list embedded, IOMMU path) */
	E(offsetof(struct iova_domain, fq)),
	E(offsetof(struct iova_domain, fq_flush_start_cnt)),
	E(offsetof(struct iova_domain, fq_flush_finish_cnt)),
	E(offsetof(struct iova_domain, fq_timer)),
	E(offsetof(struct iova_domain, fq_timer_on)),
	E(sizeof(struct iova_domain)),

	/* small by-value types */
	E(sizeof(struct completion)),
	E(sizeof(struct mutex)),
	E(sizeof(struct semaphore)),
	E(sizeof(struct work_struct)),
	E(sizeof(struct hrtimer)),
	E(sizeof(struct list_head)),
	E(sizeof(struct hlist_head)),
};

static int __init abiprobe_init(void)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(tbl); i++)
		pr_info("ABIPROBE: %-52s %lu\n", tbl[i].name, tbl[i].val);
	pr_info("ABIPROBE: %d entries\n", (int)ARRAY_SIZE(tbl));
	return -EINVAL; /* never stay loaded */
}
module_init(abiprobe_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("struct ABI offsets probe");
