#!/bin/bash
# Build the vendor-module-compatible kernel (camera/BT/FM/SAR vendor-module
# ABI, Mali/WLAN/BT modules, KVM) by delegating to the kernel repo's own
# build.sh - that script is the canonical, maintained recipe:
#
#   * recovers the shipping .config (stock_kernel_config.txt in the tree)
#   * disables LTO/CFI (they hang this board), keeps the module ABI
#   * builds Image + modules in one go
#   * copies Image, mali_kbase.ko, sprdwl_ng.ko, sprdbt_tty.ko,
#     Module.symvers, kernel.config and SHA256SUMS into $STABLE
#     (default ~/kernel-out)
#
# Usage:
#   ./scripts/host/vps_build_cameracompat.sh [kernel-tree-dir]
#
# Env passthrough (see the kernel tree's build.sh for the full list):
#   KERNEL_TREE  kernel checkout (default: $1, then ~/kernel-sprd)
#   TOOLCHAIN / CONFIG / OUT / STABLE  forwarded unchanged
set -eu

KERNEL_TREE="${1:-${KERNEL_TREE:-$HOME/kernel-sprd}}"
if [ ! -x "$KERNEL_TREE/build.sh" ]; then
    echo "FATAL: $KERNEL_TREE/build.sh not found." >&2
    echo "  Pass the kernel checkout as an argument or set KERNEL_TREE=..." >&2
    exit 1
fi
exec bash "$KERNEL_TREE/build.sh"
