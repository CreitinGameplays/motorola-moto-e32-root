#!/system/bin/sh
# clk tree walk via the poker's clkwalk attr
P=/sys/kernel/gpu_gpll_poker
echo 0 > /proc/sys/kernel/kptr_restrict
L=$(grep -w __clk_lookup /proc/kallsyms | cut -d' ' -f1)
N=$(grep -w __clk_get_name /proc/kallsyms | cut -d' ' -f1)
echo "lookup=0x$L getname=0x$N"
echo 0x$L 0x$N > $P/clkaddr
for c in "$@"; do
    echo "$c" > $P/clkwalk
    echo "== $c =="
    cat $P/clkwalk
done
