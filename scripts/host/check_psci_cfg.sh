#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
for f in .config.diagstock .config.diagwdt phone.config; do
    echo "=== $f ==="
    grep -E '^CONFIG_(ARM_PSCI|ARM64_VA_BITS|ARM64_4K_PAGES|ARM64_64K_PAGES|ARM64_16K|ARM64_SW_TTBR0_PAN|ARM64_RELOCATABLE|RANDOMIZE_BASE)' "$f" 2>/dev/null
done
echo "=== stock reference (from the device, artifacts/kernel-build/stock_config.txt was not uploaded) ==="