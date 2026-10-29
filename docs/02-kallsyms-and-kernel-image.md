# Kernel Image Dump and kallsyms Recovery (Moto E32, 4.14.199)

Status: **solved** (2026-10-28). Full kallsyms table recovered from the live
kernel image; symbolized ELF generated; key root symbols resolved.

## Image dump
- Kernel Image physically at **0x80080000** (RAM base 0x80000000, `text_offset=0x80000`).
- Dumped 28,479,488 bytes (`image_size=0x1B29000`) with the Mali UAF physical
  read primitive (`scripts/mali/mali_physdump.c`) to `artifacts/kimage.bin`.
- Mapping: file offset `O` <-> phys `0x80080000 + O` <-> VA `_text + O`,
  with `_text = 0xffffff8008080000` (KASLR disabled: `Kernel Offset: disabled`).
- Image header verified: `q0=0x144dc000`, magic `0x644d5241` at +0x38,
  `text_offset=0x80000`, `image_size=0x1b29000`, `flags=0xa`.

### Dump holes and fix
- First dump had 32 KB zero holes (e.g. file `0xE51000-0xE59000`). Cause: the
  GPU PTE cache line holds 8 slots; if a line already cached a different
  mapping, GPU writes to the newly-written slot are masked for the whole line,
  losing 8 pages = 32 KB.
- Fix (`scripts/mali/mali_kdump.c`): dump 8 pages per fresh cache line (never reuse
  a line within a group), read all 8 aliases back to verify, retry with a
  second candidate PTE page on mismatch, then GPU-zero the slots and thrash
  before reuse. No panics, no reboots.
- Re-dumped region `[0xDE0000, 0x10CD000)` (749 pages, 94 groups) cleanly to
  `artifacts/kallsyms_region.bin` (3,067,904 bytes); spliced into
  `artifacts/kimage_ok.bin`.

## kallsyms layout (file offsets into Image)
- token table: `0x10CC300`
- token index: `0x10CC700` (256 `u16`, strictly increasing, max 802)
- markers: `0x10CB400`, **469** entries (`u64`), `[0]=0,[1]=3428,[2]=6339,
  [3]=9719,[4]=13039,[5]=16313,[467]=2566601,[468]=2570942`, then 96 zero
  bytes before the token table
- **names: `0xE57400`**, **num_syms: `0xE57300` = 119,878 (`0x1D446`)**,
  relative base: `0xE57200` = `_text` (0xffffff8008080000)
- offsets array: **`0xDE2000`**, 119,878 `u32` (length `0x75118`, 4-byte
  aligned; 0xE8 bytes zero pad to 0xE57200)
- labels are 256-byte aligned; **the offsets are relative to `_text`**
  (`addr = 0xffffff8008080000 + offsets[i]`)
- names blob parses to `0x10CB399` (0x67 zero padding to markers)
- previous wrong hypothesis (names at 0xE57400 with ALGN=8 and num_syms at
  S-8/S-16) discarded: S-8/S-16 are zero because the real fields are at the
  256-aligned labels above.

## Verification
- all 119,878 names decompress with the token table; all 469 markers match
  (every 256 entries); offsets array strictly non-decreasing, max `0x1B29000`
  (= image_size); first names `t_head`, `T_text`, `Tdo_undefinstr`,
  `T_stext`, `T__exception_text_start`, `Tdo_sysinstr`; last `B_end`.
- `vmlinux-to-elf` succeeded on `kimage_ok.bin`:
  `artifacts/vmlinux_ok.elf` (35,419,361 bytes), parse log
  `artifacts/vmlinux_to_elf_run.txt`.

## Key symbols (VA)
| symbol | VA |
|---|---|
| `_text` | `0xffffff8008080000` |
| `_stext` | `0xffffff8008081000` |
| `_end` | `0xffffff8009ba9000` |
| `__bss_stop` | `0xffffff8009ba1520` |
| `init_task` | `0xffffff8009721780` |
| `init_cred` | `0xffffff800972c0c0` |
| `init_nsproxy` | `0xffffff800972bf58` |
| `commit_creds` | `0xffffff8008260a00` |
| `prepare_kernel_cred` | `0xffffff8008260d7c` |
| `prepare_creds` | `0xffffff8008260620` |
| `kallsyms_lookup_name` | `0xffffff80082fd880` |
| `sys_call_table` | `0xffffff80092a1000` |
| `swapper_pg_dir` | `0xffffff8009ba5000` |
| `modprobe_path` | `0xffffff800972c408` |
| `kimage_voffset` | `0xffffff8009371230` |
| `memstart_addr` | `0xffffff8009371220` |

Physical address of an image symbol:
`phys = VA - 0xffffff8008080000 + 0x80080000`.

## Tooling
- `scripts/mali/mali_physdump.c` - original full Image dump (source of holes).
- `scripts/mali/mali_physrd.c` - alias-verified 8-page re-dump (hole repair).
- `scripts/mali/mali_kdump.c` - 749-page region re-dump, per-group
  verification/retry, cleanup; used for `kallsyms_region.bin`.
- `artifacts/kimage_ok.bin` - repaired Image used for symbol extraction.
- `artifacts/vmlinux_ok.elf` - symbolized ELF.

## Next
1. Derive `task_struct`/`cred` offsets from `vmlinux_ok.elf` disassembly
   (`commit_creds`, `prepare_kernel_cred`, `sys_getuid`, `copy_creds`).
2. Build phys R/W tool (write side of `mali_kdump`); walk `init_task.tasks`,
   match our `comm`, patch `cred` uid/gid/caps to 0; optionally set
   `selinux_enforcing=0`.
3. Verify with `id`/`getenforce`; document the root run.

## DONE (2026-10-28)
Steps 1-3 completed: offsets derived and documented in
`docs/03-root-exploit.md` (`tasks`=0x4D8, `cred`=0x788, `comm`=0x790,
`real_parent`=0x5E8, cred uid..fsgid=0x04..0x20, caps 0x28..0x40,
`selinux_state.enforcing` = `selinux_state+1`).
`scripts/mali/mali_kroot.c` uses this table: **root obtained**
(`uid=0(root)`, SELinux Permissive).

Note: parts of the dumped Image are still zeroed (32 KB holes outside
`[0xDE0000,0x10CD000)`), e.g. `commit_creds` at file offset `0x1E0A00`.
The symbols themselves come from kallsyms and are unaffected; the holes only
matter for disassembly of specific functions.
