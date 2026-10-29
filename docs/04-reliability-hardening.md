# Root exploit hardening & reliability (2026-10-29)

Companion to `docs/03-root-exploit.md`. This page documents the hardening work
done on `scripts/mali/mali_kroot.c` after the first successful root, the failure
modes that motivated it, and the measured results.

## TL;DR

| build | fresh-boot success | same-boot rerun | notes |
|---|---|---|---|
| first working build | yes (rooted) | mostly no | corrupts kernel pages on false candidates |
| hardened (final) | **5/5** | **3/3** | all attempt 1, 2-5 s per run |

The final binary is `artifacts/mali_kroot` (same source in
`scripts/mali/mali_kroot.c`).

## Failure modes that were fixed

### 1. Bogus physical writes -> kernel Oops

A failed run produced:

```
kmem_cache_free <- __put_task_struct <- delayed_put_task_struct   Comm: id
```

Cause: the task walk returned garbage (`cred=0`, `tasks.prev=0xdeacfffffffffd28`)
and the old code still wrote "patched" creds to a bogus physical address. Two
classes of fix:

- `phys_ok()` / `kva_ok()` bounds checks on every physical target and every
  kernel pointer read from the task list; abort instead of writing on garbage.
- Correct linear-map span (see fix 3); the old bound rejected *valid* creds and
  would have silently steered the walk into garbage.

### 2. Writing hijack PTEs into stale/reclaimed pages

The alias window shows the freed 32 MB of pages regardless of who owns them
now. A page can look exactly like a two-entry marker PTE page (slots >= 32 and
< 32, valid user PTE flags) while actually belonging to another process or to a
previous mapping. Writing a hijack PTE into such a page corrupts an unrelated
page table - the source of the `kmem_cache_free` Oops and of
`cand gone live (race)` loops.

Fix: **read-only liveness proof before the first write** (see fix 1).

### 3. Post-success runs stopped finding candidates

After the first exploit run, repeated runs found nothing even with heavy
pressure. Root cause: the kbase shrinker only evicts `BASE_MEM_DONT_NEED`
pages while the kernel is actually reclaiming memory. Immediately after boot
`MemFree` is tiny and the shrinker runs; once the system settles, `MemFree` is
hundreds of MB and the shrinker never runs, so the "freed" pages are simply
never freed. Fix: drive `MemFree` to the watermark ourselves (fix 4).

### 4. Candidates existed but were skipped

`scan_pg` was monotonic across spray rounds. Early alias pages are often still
"native data" when round 0 scans them, then become the live PTE pages of chunks
sprayed in later rounds (e.g. alias page 0 holding the slot pair `(31,126)`
=> chunk `31*480+(126-32) = 14974`, which is only sprayed in round 7). Those
pages were never re-examined. Fix: reset the cursor per round (fix 5).

## Fixes

### Fix 1 - read-only candidate validation (`validate_candidate_readonly`)

Order: decode candidate from alias, then **before any GPU write**:

1. Pick a probe slot: in a free (non-marker, non-probe) line, slot
   `L*8+j, j>=1`, currently zero. The probe line is removed from the hijack
   line list so cleanup never touches the kernel-created probe PTE.
2. Snapshot: exactly 2 non-zero entries, A/B values recorded.
3. Fault the probe page in through our own CPU mapping of that chunk
   (`chunk_va + probe*0x1000`). If the candidate is the live PTE page for the
   chunk, the kernel itself writes a new entry at the probe slot.
4. `thrash()` (cache eviction) and re-read the alias:
   - exactly one new non-zero entry, at the probe slot,
   - present bit set, phys inside RAM, not the A page,
   - A/B entries bit-identical.
5. Success: `probe_slot`/`probe_val` recorded and the pattern check tolerates
   this third entry.

Because validation writes nothing to the candidate, a false candidate is left
untouched - the failure mode that corrupted page tables is gone. Sample log:

```
[+] validated pg=0x0 probe=9 pte=1600000818b0fd3 (live PTE page confirmed)
[-] validate: probe entry absent (stale page)      <- rejection (safe)
```

### Fix 2 - used-slot bookkeeping in `pattern_still_live()`

After a line is hijacked, its entry stays non-zero (it maps kernel phys). The
old check expected exactly two non-zero entries, so every allocation after the
first failed with `cand gone live (race)`. The exploit now records every hijack
slot (`used_slot/used_val`) and the liveness check requires the page to hold
exactly A, B, the probe (if any) and the known hijack entries - each with the
expected value. This both fixes multi-slot use and detects reuse of the page.

### Fix 3 - address-space bounds and linear-map span

`phys_ok(phys)` and `kva_ok(va)` gate every physical target and every pointer
read from kernel data. The span is the linear-map size, *not* `MemTotal`:

- RAM starts at physical `memstart_addr = 0x80000000` (read live from
  `0xffffff8009371220`), `MemTotal` is 3,610,792 kB (3.44 GiB) after reserves.
- Live creds appear at linear offsets around `0xF9D3AE40` (> `MemTotal`), so
  the map span is rounded up: `span = next_pow2(MemTotal) = 4 GiB`
  -> physical range `[0x80000000, 0x180000000)`, VA range
  `[0xffffffc000000000, 0xffffffc100000000)`.
- Using `MemTotal` as the span rejected valid creds
  (`task[0] bad cred ptr cr=ffffffc0f9d3ae40`) - the walk aborted even though
  the kernel data was correct.

### Fix 4 - pressure to the watermark (`pressure_fill`)

Measured on device:

| state | `mali_rwtest3` (192 MB spray) | result |
|---|---|---|
| fresh boot (`MemFree` ~40 MB) | 5981/8192 freed pages reclaimed | exploit works |
| settled system (`MemFree` ~677 MB) | 0/8192, all still native data | exploit cannot work |
| settled + 512 MB spray (`mali_rwtest3b`) | 0/8192 | still no reclaim |
| `drop_caches` (`MemFree` 507 MB) then pressure to 17 MB | candidate validated | exploit works |

So the shrinker needs `MemFree` near the watermark. `pressure_fill()` allocates
64 MB anonymous slots until `MemFree < 80 MB` (stop if `MemAvailable` drops
below 350 MB; at most 24 slots = 1.5 GB). The chunk spray then runs while
reclaim is active, which is the condition under which kbase evicts the
`DONT_NEED` pages.

```
[i] pressure_fill start npress=0 free=225704kB avail=1389428kB
[i]  press=1 free=155024kB avail=1321676kB
[i]  press=2 free=87072kB avail=1254684kB
[i]  press=3 free=17152kB avail=1185112kB
[+] validated pg=0x165000 probe=9 ...
```

zram/swap absorbs the pressure; the device stayed up in every run.

### Fix 5 - rescan the alias each spray round

`scan_pg = 0` before every round, and a page is only marked `used_pg` after its
probe validation succeeds. Pages rejected earlier are re-examined in later
rounds (they may have become live meanwhile). Effect: fresh-boot success went
from 2/5 to 5/5.

### Fix 6 - up to 4 re-arm attempts

If no candidate is found, the kbase context is fully torn down (`disarm()`:
chunk mapping, alias, native mapping, fd, scanner state) and a fresh context is
armed. Each attempt re-triggers the free and re-runs `pressure_fill()` +
spray. In the measured runs attempt 1 always succeeded, so the retry is pure
insurance; it costs ~2 s per extra attempt.

## Verification

Fresh boot = `adb reboot`, wait for `sys.boot_completed`, 15 s settle, run:

| cycle | result | attempt | time |
|---|---|---|---|
| 1 | root (uid 0, Permissive) | 1 | 4.1 s |
| 2 | root | 1 | 4.1 s |
| 3 | root | 1 | 5.3 s |
| 4 | root | 1 | 5.2 s |
| 5 | root | 1 | 4.2 s |

Same boot, three consecutive runs (after the first successful run):

| run | validated | root shell | attempt | time |
|---|---|---|---|---|
| 1 | yes | yes | 1 | 2.2 s |
| 2 | yes | yes | 1 | 4.4 s |
| 3 | yes | yes | 1 | 2.1 s |

Device remained stable throughout (`uptime` continued, no panic). Logs:
`artifacts/rel2_run_*.txt`, `artifacts/seq_run_*.txt`, `artifacts/rel_run_*.txt`
(the pre-rescan-fix 2/5 matrix).

## Teardown requirements (unchanged, still mandatory)

- Every hijack line must be GPU-zeroed (8 PTEs) and thrashed before exit;
  otherwise the kernel frees the process with stale PTEs pointing at kernel
  physical pages -> `kmem_cache_free` Oops.
- Never `mprotect` a chunk range after GPU writes.
- Never kill the exploit mid-run. A truncated run (e.g. an over-eager
  `| Select-Object -First N` in PowerShell closing the adb pipe) skips the
  teardown. The device survived once, but treat it as unsafe: reboot.

## Quick reproduce

```powershell
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
adb shell chmod 755 /data/local/tmp/mali_kroot
adb shell /data/local/tmp/mali_kroot        # do not truncate the output
```

Expected key lines: `[+] validated pg=... (live PTE page confirmed)`,
`[+] cred patched (readback uid=0 gid=0 cap_eff=3fffffffff)`,
`[+] selinux enforcing now: 00 00 00 01`, `uid=0(root)`, `Permissive`.
