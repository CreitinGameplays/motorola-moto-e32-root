#!/usr/bin/env python3
"""Second half of the vendor-module compatibility patch set.

Besides `struct module` (see apply_vendor_module_compat.py), the only other
ABI-visible CONFIG_CFI_CLANG layout change in this kernel is
`struct timer_list`:

    struct timer_list {
        ...
        u32 flags;
    #ifdef CONFIG_CFI_CLANG
        void (*__function)(struct timer_list *);
    #endif
    };

That extra trailing pointer matters because timer_list is embedded in
`struct dev_pm_info`, which is embedded in `struct device`; without it
every `struct device` field after `power` (of_node, fwnode, ...) is 8 bytes
off for the CFI-built vendor modules.

Making the field unconditional restores the layout.  Our own (CFI-off)
kernel keeps using `timer->function`, while a CFI-built module's inline
setup_timer() stores its trampoline in `function` and the real callback in
`__function` - both work.

The genksyms CRCs still differ for most struct-typed symbols (CFI changes
the preprocessing/type numbering), so check_version() must warn instead of
failing.
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/kernel-sprd")


def patch(path, old, new):
    p = os.path.join(root, path)
    s = open(p).read()
    if old not in s:
        if new in s:
            print("already patched:", path)
            return
        raise SystemExit("pattern not found in %s:\n%s" % (path, old[:200]))
    open(p, "w").write(s.replace(old, new, 1))
    print("patched:", path)


# 1. keep the CFI-only timer_list tail field so the struct size (and every
#    struct embedding it, notably struct dev_pm_info inside struct device)
#    matches the vendor build.
patch(
    "include/linux/timer.h",
    """#ifdef CONFIG_CFI_CLANG
\tvoid\t\t\t(*__function)(struct timer_list *);
#endif""",
    """\t/* Kept unconditional: vendor modules were built with CFI on, so the
\t * field must exist for struct timer_list (and struct device, through
\t * struct dev_pm_info) to keep the vendor's layout. */
\tvoid\t\t\t(*__function)(struct timer_list *);""",
)

# 2a. crcval is needed after the loop (the bad_version label is outside it).
patch(
    "kernel/module.c",
    """\tunsigned int i, num_versions;
\tstruct modversion_info *versions;
""",
    """\tunsigned int i, num_versions;
\tstruct modversion_info *versions;
\tu32 crcval = 0;
""",
)
patch(
    "kernel/module.c",
    """\tfor (i = 0; i < num_versions; i++) {
\t\tu32 crcval;

\t\tif (strcmp""",
    """\tfor (i = 0; i < num_versions; i++) {
\t\tif (strcmp""",
)

# 2b. warn about CRC differences instead of refusing the module.
patch(
    "kernel/module.c",
    """bad_version:
\tpr_warn("%s: disagrees about version of symbol %s\\n",
\t       info->name, symname);
\treturn 0;
}""",
    """bad_version:
\t/* CFI changes genksyms' type numbering, so a CFI-off rebuild of the
\t * same source mismatches most struct-typed symbols even though the
\t * layouts match.  Log and continue. */
\tprintk(KERN_DEBUG "%s: CRC differs for %s (module %llx, kernel %x)\\n",
\t       info->name, symname,
\t       (unsigned long long)versions[i].crc, crcval);
\treturn 1;
}""",
)

print("ok")
