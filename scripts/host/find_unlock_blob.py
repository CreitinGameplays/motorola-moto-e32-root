import pathlib, re, sys

bl = pathlib.Path(r"C:\Users\Creitin\moto-root-test\artifacts\bootloader\bl")
pat_hex = "a3ba69438ad7993682f1665ab5f25045"
pat = bytes.fromhex(pat_hex)
# also the byte-swapped / reversed variants and the ascii text form
needles = {
    "hex16": pat,
    "hex16_rev": pat[::-1],
    "ascii": pat_hex.encode(),
    "ascii_upper": pat_hex.upper().encode(),
}

kw = re.compile(rb"unlock|Unlock|UNLOCK|VerifiedBoot|lock_status|LOCK FLAG", re.I)

for p in sorted(bl.glob("*.img")):
    d = p.read_bytes()
    out = []
    for name, n in needles.items():
        start = 0
        while True:
            i = d.find(n, start)
            if i < 0:
                break
            out.append((i, name))
            start = i + 1
            if len(out) > 40:
                break
    print("== %-16s %9d bytes  needle-hits=%d" % (p.name, len(d), len(out)))
    for off, name in out[:20]:
        ctx = d[max(0, off - 24):off + 40]
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx)
        print("   %08x %-10s %s" % (off, name, txt))
