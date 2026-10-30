#!/bin/bash
# Build the Moto E32 (UMS9230/T606) kernel on a Linux host, with KVM enabled.
#
#   * tree   : github.com/MotorolaMobilityLLC/kernel-sprd @ R-11-release-RORS
#   * config : the phone's own /proc/config.gz + every KVM option switched on
#   * clang  : 11.0.1 (the version that built the shipping kernel)
#
# Usage (on the target box, from a checkout of the analysis repo):
#   ./scripts/host/build_kernel_vps.sh [tree-dir]
#
# The phone's shipping config has to be in the tree as "phone.config"
# (that is artifacts/kernel-config from the analysis repo).
#
# Patches are applied first when the repo's patches/ directory is reachable
# (idempotent, so re-running is safe):
#   0001  measured header delta of the shipping build
#   0002  the matching .c half (mm/rmap.c, fs/file.c, fs/file_table.c)
#   0003  build fix: drivers/devfreq/sprd include path
#   0004  build fix: drivers/staging/sprd/sfp include path
#   0005  build fix: vhost_vring_ioctl() ioctl type (needed for CONFIG_VHOST)
set -eu

TREE="${1:-$HOME/kernel-sprd}"
TC="${TC:-$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10}"
JOBS="${JOBS:-$(nproc)}"
LOG="${LOG:-$HOME/build-kvm.log}"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$(dirname "$SCRIPT_DIR")")

cd "$TREE"

# --------------------------------------------------------------- patches ----
if [ -d "$REPO/patches/kernel-sprd" ] && command -v python3 >/dev/null; then
    python3 "$REPO/scripts/host/apply_shipping_header_delta.py" --tree "$TREE"
    python3 "$REPO/scripts/host/apply_shipping_code_delta.py" --tree "$TREE"
else
    echo "note: patches/ not reachable from $0 - assuming the tree is already patched"
fi

# ---------------------------------------------------------------- config ----
if [ ! -f phone.config ]; then
    echo "phone.config missing - copy artifacts/kernel-config there" >&2
    exit 1
fi

cp phone.config .config

KVM_SYMS="VIRTUALIZATION KVM KVM_ARM_HOST KVM_ARM_PMU KVM_MMIO
KVM_GENERIC_DIRTYLOG_READ_PROTECT KVM_COMPAT KVM_VFIO
HAVE_KVM HAVE_KVM_IRQCHIP HAVE_KVM_IRQFD HAVE_KVM_IRQ_ROUTING HAVE_KVM_EVENTFD
HAVE_KVM_MSI HAVE_KVM_CPU_RELAX_INTERCEPT HAVE_KVM_ARCH_TLB_FLUSH_ALL
HAVE_KVM_INVALID_WAKEUPS HAVE_KVM_IRQ_BYPASS
VHOST VHOST_NET VHOST_VSOCK VHOST_CROSS_ENDIAN_LEGACY
VSOCKETS VFIO VFIO_PCI VFIO_PLATFORM VFIO_IOMMU_TYPE1"

for s in $KVM_SYMS; do
    if grep -rq --include='Kconfig*' -E "^(menu)?config ${s}\$" .; then
        ./scripts/config --enable "$s"
    fi
done

make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
grep -E '^CONFIG_(VIRTUALIZATION|KVM|VHOST|VSOCKETS)[A-Z0-9_]*' .config

# ----------------------------------------------------------------- build ----
export PATH="$TC/bin:$PATH"
{
    echo "=== toolchain ==="
    clang --version | head -2
    ld.lld --version | head -1
    echo "=== build start $(date) ==="
} | tee "$LOG"

set -x
make -j"$JOBS" ARCH=arm64 \
     CROSS_COMPILE=aarch64-linux-gnu- \
     CC="clang --target=aarch64-linux-gnu-" \
     LD=ld.lld \
     LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
     Image dtbs modules 2>&1 | tee -a "$LOG"
set +x

echo "=== build end $(date) ==="
ls -l arch/arm64/boot/Image vmlinux System.map
