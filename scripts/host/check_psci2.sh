#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
f=drivers/firmware/psci.c
[ -f "$f" ] && echo "== $f ==" && grep -n -E 'initcall|psci_dt_init|psci_init\(|arm_pm_restart' "$f"
echo "== machine_desc restart (arm64 setup) =="
grep -rn -E 'machine_desc->restart|setup_machine_fdt|__machine_arch_type' arch/arm64/kernel/setup.c | head
echo "== sprd reboot/restart handlers =="
grep -rn 'register_restart_handler' drivers/spi/spi-sprd-adi.c | head -3
grep -n -E 'module_platform_driver|late_initcall|subsys_initcall|device_initcall' drivers/spi/spi-sprd-adi.c | head