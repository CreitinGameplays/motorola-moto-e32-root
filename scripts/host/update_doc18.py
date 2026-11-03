#!/usr/bin/env python3
"""Update docs/18: vendor-module/KVM status, LOCALVERSION, module names."""
import io, sys

p = 'docs/18-kernel-build-flash-howto.md'
s = io.open(p, encoding='utf-8').read()
BS = chr(92)


def rep(old, new, what):
    global s
    if new in s and old not in s:
        print('already:', what)
        return
    if old not in s:
        raise SystemExit('NOT FOUND: ' + what)
    s = s.replace(old, new, 1)
    print('ok:', what)


# 1. section 2 pointer
rep(
    "The working config (non-LTO, `MALI_MIDGARD=m`, qogirl6 platform, WCN bus\n"
    "built-in, AON watchdog diagnostics) is committed as\n"
    "`patches/kernel-sprd/branch-hawaii-diag/phone.config` in the analysis repo.",
    "Two config routes exist:\n\n"
    "* **Daily kernel (recommended)** - the *stock-config* build of section 8b\n"
    "  (+ KVM per section 9).  It is the one that loads the vendor modules and\n"
    "  is what currently runs on the phone.\n"
    "* **Older custom config** (non-LTO, `MALI_MDBG_CRUMB` diagnostics, ...)\n"
    "  committed as `patches/kernel-sprd/branch-hawaii-diag/phone.config` in\n"
    "  the analysis repo - the diag-series route; it does NOT load the vendor\n"
    "  modules (CRC mismatch) and is kept for the probe/diag workflows.",
    "section 2 config pointer",
)

# 2. section 3 build command + outputs
old3 = (
    "```bash\n"
    "make -j$(nproc) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- " + BS + "\n"
    '    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld ' + BS + "\n"
    '    LLVM_AR=llvm-ar LLVM_NM=llvm-nm KCFLAGS="" Image modules\n'
    "```\n"
    "\n"
    "Outputs that matter:\n"
    "\n"
    "* `arch/arm64/boot/Image` - the kernel\n"
    "* `drivers/gpu/arm/midgard/mali_kbase.ko` - the GPU driver\n"
    "* `drivers/net/wireless/sprd_wlan/sprd_wlan_combo.ko` - the SC2355 WiFi driver\n"
    "* `fs/incfs/incrementalfs.ko` - for Android's incremental installs"
)
new3 = (
    "```bash\n"
    "make -j$(nproc) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- " + BS + "\n"
    '    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld ' + BS + "\n"
    '    LLVM_AR=llvm-ar LLVM_NM=llvm-nm KCFLAGS="" ' + BS + "\n"
    "    LOCALVERSION=+-ab612c2 Image modules\n"
    "```\n"
    "\n"
    "`LOCALVERSION=+-ab612c2` makes `UTS_RELEASE` byte-match the shipping\n"
    "kernel (`4.14.199+-ab612c2`), which the vendor modules' vermagic check\n"
    "requires - omit it and every `insmod` fails with a version-magic error.\n"
    "The CFI-ABI compat patches (section 8b) must be in the tree; the\n"
    "published branch already carries them.\n"
    "\n"
    "Outputs that matter:\n"
    "\n"
    "* `arch/arm64/boot/Image` - the kernel\n"
    "* `drivers/gpu/arm/midgard/mali_kbase.ko` - the GPU driver (staged via\n"
    "  the Magisk module)\n"
    "* `drivers/net/wireless/sprd_wlan/sprdwl_ng.ko` - the SC2355 WiFi driver\n"
    "  (the module must keep this exact name; the WiFi HAL gates on a\n"
    "  `/proc/modules` line starting with `sprdwl_ng`)\n"
    "* the vendor modules (camera/BT/FM/SAR, and `incrementalfs`) are loaded\n"
    "  by the vendor rc files themselves - nothing to stage"
)
rep(old3, new3, "section 3 build + outputs")

# 3. section 6 note
rep(
    "`/data/local/tmp/<id>_module_load.log`.",
    "`/data/local/tmp/<id>_module_load.log`.\n\n"
    "The `.ko` files must come from the **same kernel build** as the flashed\n"
    "Image (same vermagic `4.14.199+-ab612c2`, same `module_layout` CRC) -\n"
    "after every kernel rebuild, re-run both install scripts with the fresh\n"
    "`.ko` files before rebooting into it.  The vendor modules need no\n"
    "staging: `camera.rc` / `wcn.rc` insmod them from `/mnt/vendor/socko/`\n"
    "on every boot.",
    "section 6 same-build note",
)

# 4. section 7 expected failures
rep(
    "And two *expected* failures from the vendor's own rc files (their\n"
    "prebuilt modules cannot load against our kernel - `module_layout` CRC\n"
    "mismatch): `init.md.rc`'s `insmod .../socko/mali_kbase.ko` and\n"
    "`wcn.rc`/`camera.rc`'s insmods. Harmless: our in-tree replacements load\n"
    "later at post-fs-data.",
    "On the stock-config build the vendor rc insmods *succeed*, so the only\n"
    "expected log noise is:\n"
    "\n"
    "* `wcn.rc` trying to insmod the non-existent `socko/sprdbt_tty.ko` (the\n"
    "  real file is `sprdbt_sdio_tty.ko` - a vendor rc typo, harmless), and\n"
    "* our own post-fs-data insmod of `mali_kbase`/`sprdwl_ng` failing with\n"
    "  \"File exists\" if the vendor rc loaded its copy first (one driver per\n"
    "  name; either copy works on this kernel).\n"
    "\n"
    "On the older `phone.config` diag build those vendor insmods fail with a\n"
    "`module_layout` CRC mismatch instead - also harmless there, our in-tree\n"
    "replacements load later.",
    "section 7 expected failures",
)

# 5. section 8 KVM status
rep(
    "is loaded by the vendor rc itself.  The KVM kernel (section 9) remains a\n"
    "separate build until the task_struct/mm_struct field relocation\n"
    "(docs 17 \"2026-11-03 (2)\") is implemented and verified.",
    "is loaded by the vendor rc itself.  KVM is in the same build too (see\n"
    "section 9): the task_struct/mm_struct field relocation\n"
    "(docs 17 \"2026-11-03 (2)\") is implemented and device-verified with the\n"
    "`modules/abiprobe` offsets check.",
    "section 8 KVM status",
)

# 6. section 8b KVM note
rep(
    "* **Do not enable KVM in this config** - it selects `MMU_NOTIFIER` and\n"
    "  `PREEMPT_NOTIFIERS`, which change `struct mm_struct` / `struct\n"
    "  task_struct` and break the vendor modules.  The KVM kernel is a separate\n"
    "  build.",
    "* **KVM can be added to this config only together with the field\n"
    "  relocation**: KVM selects `MMU_NOTIFIER`/`PREEMPT_NOTIFIERS`, which\n"
    "  change `struct mm_struct` / `struct task_struct`.  With\n"
    "  `scripts/host/apply_kvm_field_relocation.py` applied (published\n"
    "  branch: yes) the two fields sit at the struct tails and the vendor\n"
    "  ABI is preserved - verified with `modules/abiprobe`\n"
    "  (docs/evidence/abiprobe/README.md).  Without the relocation, do not\n"
    "  enable KVM.",
    "section 8b KVM note",
)

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('done')
