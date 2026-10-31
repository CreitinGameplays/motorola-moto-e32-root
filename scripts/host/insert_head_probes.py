#!/usr/bin/env python3
"""Insert MMU-off paint probes into stext, on the VPS kernel tree.

stext runs with the MMU off, so a plain store to the bootloader's framebuffer
(physical 0x9e000000) is a valid probe there - no page tables, no mapping.
Each probe paints its own 128 KB band, so one boot tells us which of

    preserce_boot_args -> el2_setup -> set_cpu_boot_mode_flag ->
    __create_page_tables -> __cpu_setup -> __primary_switch (MMU on)

completed.  Bands are chosen above the ones the C trace already uses (1..19):

    22  after bl el2_setup
    23  after bl __create_page_tables
    24  after bl __cpu_setup

Idempotent: a probe already present is left alone.

Usage: python3 insert_head_probes.py
"""
import pathlib
import re

ROOT = pathlib.Path.home() / "kernel-sprd"
HEAD = ROOT / "arch" / "arm64" / "kernel" / "head.S"

MACRO = r"""
#if defined(DIAG_EARLY_PAINT)
/*
 * DIAG: paint band \band through a *physical* store.  Only valid while the
 * MMU is off, which is exactly where these probes sit (stext).  Clobbers
 * x9/x10/x11, which the boot path does not use before start_kernel().
 */
\t.macro\tdiag_probe, band
\tmovz\tx10, #(((0x9e000000 + (\band) * 0x20000) >> 16) & 0xffff), lsl #16
\tmovk\tx10, #((0x9e000000 + (\band) * 0x20000) & 0xffff)
\tmovn\tx9, #0
\tmovz\tx11, #8192
9991:\tstp\tx9, x9, [x10], #16
\tsubs\tx11, x11, #1
\tb.ne\t9991b
\t.endm
#else
\t.macro\tdiag_probe, band
\t.endm
#endif
"""

PROBES = [
    ("\tbl\tel2_setup\t\t\t// Drop to EL1, w0=cpu_boot_mode\n", 22),
    ("\tbl\t__create_page_tables\n", 23),
    ("\tbl\t__cpu_setup\t\t\t// initialise processor\n", 24),
]


def main():
    s = HEAD.read_text()
    if "diag_probe" not in s:
        anchor = "ENTRY(stext)\n"
        assert s.count(anchor) == 1
        s = s.replace(anchor, MACRO.replace("\\t", "\t").replace("\\band", "\\band")
                      + "\n" + anchor, 1)
        print("inserted diag_probe macro")
    for anchor, band in PROBES:
        hook = "\tdiag_probe %d\n" % band
        if hook in s:
            continue
        if s.count(anchor) != 1:
            print("WARN: anchor %r occurs %d times" % (anchor, s.count(anchor)))
            continue
        s = s.replace(anchor, anchor + hook, 1)
        print("inserted %s" % hook.strip())
    HEAD.write_text(s)


if __name__ == "__main__":
    main()