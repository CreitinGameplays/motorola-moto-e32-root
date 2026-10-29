#!/usr/bin/env python3
"""Apply the measured RORS31.335-58-1 header delta to a kernel-sprd checkout.

The public Motorola/Unisoc tree (branch R-11-release-RORS, 2022-10-25) is
missing exactly 7 headers' worth of changes that the shipping kernel of
firmware RORS31.335-58-1 (built 2024-02-20) contains.  The delta was
measured by comparing the public tree against the IKHEADERS tarball of the
*running* kernel (comments/whitespace normalised, because the vendor strips
comments out of that tarball).

Provenance of every hunk
------------------------
include/linux/file.h   upstream stable: "fs: add fget_many() and fput_many()"
                       (Jens Axboe; present in linux-4.19.y / linux-5.10.y,
                       removed upstream again in 6.2)
include/linux/fs.h     same series (get_file_rcu_many)
include/linux/rmap.h   upstream "mm: change anon_vma degree to num_children"
                       (Jee Won, v6.9, backported to stable) - Unisoc moved the
                       two counters behind rb_root
include/linux/sipc.h   Unisoc specific: hardened unalign_copy_from_user()
                       using sbuf_copy_from_user()
include/uapi/video/*   Unisoc specific (JPG/VSP map sizes, sensor ioctls)

Usage:
    apply_shipping_header_delta.py --tree D:\\AndroidSDKTools\\kernel-sprd
    apply_shipping_header_delta.py --tree ... --check     # dry run
"""
import argparse
import os
import sys

# (file, [(old, new, expected_count), ...])
DELTA = [
    (
        "include/linux/file.h",
        [
            (
                "extern void fput(struct file *);\n",
                "extern void fput(struct file *);\n"
                "extern void fput_many(struct file *, unsigned int);\n",
                1,
            ),
            (
                "extern struct file *fget(unsigned int fd);\n",
                "extern struct file *fget(unsigned int fd);\n"
                "extern struct file *fget_many(unsigned int fd, unsigned int refs);\n",
                1,
            ),
        ],
    ),
    (
        "include/linux/fs.h",
        [
            (
                "#define get_file_rcu(x) atomic_long_inc_not_zero(&(x)->f_count)\n",
                "#define get_file_rcu_many(x, cnt)\t\\\n"
                "\tatomic_long_add_unless(&(x)->f_count, (cnt), 0)\n"
                "#define get_file_rcu(x) get_file_rcu_many((x), 1)\n",
                1,
            ),
        ],
    ),
    (
        "include/linux/rmap.h",
        [
            (
                "\t/*\n"
                "\t * Count of child anon_vmas and VMAs which points to this anon_vma.\n"
                "\t *\n"
                "\t * This counter is used for making decision about reusing anon_vma\n"
                "\t * instead of forking new one. See comments in function anon_vma_clone.\n"
                "\t */\n"
                "\tunsigned degree;\n",
                "",
                1,
            ),
            (
                "\tstruct rb_root_cached rb_root;\n",
                "\tstruct rb_root_cached rb_root;\n"
                "\n"
                "\t/*\n"
                "\t * Count of child anon_vmas and VMAs which points to this anon_vma.\n"
                "\t *\n"
                "\t * This counter is used for making decision about reusing anon_vma\n"
                "\t * instead of forking new one. See comments in function anon_vma_clone.\n"
                "\t */\n"
                "\tunsigned long num_children;\n"
                "\t/* Count of VMAs whose ->anon_vma pointer points to this object. */\n"
                "\tunsigned long num_active_vmas;\n",
                1,
            ),
        ],
    ),
    (
        "include/linux/sipc.h",
        [
            (
                "#endif /* CONFIG_SPRD_SIPC_ZERO_COPY_SIPX */\n"
                "\n"
                "#ifdef CONFIG_ARM64\n",
                "#endif /* CONFIG_SPRD_SIPC_ZERO_COPY_SIPX */\n"
                "\n"
                "/*\n"
                " * Unisoc: hardened copy_from_user() for the shared memory buffers.\n"
                " * The generic copy_from_user() may zero the tail of a partially\n"
                " * copied buffer, which would corrupt the shared memory block.\n"
                " */\n"
                "static inline unsigned long sbuf_copy_from_user(void *to,\n"
                "\t\tconst void __user *from, unsigned long n)\n"
                "{\n"
                "\tunsigned long res = n;\n"
                "\tmight_fault();\n"
                "\tif (likely(check_copy_size(to, n, false))) {\n"
                "\t\tkasan_check_write(to, n);\n"
                "\t\tres = raw_copy_from_user(to, from, n);\n"
                "\t}\n"
                "\treturn res;\n"
                "}\n"
                "\n"
                "#ifdef CONFIG_ARM64\n",
                1,
            ),
            (
                "\t\treturn copy_from_user(to, from, n);",
                "\t\treturn sbuf_copy_from_user(to, from, n);",
                3,
            ),
            (
                "\t\tif (copy_from_user(to++, from++, 1))",
                "\t\tif (sbuf_copy_from_user(to++, from++, 1))",
                1,
            ),
            (
                "\treturn copy_from_user(to, from, n);\n"
                "}\n"
                "static inline void *unalign_memcpy(void *to, const void *from, size_t n)\n",
                "\treturn sbuf_copy_from_user(to, from, n);\n"
                "}\n"
                "static inline void *unalign_memcpy(void *to, const void *from, size_t n)\n",
                1,
            ),
        ],
    ),
    (
        "include/uapi/video/sprd_jpg.h",
        [
            (
                "#define SPRD_JPG_IOCTL_MAGIC 'm'\n",
                "#define SPRD_JPG_MAP_SIZE 0x6000\n"
                "#define SPRD_JPG_IOCTL_MAGIC 'm'\n",
                1,
            ),
        ],
    ),
    (
        "include/uapi/video/sprd_vsp.h",
        [
            (
                "#define SPRD_VSP_MAP_SIZE 0xA000\n",
                "#define SPRD_VSP_MAP_SIZE 0x14000\n",
                1,
            ),
        ],
    ),
    (
        "include/uapi/video/sprd_sensor_k.h",
        [
            (
                "#define SENSOR_IOC_MAGIC\t\t\t'R'\n",
                "#define SENSOR_IOC_MAGIC\t\t\t'R'\n"
                "#define SENSOR_IOC_PRIVATE_KEY\t\t0x789A\n",
                1,
            ),
            (
                "#define SENSOR_IO_READ_OTPDATA\t\\\n",
                "#define SENSOR_IO_PRI_KEY\t\\\n"
                "\t_IOW(SENSOR_IOC_MAGIC, \t25, uint32_t)\n"
                "#define SENSOR_IO_READ_OTPDATA\t\\\n",
                1,
            ),
        ],
    ),
]


def apply_file(path, edits, write=True):
    """Apply the edits of one file; returns (changed, message)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    orig = text
    for old, new, count in edits:
        found = text.count(old)
        if found == 0 and new.strip() and new in text:
            continue                      # already applied
        if found != count:
            return False, (f"{path}: expected {count} occurrence(s) of "
                           f"{old.strip()[:48]!r}, found {found}")
        text = text.replace(old, new)
    changed = text != orig
    if changed and write:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return changed, (f"{path}: {'patched' if changed else 'already up to date'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True,
                    help="kernel-sprd checkout (e.g. D:\\AndroidSDKTools\\kernel-sprd)")
    ap.add_argument("--check", action="store_true",
                    help="only report, do not modify the tree")
    args = ap.parse_args()

    rc = 0
    for rel, edits in DELTA:
        path = os.path.join(args.tree, rel.replace("/", os.sep))
        if not os.path.exists(path):
            print(f"[!] missing {rel}")
            rc = 1
            continue
        ok, msg = apply_file(path, edits, write=not args.check)
        print(f"[{'=' if ok else '!'}] {msg}")
        if not ok:
            rc = 1
    if rc:
        print("\n[!] delta not fully applicable", file=sys.stderr)
    else:
        print("\n[+] shipping header delta fully applied"
              + (" (dry run)" if args.check else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
