#!/usr/bin/env python3
"""Build a tiny unsigned kernel module that issues one Spreadtrum SIP SMC.

The kernel ships no build tree and no Module.symvers, so we cannot compile a
module normally.  Instead we graft a stub into a vendor module built for the
exact same kernel (same vermagic, ``__versions`` and CFI jump table):

* overwrite ``.init.text`` (which starts with ``init_module``) with the stub,
* disable ``.rela.init.text`` so the loader does not rewrite our instructions,
* leave every other section untouched.

Usage:
    python scripts/host/build_sip_ko.py \
        --template artifacts/trace_runqlat_bytedancy.ko \
        --out artifacts/sip_probe.ko \
        --op 0x31 --pa 0x9f123000 --va 0xffffffc01f123000 --len 0x40

``--va`` is the linear-map alias of the physical scratch page:
``va = PAGE_OFF + (pa - memstart_addr)`` with PAGE_OFF = 0xffffffc000000000
(39-bit VA).  The stub stores the four SMC return words at scratch+0x40.
"""

import argparse
import pathlib
import struct

SHF_ALLOC = 0x2
SHT_RELA = 4
SHT_SYMTAB = 2

# int stub(void)
#
#   str  x19, [sp, #-16]!          ; save callee-saved reg
#   movz x19, #va0   ...
#   movz w0, #0x20 ; movk w0, #0xb400, lsl #16   ; SIP id 0xb4000020
#   movz w1, #op
#   movz w2, #lo(pa) ; movk w2, #hi(pa), lsl #16
#   movz w3, #len
#   smc  #0
#   stp  w0, w1, [x19, #0x40]
#   stp  w2, w3, [x19, #0x48]
#   movz w0, #0
#   ldr  x19, [sp], #16
#   ret
#
# Word offsets inside the stub:
W_LEN = 10       # movz w3, #len
W_SMC = 11       # smc #0
W_RET = 15       # ldr x19


def movz(reg, imm, shift=0, sf=0):
    return ((sf << 31) | 0x52800000 | ((shift // 16) << 21)
            | ((imm & 0xFFFF) << 5) | reg)


def movk(reg, imm, shift=0, sf=0):
    return ((sf << 31) | 0x72800000 | ((shift // 16) << 21)
            | ((imm & 0xFFFF) << 5) | reg)


def movn(reg, imm, shift=0, sf=0):
    return ((sf << 31) | 0x12800000 | ((shift // 16) << 21)
            | ((imm & 0xFFFF) << 5) | reg)


def dc(crm, op2, reg):
    """Encode ``dc <op>, Xt`` (op1=3, CRn=7; op2 is only 3 bits)."""
    return 0xD5080000 | (3 << 16) | (7 << 12) | (crm << 8) | (op2 << 5) | reg


DC_IVAC = (6, 1)     # traps on this SoC, kept for reference
DC_CIVAC = (14, 1)
DSB_SY = 0xD5033F9F


def dcache_words(len_):
    """Clean/invalidate the whole scratch buffer (one or two 64-byte lines)."""
    out = [dc(DC_CIVAC[0], DC_CIVAC[1], 19)]
    if len_ > 64:
        out += [0x91010269,                       # add x9, x19, #0x40
                dc(DC_CIVAC[0], DC_CIVAC[1], 9)]
    out.append(DSB_SY)
    return out


def encode(op, pa, va, len_, ret=0, pre_marker=False, dcache=False,
           ret_off=0x40):
    if ret < 0:
        ret_word = movn(0, -ret - 1)      # movn w0, #(-ret-1) == ret
    else:
        ret_word = movz(0, ret & 0xFFFF)
    ret_off = ret_off & ~7
    w_imm = ret_off // 4
    stp01 = 0x29000000 | ((w_imm & 0x7F) << 15) | (1 << 10) | (19 << 5) | 0
    stp23 = (0x29000000 | (((w_imm + 2) & 0x7F) << 15) | (3 << 10)
             | (19 << 5) | 2)
    strm = 0xB9000000 | (((w_imm + 4) & 0xFFF) << 10) | (19 << 5) | 4
    words = [
        0xF81F0FF3,               # str  x19, [sp, #-16]!
        movz(19, va & 0xFFFF, 0, 1),
        movk(19, (va >> 16) & 0xFFFF, 16, 1),
        movk(19, (va >> 32) & 0xFFFF, 32, 1),
        movk(19, (va >> 48) & 0xFFFF, 48, 1),
    ]
    if pre_marker:
        # Written before the SMC: separates "wrong address" from "the SMC
        # clobbers callee-saved registers".
        words += [movz(5, 0x5A5A), movk(5, 0x5A5A, 16), 0xB9005A65]
    if dcache:
        # Clean+invalidate our plaintext out to DRAM before EL3 reads it, so
        # EL3 never sees (and later gets overwritten by) a dirty line.
        words += dcache_words(len_)
    words += [
        movz(0, 0x20),            # movz w0, #0x20
        movk(0, 0xB400, 16),      # movk w0, #0xb400, lsl #16
        movz(1, op & 0xFFFF),     # movz w1, #op
        movz(2, pa & 0xFFFF),     # movz w2, #pa[15:0]
        movk(2, (pa >> 16) & 0xFFFF, 16),
        movz(3, len_ & 0xFFFF),   # movz w3, #len
        0xD4000003,               # smc  #0
    ]
    if dcache:
        # EL3 wrote the result into DRAM (possibly bypassing the cache); drop
        # our now-stale lines so the following loads see its data.  The line
        # was cleaned before the SMC, so this only (re)invalidates.  Note:
        # DC IVAC traps as an undefined instruction on this SoC, DC CIVAC does
        # not, hence CIVAC is used for both directions.
        words += dcache_words(len_)
    words += [
        stp01,                    # stp  w0, w1, [x19, #ret_off]
        stp23,                    # stp  w2, w3, [x19, #ret_off+8]
        # marker: proves the stub itself executed
        0x5294B4A4,               # movz w4, #0xa5a5
        0x72B4B4A4,               # movk w4, #0xa5a5, lsl #16
        strm,                     # str  w4, [x19, #ret_off+0x10]
        ret_word,                 # return value (0 = success)
        0xF84107F3,               # ldr  x19, [sp], #16
        0xD65F03C0,               # ret
    ]
    return b"".join(struct.pack("<I", w) for w in words)


def read_sections(data):
    e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
    e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
    secs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        (name, typ, flags, addr, offset, size, link, info, align,
         entsize) = struct.unpack_from("<IIQQQQIIQQ", data, off)
        secs.append(dict(hdr_off=off, name_off=name, type=typ, flags=flags,
                         addr=addr, offset=offset, size=size, link=link,
                         info=info, align=align, entsize=entsize))
    strtab = secs[e_shstrndx]
    names = data[strtab["offset"]:strtab["offset"] + strtab["size"]]
    for s in secs:
        end = names.find(b"\0", s["name_off"])
        s["name"] = names[s["name_off"]:end].decode("latin1")
    return secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="artifacts/trace_runqlat_bytedancy.ko")
    ap.add_argument("--out", default="artifacts/sip_probe.ko")
    ap.add_argument("--op", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--pa", type=lambda x: int(x, 0), required=True,
                    help="physical address of the 64-byte scratch buffer")
    ap.add_argument("--va", type=lambda x: int(x, 0), required=True,
                    help="linear-map virtual address of the scratch buffer")
    ap.add_argument("--len", type=lambda x: int(x, 0), default=0x40)
    ap.add_argument("--ret", type=int, default=0,
                    help="module init return value; negative makes insmod "
                         "report an errno (used to prove the stub ran)")
    ap.add_argument("--pre-marker", action="store_true",
                    help="write 0x5a5a5a5a at scratch+0x58 before the SMC")
    ap.add_argument("--dcache", action="store_true",
                    help="clean+invalidate the buffer around the SMC so the "
                         "result written by EL3 is actually visible to Linux")
    ap.add_argument("--name", default="sip_probe",
                    help="module name (unique per load, avoids rmmod)")
    ap.add_argument("--ret-off", type=lambda x: int(x, 0), default=0x40,
                    help="scratch offset for the SMC return words/marker; "
                         "move it away from 0x40 to read TrustOS's status byte")
    args = ap.parse_args()

    data = bytearray(pathlib.Path(args.template).read_bytes())
    secs = read_sections(data)
    by_name = {s["name"]: s for s in secs}

    init = by_name.get(".init.text")
    rela = by_name.get(".rela.init.text")
    if not init or not rela:
        raise SystemExit("template lacks .init.text/.rela.init.text")

    stub = encode(args.op, args.pa, args.va, args.len, args.ret,
                  args.pre_marker, args.dcache, args.ret_off)
    if len(stub) > init["size"]:
        raise SystemExit("stub (%d) does not fit .init.text (%d)"
                         % (len(stub), init["size"]))

    # .init.text = stub, then ret padding (never executed).
    blob = stub + b"\xc0\x03\x5f\xd6" * ((init["size"] - len(stub)) // 4)
    data[init["offset"]:init["offset"] + init["size"]] = blob

    # Neutralise the rela section that would patch our instructions.
    off = rela["hdr_off"]
    struct.pack_into("<IIQQQQIIQQ", data, off,
                     0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    # Rename the module so repeated probes never collide (rmmod would run the
    # template's cleanup function, which would crash).
    tm = by_name[".gnu.linkonce.this_module"]
    nm = args.name.encode("ascii")[:63]
    data[tm["offset"] + 24:tm["offset"] + 24 + 64] = nm + b"\0" * (64 - len(nm))
    mi = by_name[".modinfo"]
    mi_bytes = bytes(data[mi["offset"]:mi["offset"] + mi["size"]])
    start = mi_bytes.find(b"name=")
    if start >= 0:
        end = mi_bytes.find(b"\0", start)
        old = mi_bytes[start:end]
        new = b"name=" + nm
        if len(new) <= len(old):
            new += b"\0" * (len(old) - len(new))
            data[mi["offset"] + start:mi["offset"] + end] = new

    pathlib.Path(args.out).write_bytes(data)
    print("wrote %s (%d bytes): op=0x%x pa=0x%x va=0x%x len=0x%x"
          % (args.out, len(data), args.op, args.pa, args.va, args.len))


if __name__ == "__main__":
    main()
