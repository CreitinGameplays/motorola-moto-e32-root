#!/usr/bin/env python3
"""Find the embedded IKCONFIG (kernel config) blob in a raw ARM64 Image.

CONFIG_IKCONFIG data is a gzip stream in .rodata whose payload is the
".config" text.  Scan for gzip magic and try to decompress a few KB.
"""
import sys
import zlib

path = sys.argv[1]
data = open(path, "rb").read()
print("image size:", len(data))

hits = 0
pos = 0
while True:
    i = data.find(b"\x1f\x8b\x08", pos)
    if i < 0:
        break
    pos = i + 1
    # try decompress from here, growing window
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(data[i:i + 400000], 200000)
    except Exception:
        continue
    if out.lstrip().startswith(b"#") or b"CONFIG_" in out[:4000]:
        head = out[:200].decode("utf-8", "replace")
        print("HIT at 0x%x  (%d bytes so far)" % (i, len(out)))
        print(head.replace("\n", " | ")[:200])
        open("stock_config.txt", "wb").write(out)
        hits += 1
        if hits >= 3:
            break
print("hits:", hits)
