#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
echo "--- key anchors in init/main.c ---"
grep -n -E 'start_kernel\(void\)|static int __ref kernel_init|void __init setup_arch|do_basic_setup\(void\)|do_pre_smp_initcalls\(void\)|do_initcalls\(void\)|kernel_init_freeable\(void\)|^void __init mm_init|^void __init sched_init|^	rest_init\(\)|^	do_basic_setup\(\)|^	do_pre_smp_initcalls\(\)' init/main.c
echo "--- start_kernel body, first 40 lines ---"
awk '/^asmlinkage __visible void __init start_kernel\(void\)/{f=1;n=0} f{print NR": "$0; n++; if(n>40) exit}' init/main.c
echo "--- kernel_init body ---"
awk '/^static int __ref kernel_init\(void \*unused\)/{f=1;n=0} f{print NR": "$0; n++; if(n>45) exit}' init/main.c