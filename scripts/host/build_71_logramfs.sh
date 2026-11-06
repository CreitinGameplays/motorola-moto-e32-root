#!/bin/sh
# Build the 7.1 flash-test initramfs: a tiny cpio.gz whose /init is
# scripts/host/logsave.c (dump the kernel ring into the sysdumpdb
# partition, then reboot into the boot_a rescue path).
#
# Run on the VPS (needs gcc + aarch64-linux-gnu-gcc and the kernel's
# gen_init_cpio host tool):
#   ./scripts/host/build_71_logramfs.sh [workdir]
#
# Output: <workdir>/71_logramfs.cpio.gz (a few kB)
set -eu

WORK="${1:-$HOME/71logramfs}"
HERE="$(cd "$(dirname "$0")" && pwd)"
KROOT="${KROOT:-$HOME/linux-ums9230}"

mkdir -p "$WORK"
cd "$WORK"

[ -f "$HERE/logsave.c" ] || { echo "missing: $HERE/logsave.c" >&2; exit 1; }

if [ ! -x gen_init_cpio ]; then
	gcc -O2 -o gen_init_cpio "$KROOT/usr/gen_init_cpio.c"
fi

aarch64-linux-gnu-gcc -static -Os -Wall -o init "$HERE/logsave.c"
aarch64-linux-gnu-strip init
ls -l init

cat > cpio.list <<EOF
dir /dev 0755 0 0
nod /dev/console 0600 0 0 c 5 1
nod /dev/kmsg 0600 0 0 c 1 11
dir /sys 0755 0 0
file /init $PWD/init 0755 0 0
EOF

./gen_init_cpio cpio.list > 71_logramfs.cpio
gzip -9 -c 71_logramfs.cpio > 71_logramfs.cpio.gz
rm -f 71_logramfs.cpio
sha256sum 71_logramfs.cpio.gz
ls -l 71_logramfs.cpio.gz
