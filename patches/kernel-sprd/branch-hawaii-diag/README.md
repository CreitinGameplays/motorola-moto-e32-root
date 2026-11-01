# branch-hawaii-diag - local kernel changes, as an applicable series

Snapshot of the `hawaii-diag` branch of our Moto E32 kernel tree
(`~/kernel-sprd` on the build VM), exported with `git format-patch` against the
vendor OSS drop it is based on.  Applying this series to a pristine checkout
reproduces that branch **byte for byte** (verified with `git am` + tree-hash
comparison, `0` files different).

    base    MotorolaMobilityLLC/kernel-sprd
            branch R-11-release-RORS, commit c4e610cd833c ("Add design file")
    series  0001..0007
    tag     hawaii-diag-20261101

## Applying

    git clone https://github.com/MotorolaMobilityLLC/kernel-sprd.git
    cd kernel-sprd
    git checkout c4e610cd833c
    git am /path/to/000[1-7]-*.patch

`hawaii-diag-full.diff` is the same change as one flat diff (`git diff
c4e610cd..HEAD`), for reading or `git apply`.

## Contents

| patch | what |
| --- | --- |
| 0001 | `.gitignore`: ignore the tree's own build outputs (`Image.*`, `System.map.*`, `*.dtbo`, `*.symversions`, `localversion`, reconstructed configs) |
| 0002 | build fixes for the OSS drop: `-I$(src)` for `drivers/devfreq/sprd` and `drivers/staging/sprd/sfp`, `vhost_vring_ioctl()` takes `unsigned int` |
| 0003 | backports the RORS userspace expects: `fget_many()`/`fput_many()` with the refcount-recheck loop, and the `anon_vma` `num_children`/`num_active_vmas` split |
| 0004 | `sipc: sbuf_copy_from_user()` - a `copy_from_user()` that does not zero the tail of a partially copied shared-memory block |
| 0005 | SPRD uapi ABI: `SPRD_JPG_MAP_SIZE`, `SPRD_VSP_MAP_SIZE` 0x14000, `SENSOR_IO_PRI_KEY` |
| 0006 | **DIAG only**: on-panel boot tracing (framebuffer text console, paint bands, milestone line, printk mirror, AON watchdog arm, late KVM init) |
| 0007 | the generated `diag_stage.h`/`diag_font.h` snapshot that built the last test image, plus `diag/README.md` and the device's `phone.config` |

`phone.config` is the vendor kernel configuration read off the phone
(`/proc/config.gz`); the OSS drop does not ship it.  Line endings were
normalised to LF so the patch series is exact.

## State

The 4.14.199 build reaches the end of `setup_arch()` (milestone line
`15 16 17 18 19`) and then hangs, before the first driver `printk`.  Stock
4.14.199 boots on the same device.  Full investigation:
`docs/evidence/2026-10-30-custom-kernel-hang.txt`.
