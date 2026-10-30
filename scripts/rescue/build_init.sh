#!/bin/sh
# Build the rescue init for aarch64 on the VPS (static, freestanding, no libc).
set -e
TC="$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin"
CC="$TC/clang"
SRC="${1:-$HOME/rescue/rescue_init.c}"
OUT="${2:-$HOME/rescue/out}"
mkdir -p "$OUT"

FLAGS="--target=aarch64-linux-gnu -O2 -ffreestanding -nostdlib -static
 -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables
 -mgeneral-regs-only -fuse-ld=lld -Wl,-e,_start"

# shellcheck disable=SC2086
$CC $FLAGS -o "$OUT/rescue_init_dry" "$SRC"
# shellcheck disable=SC2086
$CC $FLAGS -DRESCUE_RESTORE -o "$OUT/rescue_init_restore" "$SRC"

ls -l "$OUT"
for f in "$OUT"/rescue_init_dry "$OUT"/rescue_init_restore; do
    echo "--- $f ---"
    "$TC/llvm-readelf" -h "$f" 2>/dev/null | sed -n '1,12p' || true
    "$TC/llvm-size" "$f" 2>/dev/null || true
done
sha256sum "$OUT"/rescue_init_dry "$OUT"/rescue_init_restore