import pathlib, re, sys

def recs(path):
    d = pathlib.Path(path).read_bytes()
    return [(int(m.group(1)), m.group(2).decode("latin-1"))
            for m in re.finditer(rb"\[(\d{8})\]\s([^\x00\r\n]*)", d)]

old = recs(r"C:\Users\Creitin\moto-root-test\artifacts\bootloop-stock\uboot_log.img")
new = recs(r"C:\Users\Creitin\moto-root-test\artifacts\bootloop-stock\uboot_log2.img")
print("old records:", len(old), " new records:", len(new))

# longest common suffix (ring buffer keeps the newest at the end)
n = 0
while n < min(len(old), len(new)) and old[-1 - n] == new[-1 - n]:
    n += 1
print("common tail records:", n)

fresh = new[:len(new) - n] if n else new
print("new records appended:", len(fresh))
for ts, t in fresh:
    print("[%08d] %s" % (ts, t))