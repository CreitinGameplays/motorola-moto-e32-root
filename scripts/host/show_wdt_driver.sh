#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
echo "===== register defines ====="
sed -n '1,120p' drivers/watchdog/sprd_wdt_fiq.c
echo "===== enable / set_timeout / start / probe ====="
grep -n -E 'sprd_wdt_fiq_(enable|set_timeout|start|stop|probe)|clk_|regmap|raw_writel|writel' drivers/watchdog/sprd_wdt_fiq.c | head -60