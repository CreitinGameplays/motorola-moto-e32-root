#!/system/bin/sh
# Find the bootloader's logo buffer: is 0x9e000000 (lcd_base) readable, and
# does it contain a non-blank image while Android is running?
#
# Root required (mali_kroot first).

BASE=9e000000
ALT=fd380000

echo "--- reserved-memory parent cells ---"
P=/sys/firmware/devicetree/base/reserved-memory
printf 'address-cells: %s\n' "$(od -An -tu4 "$P/#address-cells" 2>/dev/null)"
printf 'size-cells   : %s\n' "$(od -An -tu4 "$P/#size-cells" 2>/dev/null)"
echo "--- raw reg bytes (big-endian cells) ---"
for d in 'logobuffer@9e000000' 'framebuffer-mem@fd380000' 'sysdump-uboot@9f000000'; do
    printf '%-28s ' "$d"
    od -An -tx1 "$P/$d/reg" 2>/dev/null | tr -d '\n'
    echo
done
echo "--- properties present in logobuffer node ---"
ls "$P/logobuffer@9e000000" 2>/dev/null

echo
echo "--- /dev/mem present? ---"
ls -l /dev/mem 2>&1

echo
echo "--- 64 bytes at phys $BASE via /dev/mem ---"
dd if=/dev/mem bs=64 skip=$((0x$BASE / 64)) count=1 2>&1 | od -An -tx1 | head -4

echo
echo "--- 64 bytes at phys $ALT via /dev/mem ---"
dd if=/dev/mem bs=64 skip=$((0x$ALT / 64)) count=1 2>&1 | od -An -tx1 | head -4

echo
echo "--- scratch: does /dev/mem write work? (write/read at 0x9e000000) ---"
# read 16 bytes, then write them back unchanged: only proves write permission.
dd if=/dev/mem bs=16 skip=$((0x$BASE / 16)) count=1 2>/dev/null > /data/local/tmp/fb16.bin
dd if=/data/local/tmp/fb16.bin of=/dev/mem bs=16 seek=$((0x$BASE / 16)) count=1 2>&1
echo "write rc=$?"