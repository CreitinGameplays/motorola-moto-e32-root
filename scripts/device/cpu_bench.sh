#!/system/bin/sh
# Pinned busy-loop benchmark for one CPU.
# Usage: sh cpu_bench.sh <hex-mask> <iterations>
# e.g.  sh cpu_bench.sh 0x40 200000   -> cpu6 only

MASK=$1
ITERS=${2:-200000}

taskset "$MASK" sh -c "
X=0; j=0
S=\$(date +%s%N)
while [ \$j -lt $ITERS ]; do X=\$((X+j)); j=\$((j+1)); done
E=\$(date +%s%N)
awk -v s=\$S -v e=\$E 'BEGIN{printf \"bench_ms=%.0f\\n\", (e-s)/1000000}'
"
