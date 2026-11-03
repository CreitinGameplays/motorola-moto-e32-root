#!/bin/bash
# Build the kernel with the recovered stock config (LTO/CFI off so it can boot)
# into /tmp/kbuild, only to obtain Module.symvers (CRC table) for comparison
# against the vendor modules.  The source tree stays clean: the config lives
# in the output directory.
set -e
cd ~/kernel-sprd
export PATH=~/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH
OUT=/tmp/kbuild
rm -rf "$OUT"
mkdir -p "$OUT"
cp ~/stock_kernel_config.txt "$OUT/.config"
scripts/config --file "$OUT/.config" --disable LTO_CLANG --disable LTO \
	--enable LTO_NONE --disable CFI_CLANG --disable CFI
M="make O=$OUT ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- CC=clang LD=ld.lld LLVM_AR=llvm-ar LLVM_NM=llvm-nm OBJDUMP=llvm-objdump"
$M olddefconfig
$M -j2 Image
ls -la "$OUT/Module.symvers" "$OUT/arch/arm64/boot/Image"
echo DONE
