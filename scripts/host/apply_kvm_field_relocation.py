#!/usr/bin/env python3
"""Relocate the two KVM-only struct fields to the ends of their structs.

CONFIG_KVM selects CONFIG_PREEMPT_NOTIFIERS and CONFIG_MMU_NOTIFIER, which
add `preempt_notifiers` to `struct task_struct` (after sched_dl_entity) and
`mmu_notifier_mm` to `struct mm_struct` (after exe_file).  The CFI-built
vendor modules were compiled against a kernel without either, so those
insertions shift every following field by 8 bytes.  Moving the fields to
the struct tails keeps every vendor-visible offset identical; only the
struct sizes grow by 8, and both structs are kernel-allocated only.

See docs/17-vendor-module-rebuilds.md, section "2026-11-03 (2)".
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/kernel-sprd")

COMMENT = """\t/*
\t * KVM-only field, moved to the tail so every other field keeps the
\t * offset the CFI-built vendor modules were compiled with (docs/17,
\t * section "2026-11-03 (2)").  All kernel access is by name.
\t */
"""


def patch(path, old, new):
    p = os.path.join(root, path)
    s = open(p).read()
    if new in s and old not in s:
        print("already patched:", path)
        return
    if old not in s:
        raise SystemExit("pattern not found in %s:\n%s" % (path, old[:240]))
    open(p, "w").write(s.replace(old, new, 1))
    print("patched:", path)


# --- task_struct: move preempt_notifiers to just above the randstruct end
patch(
    "include/linux/sched.h",
    """\tstruct sched_dl_entity\t\tdl;

#ifdef CONFIG_PREEMPT_NOTIFIERS
\t/* List of struct preempt_notifier: */
\tstruct hlist_head\t\tpreempt_notifiers;
#endif
""",
    """\tstruct sched_dl_entity\t\tdl;
""",
)
patch(
    "include/linux/sched.h",
    """\t/*
\t * New fields for task_struct should be added above here, so that
\t * they are included in the randomized portion of task_struct.
\t */
\trandomized_struct_fields_end
""",
    COMMENT + """#ifdef CONFIG_PREEMPT_NOTIFIERS
\t/* List of struct preempt_notifier: */
\tstruct hlist_head\t\tpreempt_notifiers;
#endif

\t/*
\t * New fields for task_struct should be added above here, so that
\t * they are included in the randomized portion of task_struct.
\t */
\trandomized_struct_fields_end
""",
)

# --- mm_struct: move mmu_notifier_mm to just before the closing brace
patch(
    "include/linux/mm_types.h",
    """\t/* store ref to file /proc/<pid>/exe symlink points to */
\tstruct file __rcu *exe_file;
#ifdef CONFIG_MMU_NOTIFIER
\tstruct mmu_notifier_mm *mmu_notifier_mm;
#endif
""",
    """\t/* store ref to file /proc/<pid>/exe symlink points to */
\tstruct file __rcu *exe_file;
""",
)
patch(
    "include/linux/mm_types.h",
    """#ifdef CONFIG_PROTECT_LRU
\tint protect;
#endif
} __randomize_layout;
""",
    """#ifdef CONFIG_PROTECT_LRU
\tint protect;
#endif
""" + COMMENT + """#ifdef CONFIG_MMU_NOTIFIER
\tstruct mmu_notifier_mm *mmu_notifier_mm;
#endif
} __randomize_layout;
""",
)

print("ok")
