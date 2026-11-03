# GPU benchmark results (DevCheck GPU benchmark, screenshots only)

Naming: benchmarks/gpu/<base|overclocked>_<freq><unit>_<bench_config>/*.png

- `base_650mhz_default`    - shipping-trim maximum (T606 GPLL 650 MHz),
                              DevCheck defaults (3 iterations, 10 s cooldown)
- `base_650mhz_sustained`  - sustained run (more iterations / no cooldown)
- `overclocked_768mhz_*`   - runtime untrim to the true 768 hardware level
                              (DVFS index 3).  RESULT: hardware-capped at
                              half rate (~384 MHz): GPU 69/71 vs 119/117,
                              all metrics -42 %.  See docs/20 section 3d.
- `gpll_rerate_768mhz_*`   - (failed) GPLL parent re-rated to 768 via the
                              clk framework + re-clamp veto: GPU 69/71,
                              compute -32 %.  Research record only.
- `overclocked_850mhz_*`   - never attempted (850 OPP stays disabled)

Keep the bench config identical between the base and overclocked runs of
the same kind (default vs sustained) for a fair comparison.

Alongside each screenshot folder, the kernel-side recorder log
(`/data/local/tmp/gpubench_<tag>.log`: uptime, devfreq cur/max freq, GPU
thermal-zone temperature every 0.5 s) is stored in the same directory as
`devfreq_gpu-thmzone_<tag>.log`.
