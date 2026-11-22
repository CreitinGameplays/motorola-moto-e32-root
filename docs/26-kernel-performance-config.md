# Kernel performance config defaults (2026-11-21)

`build.sh` now applies a small set of runtime tuning options to *every*
build, on top of the stock config (which was already well tuned).  The
goal was to take the safe wins and leave anything that trades ABI
compatibility, latency or power for a micro-benchmark number.

Applied in the `build.sh` `$S` block:

| option | value | why |
|---|---|---|
| `HZ_300` (`CONFIG_HZ=300`) | y | 250 -> 300 Hz: less scheduler wakeup jitter than 100/250, without the idle-power cost of 1000 Hz.  AOSP's jank/jitter guidance uses 300 on ARM64. |
| `TCP_CONG_ADVANCED`, `TCP_CONG_BBR`, `DEFAULT_BBR` | y | BBR is loss/bufferbloat tolerant; cubic stays built in and selectable. |
| `NET_SCH_FQ`, `NET_SCH_FQ_CODEL`, `NET_SCH_CODEL`, `NET_SCH_DEFAULT`, `DEFAULT_FQ_CODEL` | y | BBR pacing path plus a real AQM by default.  The phone had `pfifo_fast` before (`/proc/sys/net/core/default_qdisc`).  Same combo LineageOS measured best (gauguin: "Switch to BBR TCP + fq_codel qdisc"). |
| `CRYPTO_CRC32_ARM64_CE` | y | ARMv8 crypto extensions for CRC32/CRC32C through the crypto API (f2fs/ext4 metadata checksums). |
| `CRYPTO_AES_ARM64_BS` | y | bit-sliced AES for FBE and WPA2/WPA3. |
| `CRYPTO_SHA512_ARM64` | y | SHA-384/512 in arm64 asm. |
| `CRYPTO_CHACHA20_NEON` | y | NEON ChaCha20. |
| `ARM64_VHE` | y | lets KVM run the host at EL2 and cuts the world-switch cost on ARMv8.1+ (Cortex-A75/A55); runtime-detected, no-op on older cores. |

All of these are runtime-detected or data-path only; none changes a
structure shared with the prebuilt vendor modules.

## Already enabled by the stock config (left alone)

`PREEMPT`, `NO_HZ_IDLE`, `HIGH_RES_TIMERS`, `SCHED_HRTICK`, `SCHED_MC`,
`CPU_FREQ_DEFAULT_GOV_SCHEDUTIL`, `ARM64_LSE_ATOMICS`, `ARM64_HW_AFDBM`,
`ARM64_UAO`, `JUMP_LABEL`, `SLUB_CPU_PARTIAL`, `BPF_JIT_ALWAYS_ON`,
`CC_OPTIMIZE_FOR_PERFORMANCE`, `F2FS_FS`, `ZRAM` (+ `ZRAM_WRITEBACK`).

On the phone: zram runs 1.5 GB with `lz4` selected
(`lzo [lz4] deflate`), i.e. the compressor Android picked is already the
fast one.

## Considered and deliberately not changed

| option | why not |
|---|---|
| `SCHEDSTATS`, `SCHED_DEBUG` | `SCHEDSTATS` adds fields to `struct sched_entity` *inside* `task_struct`; toggling it shifts offsets the prebuilt vendor modules were built against (the abiprobe ABI check of docs 17/18).  Its overhead is small - not worth the ABI break. |
| `DEBUG_INFO` | build-time only; kept for `vmlinux`/crash symbol work. |
| `IOSCHED_DEADLINE` + default `deadline` (currently `noop [cfq]`) | CFQ is what the vendor UFS stack and Android's blkio weights were tuned for on 4.14; a config-only switch is not clearly a win on this board. |
| `TRANSPARENT_HUGEPAGE`, `KSM` | memory/latency trade-offs on a 4 GB phone already swapping 1.4 GB into zram; both stay off. |
| zram `zstd`/`lz4hc` | would only add selectable algorithms (Android's init sets `lz4` anyway) and zstd costs CPU on this SoC. |
| `KALLSYMS_ALL` | kept for diagnostics; disabling saves only kernel memory, not data-path time. |
| `LTO`/`CFI` | still off - they hang this board at boot (docs 17/18). |

## BBR was not compilable in the vendor drop

`net/ipv4/tcp_bbr.c` in the OSS drop is a partly newer version: its
`bbr_tso_segs_goal()` calls `bbr_min_tso_segs()`, but that helper is not
defined anywhere in the tree.  The stock config had `TCP_CONG_ADVANCED`
off, so nobody ever compiled the file.  The build fix restores the helper
used by the newer BBR (and matching the `min_segs` already computed by
`bbr_set_tso_segs_goal()`):

```c
/* override sysctl_tcp_min_tso_segs */
static u32 bbr_min_tso_segs(struct sock *sk)
{
	return sk->sk_pacing_rate < (bbr_min_tso_rate >> 3) ? 1 : 2;
}
```

## Vendor-module caveat for HZ=300

The prebuilt `/mnt/vendor/socko/*.ko` were compiled against HZ=250.  A
constant argument to `msecs_to_jiffies()` is folded at *module* build time
(`include/linux/jiffies.h`), so their timeouts on a 300 Hz kernel run
about 20% short (a 1000 ms timeout becomes ~833 ms).  That is harmless for
timeouts, but after flashing it is worth a smoke test of the vendor-owned
paths: BT on/off, camera open/close, FM/SAR load.  The modules this tree
builds (Mali, sprdwl_ng, sprdbt_tty) are rebuilt with HZ=300 and are
consistent.

## Verify

After a build, in `$STABLE/kernel.config`:

```bash
grep -E '^CONFIG_(HZ=|HZ_300|DEFAULT_TCP_CONG|DEFAULT_NET_SCH|CRYPTO_CRC32_ARM64_CE|CRYPTO_AES_ARM64_BS|CRYPTO_SHA512_ARM64|CRYPTO_CHACHA20_NEON|ARM64_VHE)=' kernel.config
```

Expected:

```
CONFIG_HZ=300
CONFIG_HZ_300=y
CONFIG_DEFAULT_TCP_CONG="bbr"
CONFIG_DEFAULT_NET_SCH="fq_codel"
CONFIG_CRYPTO_CRC32_ARM64_CE=y
CONFIG_CRYPTO_AES_ARM64_BS=y
CONFIG_CRYPTO_SHA512_ARM64=y
CONFIG_CRYPTO_CHACHA20_NEON=y
CONFIG_ARM64_VHE=y
```

On the phone, after flashing the Image and staging the rebuilt modules
(`IKCONFIG_PROC=y` is set, so the running config is readable):

```bash
su -c 'zcat /proc/config.gz | grep -E "CONFIG_HZ=|CONFIG_ARM64_VHE"'
cat /proc/sys/net/ipv4/tcp_congestion_control    # bbr
cat /proc/sys/net/core/default_qdisc              # fq_codel
cat /proc/sys/net/ipv4/tcp_available_congestion_control  # ... bbr ...
```

## Status

Built (EXIT=0, `DONE`), validated and **flashed** to `boot_b` on
2026-11-21.  The build keeps the vermagic and `module_layout` CRC
(`0x89b5c3ef`) unchanged, and an `abiprobe` run built against the new
config matches all 127 offsets of the existing KVM reference.  The phone
boots the new Image in ~1 min with `CONFIG_HZ=300`, BBR + fq_codel active
(`wlan0` also shows `qdisc fq_codel`), vendor modules loading and no
Oops/panic.  Wi-Fi now associates on the 5 GHz network (5200 MHz) and
survives off/on cycles - a bonus the stock configs never had.  Evidence:
`docs/evidence/2026-11-21-kernel-perf-config.txt` and
`docs/evidence/2026-11-21-perf-flash.txt`.  The previous output set is
backed up on the VPS as `~/kernel-out-before-perf`; if needed, power-cycle
once to fall back to the slot-a rescue.
