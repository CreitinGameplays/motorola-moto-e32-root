import struct, sys

path = sys.argv[1] if len(sys.argv) > 1 else r"artifacts\kimage.bin"
d = open(path, "rb").read()

TOK = 0x10cc300
TOKIDX = 0x10cc700
MARK = 0x10cb400

raw_tok = d[TOK:TOKIDX]
tidx = struct.unpack_from("<256H", d, TOKIDX)
tokens = []
for t in range(256):
    off = tidx[t]
    end = raw_tok.find(b"\x00", off)
    if end < 0:
        end = len(raw_tok)
    tokens.append(raw_tok[off:end])

markers = struct.unpack_from("<480Q", d, MARK)
nz = [v for v in markers if v]
last = nz[-1]
print("markers nonzero", len(nz), "last", last, hex(last), "markers[1..4]", markers[1:5])

TYPES = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_.$?")

def parse_block(S, count, endpos):
    """Parse `count` entries starting at S; return end pos or None."""
    pos = S
    for _ in range(count):
        if pos >= MARK:
            return None
        b = d[pos]
        if b & 0x80:
            if pos + 1 >= MARK:
                return None
            ln = (b & 0x7f) | (d[pos + 1] << 7)
            pos += 2
        else:
            ln = b
            pos += 1
        if ln == 0 or ln > 0x3fff or pos + ln > MARK:
            return None
        toks = d[pos:pos + ln]
        pos += ln
        name = bytearray()
        for t in toks:
            name += tokens[t]
        if not name:
            return None
        if name[0] not in TYPES:
            return None
        for ch in name[1:]:
            if ch < 0x20 or ch > 0x7e:
                return None
    if endpos is not None and pos != endpos:
        return None
    return pos

lo = MARK - last - 0x10000
hi = MARK - last
lo &= ~3
found = []
for S in range(lo, hi + 1, 4):
    p = parse_block(S, 256, S + markers[1])
    if p is None:
        continue
    p = parse_block(S, 512, S + markers[2])
    if p is None:
        continue
    p = parse_block(S, 768, S + markers[3])
    if p is None:
        continue
    print("candidate S", hex(S), "first entries ok")
    found.append(S)

print("found", len(found), [hex(x) for x in found[:10]])
if found:
    S = found[0]
    # full parse
    pos = S
    n = 0
    ok = True
    while pos < MARK:
        if pos >= MARK:
            break
        b = d[pos]
        if b & 0x80:
            ln = (b & 0x7f) | (d[pos + 1] << 7)
            pos += 2
        else:
            ln = b
            pos += 1
        if ln == 0:
            break
        toks = d[pos:pos + ln]
        pos += ln
        name = bytearray()
        for t in toks:
            name += tokens[t]
        if n < 10 or n > 119590:
            print(n, hex(S + markers[0] if False else pos), name[:60])
        n += 1
        if n > 200000:
            ok = False
            break
    print("parsed", n, "end", hex(pos), "ok", ok)
    print("bytes after end:", d[pos:pos+16].hex())
    # check marker anchors
    good = 0
    for i in range(len(nz)):
        # position S+markers[i] should be entry boundary; verify by re-parse quickly
        pass
    # write S
    open("artifacts/kallsyms_start.txt", "w").write(hex(S))
