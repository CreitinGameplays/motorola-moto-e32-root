#!/usr/bin/env python3
"""Prepare the staged-panic instrumentation in init/main.c (idempotent).

Adds include/linux/diag_stage.h and inserts DIAG_STAGE_N markers at eight
points along early boot, so a hang can be bisected with one incremental
rebuild per stage (only init/main.c recompiles).
"""
import pathlib
import sys

ROOT = pathlib.Path.home() / "kernel-sprd"

HEADER = """#ifndef _LINUX_DIAG_STAGE_H
#define _LINUX_DIAG_STAGE_H
/*
 * DIAG ONLY - not part of a real build.
 *
 * Set DIAG_PANIC_STAGE to N to panic as early as stage N during boot.  A panic
 * on this board reboots through PSCI (panic_timeout=5), which the bootloader
 * then retries until it falls back to fastboot - so "does it reset?" is a
 * yes/no answer to "did the kernel reach this point?".  Editing this one file
 * only recompiles init/main.c, so each bisection step costs a link, not a
 * full build.
 *
 *   1  first statement of start_kernel()      (does the Image execute?)
 *   2  after setup_arch()                     (DTB, memory map, PSCI)
 *   3  after build_all_zonelists/page_alloc   (early mm)
 *   4  after check_bugs()                     (late start_kernel)
 *   5  just before rest_init()                (start_kernel finished)
 *   6  first statement of kernel_init()
 *   7  after do_pre_smp_initcalls()
 *   8  after do_basic_setup()                 (every initcall, all drivers)
 *   0  disabled - normal boot
 */
#define DIAG_PANIC_STAGE %STAGE%

#if DIAG_PANIC_STAGE == 1
#define DIAG_STAGE_1 panic("DIAG: stage 1 - start_kernel entered")
#else
#define DIAG_STAGE_1 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 2
#define DIAG_STAGE_2 panic("DIAG: stage 2 - setup_arch returned")
#else
#define DIAG_STAGE_2 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 3
#define DIAG_STAGE_3 panic("DIAG: stage 3 - early mm up")
#else
#define DIAG_STAGE_3 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 4
#define DIAG_STAGE_4 panic("DIAG: stage 4 - start_kernel nearly done")
#else
#define DIAG_STAGE_4 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 5
#define DIAG_STAGE_5 panic("DIAG: stage 5 - about to rest_init")
#else
#define DIAG_STAGE_5 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 6
#define DIAG_STAGE_6 panic("DIAG: stage 6 - kernel_init entered")
#else
#define DIAG_STAGE_6 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 7
#define DIAG_STAGE_7 panic("DIAG: stage 7 - pre-smp initcalls done")
#else
#define DIAG_STAGE_7 do { } while (0)
#endif

#if DIAG_PANIC_STAGE == 8
#define DIAG_STAGE_8 panic("DIAG: stage 8 - all initcalls done")
#else
#define DIAG_STAGE_8 do { } while (0)
#endif

#endif /* _LINUX_DIAG_STAGE_H */
"""

# (anchor, text inserted after the anchor, marker that proves it is done)
EDITS = [
    ("#include <linux/diag_stage.h>", None, "#include <linux/diag_stage.h>"),
    ("asmlinkage __visible void __init start_kernel(void)\n{\n\tchar *command_line;\n\tchar *after_dashes;\n",
     "\tDIAG_STAGE_1;\n", "DIAG_STAGE_1;"),
    ("\tpr_notice(\"%s\", linux_banner);\n\tsetup_arch(&command_line);\n",
     "\tDIAG_STAGE_2;\n", "DIAG_STAGE_2;"),
    ("\tbuild_all_zonelists(NULL);\n\tpage_alloc_init();\n",
     "\tDIAG_STAGE_3;\n", "DIAG_STAGE_3;"),
    ("\tcheck_bugs();\n", "\tDIAG_STAGE_4;\n", "DIAG_STAGE_4;"),
    ("\t/* Do the rest non-__init'ed, we're now alive */\n\trest_init();\n",
     "\tDIAG_STAGE_5;\n", "DIAG_STAGE_5;"),
    ("static int __ref kernel_init(void *unused)\n{\n\tint ret;\n\n\tkernel_init_freeable();\n",
     "\tDIAG_STAGE_6;\n", "DIAG_STAGE_6;"),
    ("\tdo_pre_smp_initcalls();\n\tlockup_detector_init();\n",
     "\tDIAG_STAGE_7;\n", "DIAG_STAGE_7;"),
    ("\tdo_basic_setup();\n", "\tDIAG_STAGE_8;\n", "DIAG_STAGE_8;"),
]


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "0"
    src = ROOT / "init" / "main.c"
    hdr = ROOT / "include" / "linux" / "diag_stage.h"

    if not hdr.exists():
        hdr.write_text(HEADER.replace("%STAGE%", stage))
        print("created include/linux/diag_stage.h")

    s = src.read_text()

    # include the header once, just above start_kernel
    if "diag_stage.h" not in s:
        anchor = "asmlinkage __visible void __init start_kernel(void)"
        assert s.count(anchor) == 1
        s = s.replace(anchor, '#include <linux/diag_stage.h>\n\n' + anchor)
        print("added #include <linux/diag_stage.h>")

    for anchor, ins, marker in EDITS:
        if ins is None:
            continue
        if marker in s:
            continue
        n = s.count(anchor)
        if n != 1:
            print("WARN: anchor for %s occurs %d times, skipping" % (marker, n))
            continue
        s = s.replace(anchor, anchor + ins)
        print("inserted %s" % marker)

    # the end-of-init panic must not mask the staged ones
    if "#ifdef DIAG_PANIC_AFTER_INIT" in s:
        s = s.replace("#ifdef DIAG_PANIC_AFTER_INIT",
                      "#if defined(DIAG_PANIC_AFTER_INIT) && DIAG_PANIC_STAGE == 0")
        print("made DIAG_PANIC_AFTER_INIT yield to staged panics")

    src.write_text(s)

    # re-point the stage
    h = hdr.read_text()
    import re
    h = re.sub(r"#define DIAG_PANIC_STAGE \d+",
               "#define DIAG_PANIC_STAGE %s" % stage, h)
    hdr.write_text(h)
    print("DIAG_PANIC_STAGE = %s" % stage)


if __name__ == "__main__":
    main()