#!/usr/bin/env bash
# Build the Mali root exploit for 64-bit Android.
#
# The NDK is taken from ANDROID_NDK_HOME (or ANDROID_NDK_ROOT).
#
#   export ANDROID_NDK_HOME=/path/to/android-ndk
#   ./scripts/build.sh
#
# Optional overrides:
#   SOURCE=... OUT=... API=30 HOST_TAG=linux-x86_64 ./scripts/build.sh
set -euo pipefail

API="${API:-30}"
HOST_TAG="${HOST_TAG:-linux-x86_64}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${SOURCE:-$SCRIPT_DIR/mali/mali_kroot.c}"
OUT="${OUT:-$(dirname "$SCRIPT_DIR")/artifacts/mali_kroot}"

if [ -z "$NDK" ]; then
    echo "error: NDK not found: set ANDROID_NDK_HOME (or ANDROID_NDK_ROOT)" >&2
    exit 1
fi

CC="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin/aarch64-linux-android${API}-clang"
if [ ! -x "$CC" ]; then
    CC="$NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin/clang"
fi
if [ ! -x "$CC" ]; then
    echo "error: clang not found in $NDK/toolchains/llvm/prebuilt/$HOST_TAG/bin" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
"$CC" --target="aarch64-linux-android$API" -static -O2 -Wall -o "$OUT" "$SOURCE"
echo "built $OUT"
