#!/bin/bash
# Build one bisection stage. Usage: stage_build.sh <0..8>
# Reuses the object tree from the v4 build (same KCFLAGS), so only
# init/main.c recompiles: seconds to a minute, not a full build.
set -e
stage="${1:?usage: stage_build.sh <0..8>}"
cd "$HOME/kernel-sprd"
export PATH="$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH"

python3 "$HOME/prepare_stage_panics.py" "$stage"
grep -n '^#define DIAG_PANIC_STAGE' include/linux/diag_stage.h

cp .config.diagwdt .config
make -j2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
    KCFLAGS="-DDIAG_WDT_ARM -DDIAG_PANIC_AFTER_INIT -DDIAG_KVM_LATE_INIT" \
    Image 2>&1 | tail -12

cp arch/arm64/boot/Image "Image.stage${stage}"
echo "--- Image.stage${stage} ---"
ls -l "Image.stage${stage}"
sha256sum "Image.stage${stage}"