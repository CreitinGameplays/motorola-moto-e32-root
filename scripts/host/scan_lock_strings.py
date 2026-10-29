import pathlib, re

bl = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloader\bl")
kw = re.compile(rb"unlock|Unlock|UNLOCK|lock flag|lock_status|lock status|verifiedboot|secureboot", re.I)

for name in ["misc.img", "miscdata.img", "persist.img", "prodnv.img", "elabel.img",
             "metadata.img", "factory.img", "teecfg_a.img", "sysdumpdb.img"]:
    p = bl / name
    d = p.read_bytes()
    hits = []
    for m in re.finditer(rb"[\x20-\x7e]{5,}", d):
        if kw.search(m.group()):
            hits.append((m.start(), m.group()[:120]))
    print("== %-14s %9d  hits=%d" % (name, len(d), len(hits)))
    for off, s in hits[:14]:
        print("   %08x  %s" % (off, s.decode("ascii", "replace")))
    if len(hits) > 14:
        print("   ... (%d more)" % (len(hits) - 14))
