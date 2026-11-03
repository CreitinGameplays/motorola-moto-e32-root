#!/usr/bin/env python3
"""Patch a 4.14 sprd kernel tree so that *vendor* (CFI-built) modules load.

Three ABI facts drive this (see docs/17-vendor-module-rebuilds.md):
  * the vendor modules were built with CONFIG_CFI_CLANG=y, so their
    `struct module` carries the `cfi_check` field at 0x150 and their
    init/cleanup relocations sit at 0x158 / 0x310;
  * the one CRC that differs between a CFI-off rebuild and those modules is
    the exported `module_layout` helper (0x36aac43d vs 0xec8a4bdb);
  * CFI-built modules import `__cfi_slowpath`, which a CFI-off kernel does
    not provide.

So:
  1. make `cfi_check_fn` and `struct module::cfi_check` unconditional, which
     reproduces the vendor `struct module` layout;
  2. make check_modstruct_version() accept the module_layout CRC mismatch
     (all other symbol CRCs still verified);
  3. export a no-op `__cfi_slowpath()` with the same prototype as kernel/cfi.c
     so its genksyms CRC matches the vendor expectation.

Usage: python3 apply_vendor_module_compat.py /path/to/kernel-tree
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/kernel-sprd")


def patch(path, old, new, count=1):
    p = os.path.join(root, path)
    s = open(p).read()
    if new in s and old not in s:
        print("already patched:", path)
        return False
    if old not in s:
        raise SystemExit("pattern not found in %s:\n%s" % (path, old))
    s = s.replace(old, new, count)
    open(p, "w").write(s)
    print("patched:", path)
    return True


# 1a. cfi.h: the typedef must exist even when CONFIG_CFI_CLANG is off.
patch(
    "include/linux/cfi.h",
    """#ifdef CONFIG_CFI_CLANG
#ifdef CONFIG_MODULES

typedef void (*cfi_check_fn)(uint64_t, void *, void *);
""",
    """typedef void (*cfi_check_fn)(uint64_t, void *, void *);

#ifdef CONFIG_CFI_CLANG
#ifdef CONFIG_MODULES
""",
)

# 1b. module.h: keep the field unconditionally -> vendor struct module layout.
patch(
    "include/linux/module.h",
    """#ifdef CONFIG_CFI_CLANG
\tcfi_check_fn cfi_check;
#endif""",
    """\t/* Kept unconditional: vendor modules were built with CFI on, so this
\t * field must exist to match their struct module layout. */
\tcfi_check_fn cfi_check;""",
)

# 2. accept the single module_layout CRC difference.
patch(
    "kernel/module.c",
    """\tpreempt_enable();
\treturn check_version(info, VMLINUX_SYMBOL_STR(module_layout),
\t\t\t     mod, crc);
}""",
    """\tpreempt_enable();
\t/*
\t * The vendor modules were built with CFI on, so their module_layout
\t * CRC differs from this CFI-off rebuild even though the struct module
\t * layout is identical (cfi_check is kept unconditionally).  Every
\t * other imported symbol is still CRC-checked by check_version().
\t */
\tpr_info_once("module: skipping module_layout CRC check (vendor CFI build)\\n");
\treturn 1;
}""",
)

# 3. provide __cfi_slowpath for CFI-built modules.
p = os.path.join(root, "kernel/module.c")
s = open(p).read()
marker = "EXPORT_SYMBOL(module_layout);"
stub = """EXPORT_SYMBOL(module_layout);

#ifndef CONFIG_CFI_CLANG
/*
 * Vendor modules were built with clang CFI, so they call this runtime
 * helper.  A CFI-off kernel does not build kernel/cfi.c; provide the same
 * prototype so both the symbol lookup and the genksyms CRC match.
 */
void __cfi_slowpath(uint64_t id, void *ptr, void *diag)
{
}
EXPORT_SYMBOL(__cfi_slowpath);
#endif
"""
if "__cfi_slowpath" not in s:
    if marker not in s:
        raise SystemExit("module_layout export not found")
    s = s.replace(marker, stub, 1)
    open(p, "w").write(s)
    print("patched: kernel/module.c (__cfi_slowpath stub)")
else:
    print("already patched: __cfi_slowpath stub")

# re-run safety: verify the field is now unconditional
mh = open(os.path.join(root, "include/linux/module.h")).read()
assert "\tcfi_check_fn cfi_check;" in mh
print("ok")
