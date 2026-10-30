#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
echo "=== initcall that installs the arm64 restart handler ==="
grep -rn -E 'psci_dt_init|arm_pm_restart|__init psci|initcall' arch/arm64/kernel/psci.c | tail -20
echo
echo "=== machine_restart / restart handler in arch/arm64 ==="
grep -rn -E 'machine_restart|do_kernel_restart|pm_power_off|restart' arch/arm64/kernel/process.c arch/arm64/kernel/setup.c | head -20
echo
echo "=== does our dtb/driver register an early restart? ==="
grep -rn -E 'register_restart_handler' drivers/soc/sprd/ drivers/ 2>/dev/null | grep -i -E 'sprd|sysdump|reboot' | head -10