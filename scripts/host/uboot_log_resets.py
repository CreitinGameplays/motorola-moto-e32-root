import pathlib, re

p = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloop-stock\uboot_log3.img")
d = p.read_bytes()
recs = [(int(m.group(1)), m.group(2).decode("latin-1"))
        for m in re.finditer(rb"\[(\d{8})\]\s([^\x00\r\n]*)", d)]
print("records:", len(recs))

boots = [(i, ts, t) for i, (ts, t) in enumerate(recs) if "Booting slot" in t]
print("Booting slot records:", len(boots))
for i, ts, t in boots[-10:]:
    print("  idx %4d  ts %8d  %s" % (i, ts, t))

# Everything after the LAST 'Booting slot_a': did a second slot_a boot follow?
last_a = max((i for i, _, t in boots if "slot_a" in t), default=None)
print("\nlast slot_a boot at index", last_a)
if last_a is not None:
    print("--- records after the last slot_a boot (first 40) ---")
    for ts, t in recs[last_a + 1:last_a + 41]:
        print("[%08d] %s" % (ts, t))

# reset reason / panic markers anywhere near the end
print("\n--- reset / crash markers (last 25) ---")
pat = re.compile(r"reset_mode|watchdog|wdt|panic|crash|sysdump|boot_fail|bootreason|RST", re.I)
hits = [(ts, t) for ts, t in recs if pat.search(t)]
for ts, t in hits[-25:]:
    print("[%08d] %s" % (ts, t))
print("total reset/crash markers:", len(hits))