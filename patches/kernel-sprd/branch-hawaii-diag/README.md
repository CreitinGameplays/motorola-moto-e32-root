# branch-hawaii-diag - local kernel changes, as an applicable series

Snapshot of the `hawaii-diag` branch of our Moto E32 kernel tree
(`~/kernel-sprd` on the build VM), exported with `git format-patch` against the
vendor OSS drop it is based on.  Applying this series to a pristine checkout
reproduces that branch **byte for byte** (verified with `git am` + tree-hash
comparison; final tree `235b58f4e9f2`).

The same history is published as
[motorola-moto-e32-kernel](https://github.com/CreitinGameplays/motorola-moto-e32-kernel):
a root **import commit** whose tree is the vendor drop verbatim, followed by
the commits above (cherry-picked, authorship kept), so each change is
reviewable as a normal diff.  (The 738k-commit vendor history itself cannot be
pushed.)

    base    MotorolaMobilityLLC/kernel-sprd
            branch R-11-release-RORS, commit c4e610cd833c ("Add design file")
    series  0001..0017
    tree    235b58f4e9f239ef3039a33d9575c015920ccd0c

## Applying

    git clone https://github.com/MotorolaMobilityLLC/kernel-sprd.git
    cd kernel-sprd
    git checkout c4e610cd833c
    git am /path/to/00[01][0-9]-*.patch

`hawaii-diag-full.diff` is the same change as one flat diff (`git diff
c4e610cd..HEAD`, 395 files, +134,732/-41), for reading or `git apply`.

## Contents

| patch | what |
| --- | --- |
| 0001 | `.gitignore`: ignore the tree's own build outputs (`Image.*`, `System.map.*`, `*.dtbo`, `*.symversions`, `localversion`, reconstructed configs) |
| 0002 | build fixes for the OSS drop: `-I$(src)` for `drivers/devfreq/sprd` and `drivers/staging/sprd/sfp`, `vhost_vring_ioctl()` takes `unsigned int` |
| 0003 | backports the RORS userspace expects: `fget_many()`/`fput_many()` with the refcount-recheck loop, and the `anon_vma` `num_children`/`num_active_vmas` split |
| 0004 | `sipc: sbuf_copy_from_user()` - a `copy_from_user()` that does not zero the tail of a partially copied shared-memory block |
| 0005 | SPRD uapi ABI: `SPRD_JPG_MAP_SIZE`, `SPRD_VSP_MAP_SIZE` 0x14000, `SENSOR_IO_PRI_KEY` |
| 0006-0007 | **DIAG only**: on-panel boot tracing (framebuffer text console, paint bands, milestone line, printk mirror, AON watchdog arm, late KVM init) + the generated `diag_stage.h`/`diag_font.h` snapshot, `diag/README.md`, device config |
| 0008-0011 | **DIAG only**: shared console instance + EL2 header, solid glyphs, ramoops capture + early AON watchdog, setup/initcall checkpoint selectors |
| 0012 | `arm64/lld`: place Clang CFI jump tables in core text (the fix that made the non-LTO config boot) |
| 0013 | `.gitignore`: local AVB tooling and packaged boot images |
| 0014 | **Mali**: import the Arm Mali Bifrost DDK r28p0-01eac0 core (pristine, matches the vendor module's UK version 11.29) |
| 0015 | **Mali**: add the Unisoc qogirl6 platform glue (from the r40p0 vendor fork) |
| 0016 | **Mali**: adapt the glue to r28p0 APIs, this board's DT (generic `syscons`/`syscon-names` bindings, `sprd,dvfs-lists`, T606 GPLL trim, core voltage index maps) |
| 0017 | **Mali**: fix the `power_control_init` Synchronous External Abort - the DDK's own clock enabling dies on `aonapb-gate#9` (`sprd_gate_enable` -> AON APB regmap read -> SEA 0x96000010); skip that path for qogirl6 and let the platform glue own clocks/regulators (vendor behavior). Also adds the config-gated MDBG probe instrumentation (`CONFIG_MALI_MDBG_CRUMB`, default n) |

`phone.config` is the current build configuration (`.config.diagwdt`: non-LTO,
`CONFIG_MALI_MIDGARD=m`, `CONFIG_MALI_PLATFORM_NAME="qogirl6"`, AON watchdog
diagnostics; `CONFIG_MALI_MDBG_CRUMB=m` for hang probes - production builds
set it to n).  Line endings are normalized to LF so the patch series is exact.

## State

**Boots Android end to end.** The 4.14.199 tree with this series boots the
phone to `sys.boot_completed=1` on the custom kernel, with the in-tree Mali
driver probed (`Probed as mali0`) via the Magisk post-fs-data module, and
Magisk `su` working. History of the bring-up:
`docs/evidence/2026-11-02-mali-autoload-success.txt` in the analysis repo
([motorola-moto-e32-root](https://github.com/CreitinGameplays/motorola-moto-e32-root)).

The earlier 0001-0007 series state ("hangs at the end of setup_arch(),
before the first driver printk") was superseded: the hang was the LTO/CFI
layout (fixed by 0012) and later the Mali `power_control_init` abort
(fixed by 0017).
