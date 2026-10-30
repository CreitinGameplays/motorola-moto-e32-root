#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
sed -n '120,240p' drivers/watchdog/sprd_wdt_fiq.c