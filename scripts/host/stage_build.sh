#!/bin/bash
# Build one bisection step. Usage: stage_build.sh [panic_stage] [arm_stage]
#   panic_stage 0..8  panic() there (only resets from stage 8 onwards: PSCI's
#                     restart handler is an arch_initcall)
#   arm_stage   0..8, or 9 = every stage >= 2  arm the AON watchdog there and
#                     keep booting - the only reset source before arch_initcalls
# Reuses the object tree (same KCFLAGS as the v4 build), so only init/main.c
# recompiles: seconds, not a full build.
set -e
panic_stage="${1:-0}"
arm_stage="${2:-0}"
tag="p${panic_stage}a${arm_stage}"
cd "$HOME/kernel-sprd"
export PATH="$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH"

python3 "$HOME/prepare_stage_panics.py" "$panic_stage" "$arm_stage"
grep -n -E '^#define DIAG_(PANIC_STAGE|ARM_STAGE|ARM_TIMEOUT)' include/linux/diag_stage.h
grep -c 'DIAG_ARM_HOOK' init/main.c

cp .config.diagwdt .config
make -j2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
    KCFLAGS="-DDIAG_WDT_ARM -DDIAG_PANIC_AFTER_INIT -DDIAG_KVM_LATE_INIT" \
    Image 2>&1 | tail -12

cp arch/arm64/boot/Image "Image.$tag"
echo "--- Image.$tag ---"
ls -l "Image.$tag"
sha256sum "Image.$tag"