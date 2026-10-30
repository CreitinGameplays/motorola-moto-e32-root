import pathlib, re

p = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloop-stock\uboot_log.img")
d = p.read_bytes()

# records look like "[00020620] text"
recs = []
for m in re.finditer(rb"\[(\d{8})\]\s([^\x00\r\n]*)", d):
    recs.append((int(m.group(1)), m.group(2).decode("latin-1")))

print("records:", len(recs))
# find the last boot sequences
idx = [i for i, (_, t) in enumerate(recs) if "Booting slot" in t]
print("Booting slot records:", len(idx))
for i in idx[-12:]:
    print("  at", i, "ts", recs[i][0], recs[i][1])

print("\n=== last 120 records from the last 'Booting slot' onward ===")
start = idx[-1] if idx else max(0, len(recs) - 120)
for ts, t in recs[start:start + 160]:
    print("[%08d] %s" % (ts, t))

print("\n=== any avb/dump/reset/watchdog lines, last 40 ===")
pat = re.compile(r"avb|AVB|dump|wdt|WDT|reset_mode|boot_fail|boot_success|panic", re.I)
hits = [r for r in recs if pat.search(r[1])]
for ts, t in hits[-40:]:
    print("[%08d] %s" % (ts, t))