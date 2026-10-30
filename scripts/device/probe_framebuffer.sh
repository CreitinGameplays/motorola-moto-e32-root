#!/system/bin/sh
# Investigate the bootloader's framebuffer: is it still scanned out, and can
# the kernel write to it?  Read-only part: DT nodes + iomem.
#
# Run as root (mali_kroot first).

RM=/sys/firmware/devicetree/base/reserved-memory

dump_node() {
    echo "== $1"
    for f in "$RM/$1"/*; do
        [ -e "$f" ] || continue
        printf '   %-16s %s\n' "$(basename "$f")" \
            "$(cat "$f" 2>/dev/null | head -c 160 | tr -d '\000')"
    done
}

dump_node 'logobuffer@9e000000'
dump_node 'framebuffer-mem@fd380000'
dump_node 'sysdump-uboot@9f000000'

echo
echo "--- reg (address,size as u32 cells) ---"
for d in 'logobuffer@9e000000' 'framebuffer-mem@fd380000' 'sysdump-uboot@9f000000'; do
    [ -e "$RM/$d/reg" ] || continue
    echo "$d"
    od -An -tx4 "$RM/$d/reg"
done

echo
echo "--- /proc/iomem hits ---"
grep -iE '9e000000|9f000000|fd380000|System RAM' /proc/iomem | head -20

echo
echo "--- lcd/logobuffer cmdline ---"
tr ' ' '\n' < /proc/cmdline | grep -iE 'lcd|logo|framebuffer'

echo
echo "--- dpu / drm status ---"
cat /sys/class/drm/card0/device/uevent 2>/dev/null | head -5
ls /sys/kernel/debug/dri 2>/dev/null

echo
echo "--- memory total ---"
head -3 /proc/meminfo