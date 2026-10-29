#!/system/bin/sh
# Dump the live flattened device tree (/proc/device-tree) from the running
# kernel into a pullable directory tree.
#
# The kernel exports the DTB as a directory tree: every property is a file,
# every directory is a node. Property values are big-endian binary, so they
# are copied byte-exact here and decoded on the host.
#
# Needs root (SELinux blocks /proc/device-tree for the adb shell otherwise).
# Usage: adb shell sh /data/local/tmp/dump_device_tree.sh [outdir]
set -u
OUT=${1:-/data/local/tmp/dt}
rm -rf "$OUT" 2>/dev/null
mkdir -p "$OUT"
cd /proc/device-tree || exit 1

# copy properties (regular files), recreate directories
find . -type d | while read -r d; do
	mkdir -p "$OUT/$d"
done
find . -type f | while read -r f; do
	cp "$f" "$OUT/$f" 2>/dev/null
done

echo "id: $(id)"
echo "out: $OUT"
echo "nodes: $(find "$OUT" -type d | wc -l)"
echo "props: $(find "$OUT" -type f | wc -l)"
echo "--- model ---"
cat /proc/device-tree/model 2>/dev/null; echo
echo "--- compatible ---"
cat /proc/device-tree/compatible 2>/dev/null; echo
echo "--- chosen ---"
cat /proc/device-tree/chosen/bootargs 2>/dev/null; echo
