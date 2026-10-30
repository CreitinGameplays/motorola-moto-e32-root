#!/bin/bash
# Build a QEMU-testable Image from the same tree/config as the device build.
#
# The device config has no PL011 UART (the phone uses SPRD's UART at 0x70...),
# so a QEMU `virt` boot would be silent.  Adding CONFIG_SERIAL_AMBA_PL011 and
# its console gives us a real kernel log from the very first printk, which is
# exactly what the phone cannot provide (its console is on ttyS1, unwired).
#
# The diag knobs are forced to 0 first: with DIAG_SMC_STAGE=1 the kernel would
# sit in an SMC SYSTEM_RESET loop under QEMU (where PSCI works!).
set -e
cd "$HOME/kernel-sprd"
export PATH="$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH"

python3 "$HOME/prepare_stage_panics.py" 0 0 0
grep -E '^#define DIAG_' include/linux/diag_stage.h

cp .config.diagwdt .config
./scripts/config --enable ARM_AMBA \
                 --enable SERIAL_AMBA_PL011 \
                 --enable SERIAL_AMBA_PL011_CONSOLE \
                 --enable SERIAL_EARLYCON
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig >/dev/null
grep -E 'CONFIG_(ARM_AMBA|SERIAL_AMBA_PL011|SERIAL_EARLYCON)=' .config

make -j2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
    KCFLAGS="-DDIAG_WDT_ARM -DDIAG_PANIC_AFTER_INIT -DDIAG_KVM_LATE_INIT" \
    Image 2>&1 | tail -8

cp arch/arm64/boot/Image Image.qemu
ls -l Image.qemu
sha256sum Image.qemu
cp .config .config.qemu