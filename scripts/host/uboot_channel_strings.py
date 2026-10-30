import pathlib
import re

p = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloader\bl\uboot_b.img")
d = p.read_bytes()
print("file", len(d), "bytes")

pats = {
    "download-mode entry": rb"download|FDL|fdl_|dl_cmd|dl_secure|dl_",
    "reboot variants": rb"reboot[-_a-z]*",
    "fastboot cmds": rb"fastboot|bootloader|flash:|erase:|oem",
    "boot/jump": rb"bootm|booti|bootz|\bgo\b|do_boot|run_command|setenv",
    "usb gadget": rb"udc|gadget|dwc3|configfs",
    "uart/console": rb"console=|ttyS|uart|serial",
}

for label, pat in pats.items():
    hits = []
    for m in re.finditer(rb"[ -~]{4,}", d):
        s = m.group()
        if re.search(pat, s, re.I):
            hits.append((m.start(), s.decode("latin-1")))
    # de-duplicate strings, keep first offset
    seen = {}
    for off, s in hits:
        if s not in seen:
            seen[s] = off
    print("\n=== %s === (%d unique)" % (label, len(seen)))
    for s, off in sorted(seen.items(), key=lambda kv: kv[1])[:60]:
        print("  %08x  %s" % (off, s[:110]))