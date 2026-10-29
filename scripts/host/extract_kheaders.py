#!/usr/bin/env python3
"""Extract the IKHEADERS tarball of the running kernel (Windows-safe).

The kernel exposes /sys/kernel/kheaders.tar.xz when the vendor's
kheaders.ko module is loaded.  The tarball contains the *exact* headers,
generated config headers and arch headers of the running kernel.

Windows cannot create files whose name is a reserved device name
(aux.h, con.c, ...), so those members are skipped instead of aborting the
extraction.

Usage: extract_kheaders.py <kheaders.tar.xz> <outdir>
"""
import os
import re
import sys
import tarfile

RESERVED = re.compile(r"^(aux|con|prn|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    tarpath, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    root = os.path.abspath(outdir)
    n = skipped = 0
    with tarfile.open(tarpath, "r:xz") as t:
        for m in t:
            if not m.isfile():
                continue
            parts = [p for p in m.name.replace("\\", "/").split("/")
                     if p and p != "."]
            if any(RESERVED.match(p) for p in parts):
                skipped += 1
                continue
            dest = os.path.join(root, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(t.extractfile(m).read())
            n += 1
    print(f"[+] extracted {n} files, skipped {skipped} (reserved names)")
    for probe in ("include/generated/autoconf.h", "include/config",
                  "arch/arm64/include/generated"):
        print(f"    {probe}: {os.path.exists(os.path.join(root, probe))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
