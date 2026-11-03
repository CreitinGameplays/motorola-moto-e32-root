#!/usr/bin/env python3
"""Run genksyms manually on kernel/module.c to get module_layout CRC.

Reads the kbuild recorded command from kernel/.module.o.cmd, turns the
compile into a preprocess (-E -D__GENKSYMS__), pipes through genksyms and
prints the CRC of module_layout (plus a few neighbours).
"""
import re
import subprocess
import sys
import os

os.chdir(os.path.expanduser("~/kernel-sprd"))

cmd_path = "kernel/.module.o.cmd"
if not os.path.exists(cmd_path):
    sys.exit("missing %s - build kernel/module.o first" % cmd_path)

txt = open(cmd_path).read()
m = re.search(r"^cmd_kernel/module\.o := (.*)$", txt, re.M)
if not m:
    sys.exit("no cmd_kernel/module.o line")
cmd = m.group(1).strip()

# clang -Wp,-MD,... -c -o kernel/.tmp_module.o kernel/module.c
cmd = cmd.replace("-c -o kernel/.tmp_module.o", " -D__GENKSYMS__ -E ")
if "-D__GENKSYMS__" not in cmd:
    # fallback: generic removal of the -c/-o pair
    cmd = re.sub(r"-c\s+-o\s+\S+", "-D__GENKSYMS__ -E", cmd, count=1)

gensym = "scripts/genksyms/genksyms -r /dev/null"
full = "%s 2>/dev/null | %s" % (cmd, gensym)
print("RUN:", full[:200], "...")
out = subprocess.run(["bash", "-c", full], capture_output=True, text=True)
res = out.stdout
if not res.strip():
    sys.exit("genksyms produced nothing; stderr of pipeline unavailable")

want = ("module_layout", "module_mutex", "try_module_get", "__module_get",
        "module_put", "find_module", "each_symbol_section")
for line in res.splitlines():
    line = line.strip()
    for w in want:
        if line.startswith("__crc_%s " % w):
            print(line)
print("--- total crc lines:", sum(1 for l in res.splitlines() if l.startswith("__crc_")))
