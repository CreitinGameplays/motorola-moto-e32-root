import struct, sys

path = sys.argv[1] if len(sys.argv) > 1 else r"artifacts\kimage.bin"
d = open(path, "rb").read()

TOK = 0x10cc300
TOKIDX = 0x10cc700
MARK = 0x10cb400

print("image size", hex(len(d)))
print("tok idx dist", hex(TOKIDX - TOK))

raw = d[TOK:TOKIDX]
print("token table raw first 160:", raw[:160].hex())
toks = raw.split(b"\x00")
print("token count split0", len(toks), "first 16", toks[:16])

idx = struct.unpack_from("<256H", d, TOKIDX)
print("token index first 16", idx[:16])
print("token index last 8", idx[-8:])
print("token index max", max(idx), "monotonic", all(idx[i] <= idx[i+1] for i in range(255)))

for esz in (8, 4, 2):
    n = (TOK - MARK) // esz
    vals = struct.unpack_from("<%d%s" % (min(n, 3000), {8:"Q",4:"I",2:"H"}[esz]), d, MARK)
    nz = [v for v in vals if v]
    print(f"\nmarkers esz={esz} n={n} first={vals[:6]} last_nonzero={nz[-1] if nz else None} count_nz={len(nz)}")
    last = nz[-1] if nz else 0
    for adj in range(0, 32):
        cand = MARK - last - adj
        cand &= ~(esz - 1)
        if cand <= 0:
            continue
        b = d[cand:cand+48]
        print("cand", hex(cand), b.hex())
        break

# try decoding candidate names
def decode_candidate(names_off, markers, esz, tok, idx):
    # markers absolute offsets from names_off
    n = len(markers)
    total = 0
    pos = names_off
    out = []
    for si in range(n * 256 + 512):
        if pos >= MARK:
            break
        ln = d[pos]
        if ln & 0x80:
            ln = (ln & 0x7f) | (d[pos+1] << 7)
            pos += 1
        if ln == 0 or ln > 0x3fff:
            break
        toksyms = d[pos+1:pos+1+ln]
        name = bytearray()
        for t in toksyms:
            off = idx[t]
            end = tok.find(b"\x00", off)
            name += tok[off:end]
        out.append(bytes(name))
        pos += 1 + ln
        total += 1
        if total > 300 and si > 0:
            pass
    return out, pos

last = struct.unpack_from("<Q", d, MARK + 8*479)[0]
print("\nmarkers[479] =", hex(last))
cand = (MARK - last) & ~7
print("names cand", hex(cand), "bytes", d[cand:cand+64].hex())
names, end = decode_candidate(cand, None, 8, raw, idx)
print("decoded", len(names), "end", hex(end), "first names", names[:8])
