#!/bin/bash
cd "$HOME/kernel-sprd" || exit 1
sed -n '560,600p;700,760p;1030,1040p;1100,1130p' init/main.c | cat -n
echo "=== grep ==="
grep -n -E '^	(mm_init|sched_init|rest_init|do_pre_smp_initcalls|do_basic_setup|rcu_init|local_irq_enable)\(\)|^#include' init/main.c | head -40