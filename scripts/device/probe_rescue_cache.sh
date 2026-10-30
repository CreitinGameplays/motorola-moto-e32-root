#!/system/bin/sh
# Can /cache hold the stock boot_b blob for a rescue initramfs to restore?
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"

echo "=== /cache free space ==="
df -h /cache 2>/dev/null

echo "=== /cache contents ==="
ls -la /cache 2>/dev/null | head -20

echo "=== write test (root, ext4 rw) ==="
if echo rescue-probe >/cache/opencode_probe.txt 2>/dev/null; then
    echo "write OK: $(cat /cache/opencode_probe.txt)"
    rm -f /cache/opencode_probe.txt
else
    echo "write FAILED"
fi

echo "=== misc 0x800..0x840 (A/B metadata) ==="
dd if=/dev/block/by-name/misc bs=1 skip=2048 count=64 2>/dev/null | od -An -tx1 -v

echo "=== misc 0x000..0x040 (BCB command area) ==="
dd if=/dev/block/by-name/misc bs=1 count=64 2>/dev/null | od -An -tx1 -v

echo "=== ls -lZ /cache ==="
ls -ldZ /cache 2>/dev/null
getenforce 2>/dev/null