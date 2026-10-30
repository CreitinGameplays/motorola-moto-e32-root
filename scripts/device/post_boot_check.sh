#!/system/bin/sh
# Post-boot check after running the custom kernel from slot a.
# Saves a report under /data/local/tmp and prints the essentials.
set -u

out=/data/local/tmp/post_boot_report.txt
{
echo "=== identity ==="
getprop ro.boot.slot_suffix
getprop ro.boot.verifiedbootstate
getprop ro.build.fingerprint
getprop sys.boot_completed
cat /proc/version
cat /proc/cmdline
echo
echo "=== uptime / load ==="
uptime
echo
echo "=== KVM ==="
ls -l /dev/kvm 2>&1
grep -i kvm /proc/misc 2>&1
grep -i -E "kvm|hyp" /proc/modules 2>&1
dmesg 2>/dev/null | grep -i -E "kvm|hyp|virtualization" | tail -40
echo
echo "=== module load failures (CRC / vermagic / exec format) ==="
dmesg 2>/dev/null | grep -i -E "disagrees about version|Unknown symbol|exec format error|invalid module|no symbol version|crc" | tail -60
echo
echo "=== loaded modules count ==="
wc -l /proc/modules 2>&1
echo
echo "=== notable kernel errors ==="
dmesg 2>/dev/null | grep -i -E "panic|Oops|BUG:|Unable to handle|Call trace" | tail -40
echo
echo "=== init / mount state ==="
mount 2>/dev/null | grep -E " /(system|vendor|data|product) " 
} > "$out" 2>&1

cat "$out"
echo
echo "report saved to $out"