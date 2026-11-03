#!/usr/bin/env python3
"""Print genksyms CRCs for objects built in a kernel build tree.

Usage: vps_crc_objects.py [--dir BUILD_DIR] obj [obj ...]
"""
import os
import re
import subprocess
import sys

args = sys.argv[1:]
build = os.path.expanduser("~/kernel-sprd")
if args and args[0] == "--dir":
    build = args[1]
    args = args[2:]
os.chdir(build)

want = {}
for path in args:
    cmd_file = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".cmd")
    if not os.path.exists(cmd_file):
        print("# no cmd file for", path)
        continue
    txt = open(cmd_file).read()
    m = re.search(r"^cmd_\S+ := (.*)$", txt, re.M)
    if not m:
        print("# no cmd line in", cmd_file)
        continue
    cmd = m.group(1).strip()
    # turn the compile into a preprocess
    cmd = re.sub(r"-c\s+-o\s+\S+", " -D__GENKSYMS__ -E ", cmd, count=1)
    if "-D__GENKSYMS__" not in cmd:
        cmd = re.sub(r"-c\s+-o\s+\S+", " -D__GENKSYMS__ -E ", cmd, count=1)
    full = "%s 2>/dev/null | scripts/genksyms/genksyms -r /dev/null" % cmd
    out = subprocess.run(["bash", "-c", full], capture_output=True, text=True).stdout
    n = 0
    for line in out.splitlines():
        line = line.strip()
        mm = re.match(r"__crc_([A-Za-z0-9_]+) = (0x[0-9a-f]+);", line)
        if mm:
            want[mm.group(1)] = int(mm.group(2), 16)
            n += 1
    print("# %s: %d crcs" % (path, n))

for name in sorted(want):
    print("%s 0x%08x" % (name, want[name]))
