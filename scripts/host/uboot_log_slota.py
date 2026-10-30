import pathlib, re

p = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloop-stock\uboot_log.img")
d = p.read_bytes()
recs = [(int(m.group(1)), m.group(2).decode("latin-1"))
        for m in re.finditer(rb"\[(\d{8})\]\s([^\x00\r\n]*)", d)]

idx = [i for i, (_, t) in enumerate(recs) if "Booting slot_a" in t]
print("slot_a boots at indices:", idx)
for i in idx:
    print("\n===== around slot_a boot at %d =====" % i)
    for ts, t in recs[max(0, i - 25):i + 45]:
        print("[%08d] %s" % (ts, t))

print("\n=== every record mentioning boot_a / slot_a (count) ===")
for ts, t in recs:
    if re.search(r"boot_a|slot_a", t):
        print("[%08d] %s" % (ts, t))