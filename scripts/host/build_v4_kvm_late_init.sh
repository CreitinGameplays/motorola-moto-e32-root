#!/bin/bash
# Build v4: KVM init moved to late_initcall so the AON watchdog arm wins.
set -e
cd "$HOME/kernel-sprd"
export PATH="$HOME/toolchains/clang+llvm-11.0.1-x86_64-linux-gnu-ubuntu-20.10/bin:$PATH"

if grep -q 'DIAG_KVM_LATE_INIT' virt/kvm/arm/arm.c; then
    echo "patch already applied"
else
    if patch -p1 --forward < "$HOME/diag-kvm-late-init.patch"; then
        echo "applied with patch(1)"
    else
        echo "patch(1) failed, doing the edit with python"
        python3 - <<'PY'
import pathlib
p = pathlib.Path("virt/kvm/arm/arm.c")
s = p.read_text()
old = "module_init(arm_init);"
assert s.count(old) == 1, s.count(old)
new = ("#ifdef DIAG_KVM_LATE_INIT\n"
       "/* DIAG build only: see patches/kernel-sprd/diag-only-kvm-late-init.patch */\n"
       "late_initcall(arm_init);\n"
       "#else\n"
       "module_init(arm_init);\n"
       "#endif\n")
p.write_text(s.replace(old, new))
print("edited arm.c")
PY
    fi
fi

echo "--- initcall order in arm.c ---"
grep -n 'initcall(arm_init)\|module_init(arm_init)' virt/kvm/arm/arm.c

cp .config.diagwdt .config
echo "--- building (this takes ~15-20 min on 2 cores) ---"
make -j2 ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
    CC="clang --target=aarch64-linux-gnu-" LD=ld.lld LLVM_AR=llvm-ar LLVM_NM=llvm-nm \
    KCFLAGS="-DDIAG_WDT_ARM -DDIAG_PANIC_AFTER_INIT -DDIAG_KVM_LATE_INIT" \
    Image 2>&1 | tail -25

cp arch/arm64/boot/Image Image.v4late
cp System.map System.map.v4late
echo "--- result ---"
ls -l Image.v4late
sha256sum Image.v4late
for s in "AON watchdog armed" "kernel init complete"; do
    printf '%-28s ' "$s"
    if strings Image.v4late | grep -qF "$s"; then echo present; else echo MISSING; fi
done