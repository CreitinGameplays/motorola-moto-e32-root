# GPU benchmark results (DevCheck GPU benchmark, screenshots only)

Naming: benchmarks/gpu/<base|overclocked>_<freq><unit>_<bench_config>/*.png

- `base_650mhz_default`    - shipping-trim maximum (T606 GPLL 650 MHz),
                              DevCheck defaults (3 iterations, 10 s cooldown)
- `base_650mhz_sustained`  - sustained run (more iterations / no cooldown)
- `overclocked_768mhz_*`   - untrimmed level 4 (768 MHz @ 800 mV)
- `overclocked_850mhz_*`   - untrimmed level 5 (850 MHz @ 800 mV)

Keep the bench config identical between the base and overclocked runs of
the same kind (default vs sustained) for a fair comparison.

Alongside each screenshot folder, the kernel-side recorder log
(`/data/local/tmp/gpubench_<tag>.log`: uptime, devfreq cur/max freq, GPU
thermal-zone temperature every 0.5 s) is stored in the same directory as
`devfreq_gpu-thmzone_<tag>.log`.
