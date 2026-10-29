# Secure-world unlock path: the `miscdata` `VerifiedBoot-UNLOCK` marker

Follow-up to [05](05-bootloader-unlock-research.md). Static analysis of the
U-Boot image found the **actual unlock state machine** and the SMC service it
talks to. This document records the mechanism, the reversing evidence, and the
first in-kernel experiment plan.

Status: mechanism fully decoded; the signing call is being tested from Linux
with an unsigned kernel module (see [Test plan](#test-plan)).
Everything below was derived **offline** from dumps taken with the runtime-root
exploit; nothing here writes to the device.

## 1. `oem unlock` and `oem unlock_bootloader` are different code paths

`fastboot_oem_handler` at `0x29be4` (annotated trace:
`artifacts/bootloader/uboot_trace_unlock.txt`, disassembly:
`artifacts/bootloader/uboot_disasm.txt`) dispatches on the first argument:

```
oem unlock                      oem unlock_bootloader
----------------------------    ----------------------------------------
0x8f06c(2)  == 0 ?              same gate
0x82760()   != 1 ?              same "already unlocked" check
erase userdata + metadata       require 64-byte token buffer @0x279000 != 0
0x82664(1)                      verify fastboot payload with 0x82a68()
-> "Unlock bootloader            -> "Unlock bootloader fail." on failure
   fail." on 0x82664 != 0
```

* `0x8f06c(n)` issues SMC op `0x0a` to fetch a 32-bit **secure lock status**
  into global `0x70e000`, then returns 0 only if that value is `1`
  (i.e. secure world already says "unlocked"). Otherwise the command answers
  `Not implemet.`
* `0x82760()` is the *state check*: it reads `miscdata` at offset `0x2000`
  (512 bytes) and calls SMC op `0x33` to validate the 64-byte block stored
  there. It caches the answer in global `0x271768` (`1` = valid unlock marker).
* `0x82664(1)` is the *state writer*: it builds the string
  `"VerifiedBoot-UNLOCK"` (or `"VerifiedBoot-LOCK"` for argument `0`),
  **signs it with SMC op `0x31`**, and writes the 64-byte result to `miscdata`
  at offset `0x2000`.
* `oem unlock_bootloader` additionally demands that the identifier token was
  fetched first (64-byte buffer at `0x279000` must be non-zero), then verifies
  the fastboot payload with `0x82a68()`.

So the persisted unlock state is a **64-byte signed marker in `miscdata`**,
not an OTP bit read directly by U-Boot. That marker is created by secure
world, and validated by secure world, on every lock/unlock check.

## 2. What U-Boot does at boot with the marker

`0x81e24` runs the boot image verification and then computes the lock flag:

```
w1 = avb_result
if (*0x271768 == 1)      w1 = 2     ; miscdata marker valid  -> UNLOCK
else if (avb_result == 0) w1 = 0    ; green
else if (avb_result == 5) w1 = 1    ; orange
else                      w1 = 3    ; red / error
*0x274810 = w1
```

`0x229a0` reads `*0x274810`; when it is `2` it prints

```
WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!
```

and skips AVB entirely. The live device has **never** printed that string
(`uboot_log` contains no `LOCK FLAG`/`SKIP VERIFY`/`VerifiedBoot`), which
confirms the marker is absent, and gives us a cheap success oracle for later
tests.

## 3. The SMC gateway (`0xb4000020`)

All secure-world calls funnel through one wrapper:

```
0x8d0e8(op, buf, len):
    struct { u32 fn; u32 op; u32 buf; u32 len; ... } msg;   ; 32 bytes @0x707058
    msg.fn = 0xb4000020            ; Spreadtrum SIP service id
    msg.op = op
    msg.buf = (u32)(uintptr_t)buf  ; physical, truncated to 32 bits
    msg.len = len
    return 0x8d0bc(&msg)

0x8d0bc(msg):
    w0..w3 = msg[0..3]
    smc #0                          ; EL3
    msg[0..3] = w0..w3              ; return words
```

Known operations used by U-Boot:

| op | wrapper | meaning |
|---|---|---|
| `0x03` | `0x8d070` | RSA verify (buffer + len) |
| `0x0a` | `0x8d04c` | read 32-bit **secure lock status** into buffer |
| `0x0b` | `0x8d098` | no-arg query, returns status word |
| `0x31` | `0x8cfac` | **sign/transform** the 64-byte `VerifiedBoot-*` string in place |
| `0x33` | `0x8cfd4` | **verify** the 64-byte `miscdata` marker (0 = valid) |

`trustos_a` contains the matching strings: `FUNCTYPE_CRYPTO_DATA`,
`FUNCTYPE_CHECK_LOCK_STATUS`, `VerifiedBoot-LOCK`, `VerifiedBoot-UNLOCK`,
`VerifiedBoot-HUK-DERIVE`, `sprd_rsa_sign`, `sprd_rsa_verify`,
`unlock status is matched, return unlock.`,
`unlock status isn't matched, return lock.`
(`VerifiedBoot-HUK-DERIVE` shows the marker key is derived from a
hardware-unique key, so the marker cannot be computed offline.)

### Why this is interesting

`op 0x31` is an **unauthenticated signing oracle**: U-Boot calls it exactly
like any other EL3 client and passes no credential. If TrustOS does not gate
the call on the current lock state, then any code running in the non-secure
world (including our runtime-root kernel) can ask secure world to mint the
`VerifiedBoot-UNLOCK` marker. That would be a full unlock without any key.

The gate `0x8f06c` proves the *status* is separate from the *marker*, i.e.
the marker is designed to be the persistent authority. The open question is
only whether op `0x31` checks "may I sign an unlock marker now?".

## 4. Module environment (why a kernel module is viable)

From `scripts/device/probe_module_env.sh`, the kernel image and the vendor
modules on `/vendor/lib/modules`:

| item | value |
|---|---|
| kernel | `4.14.199+-ab612c2 #1 SMP PREEMPT aarch64`, PSCI conduit **`smc`** |
| `CONFIG_MODULES` / `CONFIG_MODULE_SIG` | yes / **not set** (unsigned modules load) |
| `CONFIG_MODULE_FORCE_LOAD` | **not set** |
| `CONFIG_MODVERSIONS` | yes (`__versions` required: `module_layout` CRC) |
| `CONFIG_MODULE_REL_CRCS` | not set |
| `CONFIG_CFI_CLANG` | yes (indirect calls go through `.cfi_jt` stubs) |
| `CONFIG_STRICT_MODULE_RWX`, `CONFIG_ARM64_MODULE_PLTS` | yes |
| vermagic | `4.14.199+-ab612c2 SMP preempt mod_unload modversions aarch64` |
| struct module | size `896`, `name` @`+0x18`, `init` @`+0x158`, `exit` @`+0x310` |

`kheaders.ko` loads fine and exposes `/sys/kernel/kheaders.tar.xz`
(3.35 MB), which provided `include/generated/autoconf.h` and the headers used
for the table above:

```bash
adb shell "chmod 755 /data/local/tmp/mali_kroot; \
  /data/local/tmp/mali_kroot >/data/local/tmp/kroot.log 2>&1; \
  sh /data/local/tmp/load_kheaders.sh"
adb pull /data/local/tmp/kheaders.tar.xz artifacts/
```

### Grafting instead of building

The kernel has no build tree and `Module.symvers` is not shipped, but the
vendor `trace_*.ko` / `incrementalfs.ko` modules are built by the same
toolchain for this exact kernel and already carry:

* the correct `vermagic`,
* a `__versions` table (so `check_modstruct_version`/`check_version` pass
  without `force_load`),
* `.gnu.linkonce.this_module` (896 bytes) with `init`/`exit` relocations,
* a valid CFI jump-table entry `init_module.cfi_jt`.

`scripts/host/build_sip_ko.py` therefore reuses a vendor module as a container:
it overwrites `.init.text` with a hand-assembled stub, disables
`.rela.init.text` (so the loader does not rewrite our instructions) and leaves
everything else untouched. The kernel resolves `mod->init` to
`init_module.cfi_jt`, which branches to `.init.text+0` — our stub.

`scripts/host/ko_info.py` dumps the sections/relocations and was used to
confirm the offsets above.

## 5. The stub

`smc #0` is legal from EL1 (PSCI uses the same conduit). The stub issues one
SIP call and stores the four returned words into a caller-supplied scratch
page:

```
str  x19, [sp, #-16]!
movz x19, #va16 ; movk x19, ..., lsl 16/32/48   ; linear-map VA of scratch page
movz w0, #0x0020 ; movk w0, #0xb400, lsl #16    ; SIP service 0xb4000020
movz w1, #op                                    ; 0x0a / 0x31 / 0x33
movz w2, #pa16 ; movk w2, #pa_hi, lsl #16       ; physical scratch address
movz w3, #len
smc  #0
stp  w0, w1, [x19, #0x40]                       ; status + returns
stp  w2, w3, [x19, #0x48]
mov  w0, #0
ldr  x19, [sp], #16
ret
```

The scratch page is an anonymous, `mlock`ed userspace page; its physical
address comes from `/proc/self/pagemap` (root has `CAP_SYS_ADMIN`). Because
TrustOS writes into that physical page directly, the result is visible in
userspace with no copy. The linear-map alias is
`PAGE_OFF + (pa - memstart_addr)` (arm64 39-bit VA), which is why the stub also
embeds a patched VA: `memstart_addr` is read from the exploit log
(`[i] memstart_addr=...`).

Per-run patching of the two/three immediates is done by
`scripts/host/build_sip_ko.py`, so the `.ko` is regenerated for each boot.

## 6. Test plan

Ordered by risk. Each step uses a fresh boot and the runtime-root exploit.

| # | op | input | expected | what it proves |
|---|---|---|---|---|
| 1 | `0x0a` | 4 bytes | buffer[0] = 0/1 | EL3 accepts our SMC and the paddr |
| 2 | `0x0b` | none | status word | second, independent status read |
| 3 | `0x33` | current `miscdata[0x2000..0x2040]` | non-zero (invalid) | verify path reachable |
| 4 | `0x31` | `"VerifiedBoot-UNLOCK"` | 0 + transformed 64 bytes | **signing oracle works** |

If step 4 succeeds:

```
root# dd if=<scratch> of=/dev/block/by-name/miscdata bs=1 seek=$((0x2000)) count=64 conv=notrunc
root# sync; reboot
```

then check `ro.boot.flash.locked`, `ro.boot.verifiedbootstate`, and
`uboot_log` for `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!`.
Note: U-Boot's own `0x82664` reads/writes a full 512-byte block at `0x2000`;
the test writes 64 bytes into the existing block, so the rest is preserved.

Failure modes to record:

* `0xffffffff` / `SPRD_ERR_NOT_SUPPORTED`: service id or op mismatch,
* `SPRD_ERR_INVALID_PARAM`: buffer/len rejected (alignment, range, or
  plaintext not as expected),
* non-zero without buffer change: gate refused (locked state), i.e. the
  oracle is authenticated after all.

## 7. Result log

| date | step | outcome |
|---|---|---|
| 2026-10-29 | module environment + kheaders | ok, see tables above |
| 2026-10-29 | `0x0b` no-arg query | returns 0, buffer untouched |
| 2026-10-29 | `0x0a` len 4 | writes `05 00 00 00` (secure lock status = 5) |
| 2026-10-29 | `0x31` len 0x40 plaintext | `-14` (EFAULT) from the `"sprdsec"` map helper |
| 2026-10-29 | `0x31` len 0x80..0x1000 | return 0, **64-byte marker produced** |
| 2026-10-29 | `0x33` len 0x80, zeroed block | return 0, status byte `+0x40` = 0 |
| 2026-10-29 | `0x33` len 0x80, marker block | return 0, status byte `+0x40` = 1 |
| 2026-10-29 | miscdata `0x2000` marker write | **U-Boot prints the UNLOCK banner and skips verify** |
| 2026-10-29 | first boot after marker | boot loop: old `/data` no longer usable |
| 2026-10-29 | recovery `Wipe data/factory reset` | boots to Android setup, unlock persists |

### 7.0 Boot loop after the first unlocked boot (expected)

Android came up far enough to toast, but rebooted in a loop because the
existing `/data` was created under the old verified-boot state. This is the
same reason a normal `fastboot oem unlock` wipes userdata. Recovery
(`Wipe data/factory reset`, no signature needed) fixed it and the device then
booted to the setup wizard with the marker still in `miscdata`.

Important: the boot-level unlock does **not** unlock fastboot. While in the
bootloader,

```
fastboot -w
  Erasing 'userdata' ... (bootloader) Please verify the signature!
  FAILED (remote: 'Please verify the signature!')
```

so flashing/erasing still requires Motorola-signed requests. Wiping from
stock recovery is the only free operation, and it is enough to recover from
the post-unlock data mismatch.

The marker is 64 bytes, deterministic across boots and scratch pages:

```
f5 53 44 ab 11 63 dd 2a 21 53 5f 77 db a1 7c 54
23 aa ad 81 5e dd be 88 42 fe e7 f2 f5 d0 71 76
9b b3 11 6f a0 7a 85 e4 66 9b 4c 56 a1 0f 5a 10
9b b3 11 6f a0 7a 85 e4 66 9b 4c 56 a1 0f 5a 10
```

(appended to `miscdata` at `0x2000`; the rest of the 512-byte block stays
zero). Note the last two 16-byte blocks are identical, which is what AES-CBC
produces here because the chained input repeats - the plaintext after the
19-byte string is all zero and the chain state repeats with period two
64-byte blocks.

### 7.1 Why earlier `0x31` runs "succeeded but wrote nothing"

The decisive bug was on our side, not a secure-world gate:

* TrustOS encrypts into a heap buffer and then does
  `memcpy(our_va, tmp, len)` (handler at `0x384a8`, copy-back at `0x38640`).
  It really does write the result on success.
* Our scratch page is a `MAP_SHARED` file page that we had just written the
  plaintext into, so the cache line was dirty in L1/L2. EL3 writes DRAM
  directly (non-cacheable secure alias), and Linux then served the *stale
  dirty line* back to `dd`: return 0, "unchanged" buffer.
* The fix is cache maintenance around the SMC, emitted by the stub:
  `dc civac` + `dsb sy` before the call (push the plaintext to DRAM) and the
  same pair after it (drop the now-stale line). See `--dcache` in
  `scripts/host/build_sip_ko.py`.
* `dc ivac` is **not** usable: on this SoC it faults at EL1 as
  `Internal error: undefined instruction: 0` (panic at `init_module+0x44`).
  `dc civac` is accepted, and a second `civac` over an already-clean line
  behaves as an invalidate, so it is used for both directions.

Because the cache hid the writes, the earlier "one-off high-entropy buffer"
observation was correct after all - it was the same marker, just read from
DRAM by luck when the line happened to be evicted first.

### 7.2 `0x31` vs `0x33` argument shape

Both handlers map the caller buffer with the `"sprdsec"` mapper, rounding the
length up to a page (`(len & ~0xfff) + 0x1000`), so the physical address must
be page aligned and below 4 GiB. `0x31` with `len = 0x40` fails to map
(`-14`); `0x31` with `len >= 0x80` works. `0x33` is called with `len = 0x80`
by U-Boot and reports its verdict as a byte at buffer `+0x40`:

* match (`E("VerifiedBoot-UNLOCK")`): status `1`, return 0
* mismatch: status `0`, return 0

`0x33` also rewrites the first 16 bytes of the buffer while comparing, so the
input block must be re-written before every trial.

### 7.3 The mapper rejects the first request (-14), retries succeed

The two handlers issue *identical* map requests (name `"sprdsec"`, page-rounded
length, flags `0x30`), yet the request is sometimes refused with `-14`
(EFAULT) and an immediately repeated, byte-for-byte identical call succeeds:

```
op 0x31 attempt 0 -> rc=-14   (buffer untouched)
op 0x31 attempt 1 -> rc=0     (marker written)
op 0x33 attempt 0 -> rc=-14   (on the same page, right after two 0x31 calls)
op 0x33 attempt 1 -> rc=0 status=1
```

So the mapper keeps some state per buffer/operation and the first request
after a change is refused; the retry then succeeds. `scripts/host/unlock_marker.py`
therefore retries each operation up to four times and treats `rc == 0` as the
only success criterion. This is also why the very first "signing" attempt in
this project looked like a silent no-op.

### 7.4 Reading `+0x40` with the stub

The stub stores its four SMC return words at scratch `+0x40`, which is exactly
where `0x33` puts the status byte. `--ret-off` moves that store (e.g.
`--ret-off 0xF0`) so the real status byte can be observed. The `stp`
immediate is 7-bit signed scaled by 4, so `0xF0` is the largest usable offset;
`--ret-off 0x100` silently encodes `-0x100`.

### 7.5 Confirmed end state

After writing the marker to `miscdata[0x2000]` and wiping `/data` once:

| property | value |
|---|---|
| `ro.boot.flash.locked` | `0` (unlocked) |
| `ro.boot.verifiedbootstate` | `orange` |
| `ro.boot.veritymode` | `enforcing` |

U-Boot prints `WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!` on every
boot, the marker read back from flash after a reboot is byte-identical to the
one that was written, and the runtime root exploit still works on the wiped
device (`mali_kroot` -> `uid=0`, `ROOTPROOF_0_Permissive`).

## Reproduce

Full step-by-step instructions are in `docs/07-unlock-how-to.md`; the short
version:

```bash
# 1. headers/kernel facts
adb push scripts/device/load_kheaders.sh /data/local/tmp/
adb shell "chmod 755 /data/local/tmp/mali_kroot; \
  /data/local/tmp/mali_kroot >/data/local/tmp/kroot.log 2>&1; \
  sh /data/local/tmp/load_kheaders.sh"
adb pull /data/local/tmp/kheaders.tar.xz artifacts/

# 2. module template inspection
python scripts/host/ko_info.py artifacts/trace_runqlat_bytedancy.ko

# 3. mint + verify + flash the marker (automates the steps in docs/07)
adb push artifacts/sip_page /data/local/tmp/sip_page
adb push artifacts/mali_kroot /data/local/tmp/mali_kroot
python scripts/host/unlock_marker.py            # dry run
python scripts/host/unlock_marker.py --flash    # writes miscdata 0x2000

# 4. wipe /data once from stock recovery, reboot, confirm
adb shell getprop ro.boot.flash.locked          # 0
adb shell getprop ro.boot.verifiedbootstate     # orange
```

## Verdict

**Confirmed working.** The bootloader unlock state is a 64-byte marker in
`miscdata` at offset `0x2000`, produced by SIP service `0xb4000020` op `0x31`
(AES-CBC over the ASCII string `"VerifiedBoot-UNLOCK"` with a key derived from
the chip-unique `VerifiedBoot-HUK-DERIVE` secret). The call is **not** gated on
lock state for a root caller, so once the kernel can issue SMCs the marker can
be minted on-device and written to flash.

After writing it, U-Boot takes the unlocked branch on every boot
(`WARNNING: LOCK FLAG IS : UNLOCK, SKIP VERIFY!!!`), which is a permanent,
software-only unlock: no Motorola key, no unlock code, no signed FDL, no
BootROM exploit. `/data` has to be wiped once (recovery is enough) because it
was created under the previous verified-boot state.

Caveat: the marker only affects the *boot* path. The fastboot download gate
still rejects unsigned requests (`Please verify the signature!`), so this is
not a general "unlocked bootloader" for flashing arbitrary images - it is an
unlock of the verified-boot/AVB policy check, which is what `SKIP VERIFY`
means here.
