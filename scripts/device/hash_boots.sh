#!/system/bin/sh
# Verify no partition changed behind our back (fastboot boot must not write).
set -u
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "root failed"; exit 1; }
for p in boot_a boot_b; do
    l=$(readlink -f /dev/block/by-name/$p)
    echo "--- $p"
    dd if="$l" bs=4096 2>/dev/null | sha256sum
done