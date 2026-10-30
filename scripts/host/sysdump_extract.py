"""Recover the kernel log from a SPRD sysdump image.

On panic, `sysdump_panic_event()` copies the kernel printk ring buffer into the
`log_buf` minidump section, and U-Boot writes the minidump to the `sysdumpdb`
partition on the next boot. That makes a panic observable on this device even
though the console goes to an unreadable UART.

Usage:
    python scripts/host/sysdump_extract.py <sysdumpdb.img> [...]

Prints, for each image:
  * the crash banner (why it dumped),
  * every kernel-log-looking line in order, with the interesting ones
    (soft lockup, call trace, PC, panic, Oops) pulled to the top.
"""
import pathlib
import re
import sys

# kernel log lines look like "<6>[  123.456789] text" or "[  123.456789] text"
LOG_RE = re.compile(r"^[<\[]\s*\d+[>\]]\s*\[?\s*\d+\.\d+\]?\s*\S")
INTERESTING = re.compile(
    r"soft lockup|hard lockup|hung task|Call trace|CPU:|PC is at|"
    r"pc :|lr :|sp :|panic|Oops|BUG:|Internal error|Unable to handle|"
    r"Kernel Offset|WARNING:|watchdog|stuck for", re.I)


def printable_runs(data, min_len=8):
    out = []
    cur = bytearray()
    for c in data:
        if 32 <= c < 127 or c in (9,):
            cur.append(c)
        else:
            if len(cur) >= min_len:
                out.append(cur.decode("ascii", "replace"))
            cur = bytearray()
    if len(cur) >= min_len:
        out.append(cur.decode("ascii", "replace"))
    return out


def main():
    paths = [pathlib.Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit(__doc__)

    for p in paths:
        data = p.read_bytes()
        runs = printable_runs(data)

        # split runs into lines, keep kernel log lines in file order
        lines = []
        for run in runs:
            for part in re.split(r"(?<=[\]\)\.])\s{2,}|\n", run):
                part = part.strip()
                if part:
                    lines.append(part)

        loglines = [l for l in lines if LOG_RE.search(l)]
        print("=" * 78)
        print("%s  %d bytes  (%d printable runs, %d log-ish lines)"
              % (p.name, len(data), len(runs), len(loglines)))

        print("\n--- crash banner ---")
        shown = 0
        for l in lines:
            if re.search(r"kernel_crash|Native hang|Sysdump enter|panic", l, re.I):
                print("  " + l[:150])
                shown += 1
                if shown >= 12:
                    break
        if not shown:
            print("  (none)")

        hits = [l for l in loglines if INTERESTING.search(l)]
        print("\n--- interesting kernel lines (%d) ---" % len(hits))
        for l in hits[:80]:
            print("  " + l[:180])
        if len(hits) > 80:
            print("  ... %d more" % (len(hits) - 80))

        print("\n--- first 40 kernel log lines ---")
        for l in loglines[:40]:
            print("  " + l[:180])
        print("\n--- last 40 kernel log lines ---")
        for l in loglines[-40:]:
            print("  " + l[:180])


if __name__ == "__main__":
    main()