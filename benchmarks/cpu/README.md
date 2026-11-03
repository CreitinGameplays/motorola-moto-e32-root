# CPU benchmark results (DevCheck CPU benchmark, screenshots only)

Naming: benchmarks/cpu/<base|overclocked>_<freq><unit>_<bench_config>/*.png

- `base_1612mhz_default`   - stock CPU (both clusters capped at 1612 MHz
                              by the fused product grade, docs/21),
                              DevCheck defaults (3 iterations, 10 s cooldown)
- `base_1612mhz_sustained`  - sustained run (more iterations / no cooldown)

The 1820 MHz overclock was attempted and closed as hardware-capped
(fused DVFS engine; see docs/21 section 6) - no `overclocked_*` folders
will exist unless a different mechanism is ever found.
