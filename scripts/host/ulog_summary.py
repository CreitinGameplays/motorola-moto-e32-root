"""Summarise a uboot_log dump: per-attempt slot, ab_slot_flag, RPMB block,
secure-world verify result, and how far AVB got.

Usage: python scripts/host/ulog_summary.py <uboot_log.img>
"""
import pathlib
import re
import sys

BLK = 0x20000


def lines(blk):
    data = pathlib.Path(blk).read_bytes()
    t = ''.join(chr(c) for c in data if 32 <= c < 127 or c in (10, 13, 9))
    return [re.sub(r'^\[\d+\]\s*', '', l.strip()) for l in t.splitlines() if l.strip()], data


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'artifacts/slot-probe/uboot_log_now.img'
    L, data = lines(path)
    n = len(data) // BLK
    print("file %s  %d bytes  %d blocks\n" % (path, len(data), n))
    print("%-4s %-5s %-8s %-9s %-7s %-7s %-6s %s"
          % ("blk", "slot", "ab_flag", "rpmb_blk", "a0", "avbOK", "vboot", "last line"))
    for i in range(n):
        blk = data[i * BLK:(i + 1) * BLK]
        t = ''.join(chr(c) for c in blk if 32 <= c < 127 or c in (10, 13, 9))
        S = [re.sub(r'^\[\d+\]\s*', '', l.strip()) for l in t.splitlines() if l.strip()]
        if not S:
            continue
        slot = next((l.split('Booting slot')[1][:2] for l in S if 'Booting slot' in l), '-')
        flag = next((re.search(r'ab_slot_flag is (\d+)', l).group(1) for l in S if 'ab_slot_flag is' in l), '-')
        rblk = next((re.search(r'rpmb read blk (\d+)', l).group(1) for l in S if 'rpmb read blk' in l), '-')
        a0 = next((l.split('a0=')[1] for l in S if 'a0=' in l), '-')
        avb = 'YES' if any('avb slot verify OK' in l for l in S) else '-'
        vb = len([l for l in S if 'vboot' in l.lower() or 'verify' in l.lower()])
        print("%-4d %-5s %-8s %-9s %-7s %-7s %-6d %s"
              % (i, slot, flag, rblk, a0, avb, vb, S[-1][:60]))

    print("\n=== every secure-world / AVB verdict line, in order ===")
    for i in range(n):
        blk = data[i * BLK:(i + 1) * BLK]
        t = ''.join(chr(c) for c in blk if 32 <= c < 127 or c in (10, 13, 9))
        S = [re.sub(r'^\[\d+\]\s*', '', l.strip()) for l in t.splitlines() if l.strip()]
        hits = [l for l in S if any(k in l for k in (
            'a0=', 'avb slot verify', 'avb_slot_verify() ', 'allow_verification_error',
            'key_istrusted', 'sprd_secure_check', 'enter avb_slot_verify',
            'Enter vbmeta check', 'vbmeta_ret', 'rollback_index is',
            'verify_img', 'Booting slot'))]
        if hits:
            print("--- block %d ---" % i)
            for l in hits:
                print("   " + l[:140])


if __name__ == '__main__':
    main()