#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
for f in .config .config.diagstock .config.diagwdt .config.diag phone.config; do
    [ -f "$f" ] || continue
    p=$(grep -m1 '^CONFIG_PANIC_TIMEOUT=' "$f")
    h=$(grep -m1 '^CONFIG_BOOTPARAM_HUNG_TASK_PANIC=' "$f")
    s=$(grep -m1 '^CONFIG_BOOTPARAM_SOFTLOCKUP_PANIC=' "$f")
    d=$(grep -m1 '^CONFIG_DETECT_HUNG_TASK=' "$f")
    printf '%-20s %-24s %-8s %-8s %-8s\n' "$f" "${p:--}" "${h:--}" "${s:--}" "${d:--}"
done
echo "--- build progress ---"
tail -3 "$HOME/build_v4.log" 2>/dev/null