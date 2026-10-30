#!/usr/bin/env python3
"""Apply the measured RORS31.335-58-1 code delta to a kernel-sprd checkout.

`apply_shipping_header_delta.py` brings the seven headers of the shipping
build (firmware RORS31.335-58-1, built 2024-02-20) into the 2022-10 public
tree, but only the *declaration* half of two upstream changes.  Without the
matching definitions the tree does not build:

    mm/rmap.c        anon_vma->degree no longer exists (rmap.h now has
                     num_children/num_active_vmas)          -> 8 compile errors
    fs/file.c        no fget_many()
    fs/file_table.c  no fput_many()

Where the code comes from
-------------------------
The sibling vendor branch **R-11-release-RONS** (tag MMI-RONS31.267-94-14)
is the same 4.14.199 "Petit Gorille" Unisoc base and already carries this
exact pair of backports.  Its diff against R-11-release-RORS restricted to
these three files is nothing but the missing changes, so it is used verbatim
in `patches/kernel-sprd/0002-sprd-backport-rors31.335-58-1-mc-delta.patch`.

Two independent checks confirm RONS is the right source and not a lookalike:

  * `artifacts/System.map` (dumped from the phone) has
        ffffff8008415f5c T fput_many
        ffffff800843fbac T fget_many
    i.e. both are out-of-line global functions.  The static inline
    `fput_many()` of upstream 4.19 would not produce that symbol.
  * `include/linux/fs.h` already provides `get_file_rcu_many()` (patch 0001),
    so fs/file.c needs no further header work.

Build fixes (patches 0003, 0004)
--------------------------------
The tree does not compile as published; two directories are missing their own
include path:

  * with 0001+0002 applied the build stops on the vendor DDR-DFS tracepoint,
    because `sprd_dfs_trace.h` uses `TRACE_INCLUDE_PATH .` while
    `drivers/devfreq/sprd/Makefile` does not put its directory on the include
    path (patch 0003);
  * the next stop is `drivers/staging/sprd/sfp/sfp_tuple.c`, which includes
    `<sfp.h>` where every sibling uses `"sfp.h"` - the SFP driver *is* in the
    shipping kernel (102 `sfp_*` symbols in `artifacts/System.map`), so the
    Makefile is missing the flag (patch 0004).

Both are build-only: they add an include directory and do not alter the
objects produced.  No public branch carries either fix (checked RORS, RONS,
RON, rtas31.68-66-3, ula34, vuoa35).

A third one (patch 0005) only matters when `CONFIG_VHOST` is enabled, which
this build's KVM host options do but the phone does not - the shipped
`System.map` has no `vhost_*` symbols at all, so the vendor never compiled
`drivers/vhost/vhost.c` and the tree still has the pre-fix
`int ioctl` signature that newer clang rejects with `-Werror,-Wswitch`.
Patch 0005 makes it `unsigned int` (upstream form; also what the vendor's
android-14/15 trees use).  It is applied unconditionally and is harmless
when vhost is off.

Usage:
    apply_shipping_code_delta.py --tree D:\\AndroidSDKTools\\kernel-sprd
    apply_shipping_code_delta.py --tree ... --check     # dry run
"""
import argparse
import os
import subprocess
import sys

# (patch file, one-line description of what it touches)
PATCHES = [
    ("0002-sprd-backport-rors31.335-58-1-mc-delta.patch",
     "mm/rmap.c, fs/file.c, fs/file_table.c"),
    ("0003-sprd-build-fix-devfreq-trace-include.patch",
     "drivers/devfreq/sprd/Makefile"),
    ("0004-sprd-build-fix-sfp-include-path.patch",
     "drivers/staging/sprd/sfp/Makefile"),
    # Only has an effect when CONFIG_VHOST is enabled (this build's KVM host
    # options do; the phone does not - its System.map has no vhost symbols).
    ("0005-vhost-unsigned-ioctl-cmd.patch",
     "drivers/vhost/vhost.c, drivers/vhost/vhost.h"),
]


def repo_root():
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.dirname(os.path.dirname(here))


def git(tree, *args):
    return subprocess.run(["git", "-C", tree, *args],
                          capture_output=True, text=True)


def apply_one(tree, name, what, check_only, explicit_path):
    patch = explicit_path or os.path.join(repo_root(), "patches",
                                          "kernel-sprd", name)
    if not os.path.exists(patch):
        print(f"[!] patch not found: {patch}", file=sys.stderr)
        return 1

    # already applied?  (reverse check succeeds)
    rev = git(tree, "apply", "--reverse", "--check", patch)
    if rev.returncode == 0:
        print(f"[=] {name}: already applied")
        return 0

    chk = git(tree, "apply", "--check", patch)
    if chk.returncode != 0:
        print(f"[!] {name}: does not apply cleanly", file=sys.stderr)
        print(chk.stderr.rstrip(), file=sys.stderr)
        return 1

    if check_only:
        print(f"[=] {name}: would apply cleanly (dry run)")
        return 0

    res = git(tree, "apply", patch)
    if res.returncode != 0:
        print(f"[!] {name}: apply failed", file=sys.stderr)
        print(res.stderr.rstrip(), file=sys.stderr)
        return 1

    print(f"[+] {name}: applied")
    print(f"    {what}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True,
                    help="kernel-sprd checkout (e.g. D:\\AndroidSDKTools\\kernel-sprd)")
    ap.add_argument("--check", action="store_true",
                    help="only report, do not modify the tree")
    ap.add_argument("--patch", default=None,
                    help="override: apply only this single patch file")
    args = ap.parse_args()

    tree = os.path.abspath(args.tree)
    if not os.path.isdir(os.path.join(tree, ".git")) and not os.path.isfile(os.path.join(tree, ".git")):
        print(f"[!] {tree} is not a git checkout", file=sys.stderr)
        return 1

    if args.patch:
        return apply_one(tree, os.path.basename(args.patch),
                         "explicitly requested patch", args.check, args.patch)

    for name, what in PATCHES:
        rc = apply_one(tree, name, what, args.check, None)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
