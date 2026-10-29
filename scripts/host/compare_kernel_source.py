#!/usr/bin/env python3
"""Compare the public Motorola/Unisoc kernel tree against the *running* kernel.

Inputs
------
--tree     checked-out kernel source (e.g. D:\\AndroidSDKTools\\kernel-sprd)
--kheaders extracted IKHEADERS tarball of the running kernel
           (artifacts/kheaders: include/ + arch/arm64/include/)
--config   /proc/config.gz of the running kernel (artifacts/kernel-config)
--out      optional markdown report path

What it proves
--------------
1. The Kconfig symbol universe of the running kernel (derived from the
   IKHEADERS include/config/<symbol>/ tree) contains every symbol used by the
   running .config -> the public tree must contain those Kconfig symbols too.
2. The *source* headers of the running kernel (include/... in the IKHEADERS
   tarball) are byte-identical to the ones in the public tree, or the exact
   list of deviations is printed.
3. The reconstructed build config (defconfig + release diffconfig fragments)
   matches the running .config value-for-value.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_config(path):
    """Parse a .config / defconfig into {symbol: value}; 'n' means not set."""
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            m = re.match(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2)
                continue
            m = re.match(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$", line)
            if m:
                out[m.group(1)] = "n"
    return out


def parse_diffconfig(path):
    """Parse a Unisoc/Motorola diffconfig fragment: DEL:/ADD: lines."""
    adds, dels = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DEL:"):
                dels.append(line[4:])
            elif line.startswith("ADD:"):
                adds.append(line[4:])
    return adds, dels


def kconfig_symbols_from_kheaders(kheaders):
    """Symbol universe of the exact build: dirs under include/config.

    Layout is include/config/<sym0>/<sym1>/... where the Kconfig symbol
    CONFIG_SYM0_SYM1 is written lower-case with '_' acting as the path
    separator (CONFIG_ARM64_PAN -> include/config/arm64/pan).
    """
    cfgdir = os.path.join(kheaders, "include", "config")
    syms = set()
    if not os.path.isdir(cfgdir):
        return syms
    stack = [("", cfgdir)]
    while stack:
        prefix, path = stack.pop()
        try:
            entries = os.listdir(path)
        except OSError:
            continue
        for e in entries:
            full = os.path.join(path, e)
            if not os.path.isdir(full):
                continue
            syms.add(prefix + e.lower())
            stack.append((prefix + e.lower() + "/", full))
    return syms


def config_symbol_to_path(symbol):
    """CONFIG_ARM64_PAN -> arm64/pan (the IKHEADERS include/config layout)."""
    assert symbol.startswith("CONFIG_")
    return symbol[len("CONFIG_"):].lower().replace("_", "/")


def git_case_variants(tree, relf):
    """All git paths that differ from relf only in case.

    Windows/NTFS is case-insensitive, but the kernel tree contains files
    like include/uapi/linux/netfilter/xt_CONNMARK.h *and* xt_connmark.h with
    different content - only one of them can exist in the worktree.  To
    compare fairly, the other case variant is read straight from git.
    """
    out = subprocess.run(
        ["git", "-C", tree, "ls-files", "--full-name", "--", "include/"],
        capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        return []
    key = ("include/" + relf).lower()
    return [p for p in out.stdout.splitlines()
            if p.lower() == key and p != "include/" + relf]


def git_show(tree, path):
    out = subprocess.run(["git", "-C", tree, "show", f"HEAD:{path}"],
                         capture_output=True)
    return out.stdout if out.returncode == 0 else None


def compare_headers(tree, kheaders):
    """Compare source headers (exclude generated trees)."""
    kincl = os.path.join(kheaders, "include")
    skip_prefixes = ("config", "generated")
    same, differ, only_kheaders, only_tree = [], [], [], []
    case_artifacts = []
    tree_files = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(tree, "include")):
        rel = os.path.relpath(dirpath, os.path.join(tree, "include"))
        if rel == ".":
            rel = ""
        parts = rel.split(os.sep) if rel else []
        if any(p in skip_prefixes for p in parts):
            continue
        for fn in filenames:
            relf = os.path.join(rel, fn).replace("\\", "/")
            tree_files.add(relf)
    kheaders_files = set()
    for dirpath, dirnames, filenames in os.walk(kincl):
        rel = os.path.relpath(dirpath, kincl)
        if rel == ".":
            rel = ""
        parts = rel.split(os.sep) if rel else []
        if any(p in skip_prefixes for p in parts):
            continue
        for fn in filenames:
            relf = os.path.join(rel, fn).replace("\\", "/")
            kheaders_files.add(relf)
    for relf in sorted(kheaders_files):
        kp = os.path.join(kincl, relf.replace("/", os.sep))
        tp = os.path.join(tree, "include", relf.replace("/", os.sep))
        if not os.path.exists(tp):
            only_kheaders.append(relf)
            continue
        if sha256(kp) == sha256(tp):
            same.append(relf)
        elif strip_comments(kp) == strip_comments(tp):
            # same code, only comments/whitespace differ (vendor strips
            # comments out of the IKHEADERS tarball)
            same.append(relf)
        else:
            # NTFS cannot hold both case variants of a file - check the
            # other variant straight out of the git object store
            hit = None
            for cand in git_case_variants(tree, relf):
                blob = git_show(tree, cand)
                if blob is None:
                    continue
                tmp = os.path.join(kheaders, "_gitcase.tmp")
                with open(tmp, "wb") as f:
                    f.write(blob)
                if strip_comments(tmp) == strip_comments(kp):
                    hit = cand
                os.remove(tmp)
                if hit:
                    break
            if hit:
                same.append(relf)
                case_artifacts.append(f"{relf} == {hit} (case collision)")
            else:
                differ.append(relf)
    for relf in sorted(tree_files - kheaders_files):
        only_tree.append(relf)
    return same, differ, only_kheaders, only_tree, case_artifacts


def normalize_text(path):
    """Read a file and normalize line endings (for CRLF/LF-insensitive diff)."""
    with open(path, "rb") as f:
        data = f.read()
    return data.replace(b"\r\n", b"\n")


COMMENT_RE = re.compile(rb"/\*.*?\*/", re.S)
LINE_COMMENT_RE = re.compile(rb"//[^\n]*")
WS_RE = re.compile(rb"\s+")


def strip_comments(path):
    """Normalize a C header: drop comments and collapse whitespace.

    The vendor's IKHEADERS tarball ships the headers with the comments
    stripped, so a raw byte comparison is meaningless; the code itself is
    what has to match.
    """
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    data = COMMENT_RE.sub(b"", data)
    data = LINE_COMMENT_RE.sub(b"", data)
    data = WS_RE.sub(b" ", data)
    return data.strip()


KCONFIG_SYM_RE = re.compile(r"^\s*(?:menu)?config\s+([A-Za-z0-9_]+)\s*$", re.M)


def tree_kconfig_symbols(tree):
    """All Kconfig symbols defined in the public tree."""
    syms = set()
    for dirpath, dirnames, filenames in os.walk(tree):
        dirnames[:] = [d for d in dirnames if d not in (".git",)]
        for fn in filenames:
            if not fn.startswith("Kconfig"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            for m in KCONFIG_SYM_RE.finditer(txt):
                syms.add("CONFIG_" + m.group(1))
    return syms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--kheaders", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--defconfig", action="append", default=[])
    ap.add_argument("--diffconfig", action="append", default=[])
    ap.add_argument("--out")
    args = ap.parse_args()

    report = []
    report.append("# Kernel source vs running kernel\n")

    # ---- 1. config reconstruction -------------------------------------
    cfg = parse_config(args.defconfig[0])
    for d in args.diffconfig:
        adds, dels = parse_diffconfig(d)
        for s in dels:
            cfg.pop(s, None)
        for s in adds:
            cfg[s] = "y"
    run = parse_config(args.config)
    conflicts = []
    for k, v in cfg.items():
        rv = run.get(k, "n")
        if rv != v:
            conflicts.append((k, v, rv))
    run_only = sorted(set(run) - set(cfg))
    report.append("## 1. Build config\n")
    report.append(f"- defconfig entries: {len(cfg)}")
    report.append(f"- running .config entries: {len(run)}")
    report.append(f"- value conflicts: {len(conflicts)}")
    for k, v, rv in sorted(conflicts):
        report.append(f"  - `{k}`: tree={v} device={rv}")
    report.append(f"- symbols only in the running .config: {len(run_only)}")
    for k in run_only:
        report.append(f"  - `{k}`={run[k]}")

    # ---- 2. Kconfig symbol universe ----------------------------------
    syms = kconfig_symbols_from_kheaders(args.kheaders)
    enabled = {s: v for s, v in run.items() if v in ("y", "m")}
    report.append("\n## 2. Kconfig symbols\n")
    report.append("### 2a. public tree Kconfig vs running .config\n")
    tree_syms = tree_kconfig_symbols(args.tree)
    undefined = sorted(s for s in run if s not in tree_syms)
    undef_enabled = [s for s in undefined if run[s] in ("y", "m")]
    report.append(f"- Kconfig symbols defined in the public tree: {len(tree_syms)}")
    report.append(f"- symbols used by the running kernel: {len(run)}")
    report.append(f"- running symbols NOT defined in the public tree: {len(undefined)}")
    report.append(f"  - of those, ENABLED in the running kernel: {len(undef_enabled)}")
    for s in undef_enabled:
        report.append(f"  - **`{s}`={run[s]}**")
    other = [s for s in undefined if s not in undef_enabled]
    for s in other:
        report.append(f"  - `{s}`={run[s]}")
    report.append("\n### 2b. IKHEADERS include/config symbol dirs\n")
    report.append(f"- symbol dirs in exact build: {len(syms)}")
    report.append(f"- enabled symbols in running .config: {len(enabled)}")
    not_in_kheaders = sorted(s for s in enabled
                             if config_symbol_to_path(s) not in syms)
    report.append(f"- enabled symbols without a generated header dir: {len(not_in_kheaders)}")
    report.append("  (expected: bool symbols without CONFIG_ headers are not listed)")

    # ---- 3. header comparison ----------------------------------------
    same, differ, only_kheaders, only_tree, case_artifacts = compare_headers(
        args.tree, args.kheaders)
    report.append("\n## 3. Source headers (tree include/ vs IKHEADERS include/)\n")
    report.append(f"- identical (code, comments/whitespace normalised): {len(same)}")
    report.append(f"- different content: {len(differ)}")
    report.append(f"- only in exact build: {len(only_kheaders)}")
    report.append(f"- only in public tree: {len(only_tree)}")
    for f in differ:
        report.append(f"  - DIFF `{f}`")
    for f in only_kheaders:
        report.append(f"  - BUILD-ONLY `{f}`")
    for f in only_tree:
        report.append(f"  - TREE-ONLY `{f}`")
    if case_artifacts:
        report.append(f"- case-collision artifacts (identical via git): {len(case_artifacts)}")
        for f in case_artifacts:
            report.append(f"  - CASE `{f}`")

    text = "\n".join(report) + "\n"
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[+] report written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
