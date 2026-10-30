#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
sed -n '300,372p' drivers/watchdog/sprd_wdt_fiq.c
echo "=== data table / compatible ==="
sed -n '460,505p' drivers/watchdog/sprd_wdt_fiq.c
echo "=== aon watchdog node in our dtb ==="
strings arch/arm64/boot/dts/*/*ums9230*.dtb 2>/dev/null | head -3
find . -name '*.dtb' -newer .config 2>/dev/null | head -5