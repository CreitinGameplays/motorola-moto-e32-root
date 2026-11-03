# abiprobe: KVM kernel vs no-KVM reference (2026-11-03)

reference: abiprobe-reference-no-kvm-4.14.199-ab612c2.txt (no-KVM compat
kernel, all vendor modules working)
kvm:       abiprobe-kvm-4.14.199-ab612c2.txt (stock config + KVM/VHOST +
           the field relocation; this is the current single kernel)

Result: all 124 reference entries are IDENTICAL. The only additions are
the two relocated KVM-only fields at their new tail offsets:

    offsetof(struct mm_struct, mmu_notifier_mm)   = 848  (== old sizeof)
    offsetof(struct task_struct, preempt_notifiers) = 2672

and the only deltas are their unavoidable consequences:

    offsetof(struct task_struct, thread)  2672 -> 2688  (thread_struct is
        the CPU-specific tail of task_struct, after everything vendor
        modules touch)
    sizeof(struct mm_struct)               848 ->  856  (size only)

=> vendor-module ABI preserved; KVM works on the same kernel.

