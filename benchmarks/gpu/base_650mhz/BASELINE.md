# GPU overclock baseline (T606 trim: max 650 MHz) - 2026-11-03

Device: Moto E32 (hawaii, UMS9230/T606), kernel 4.14.199+-ab612c2 #2
(stock config + KVM + vendor-module ABI compat), Mali-G57 r0p1 via the
in-tree r28p0 DDK + qogirl6 glue.  DVFS governor simple_ondemand; the
DDK's Unisoc GPU_DVFS hook logs `min_freq=384000 max_freq=650000`.

Benchmark: DevCheck "GPU benchmark" (score = weighted; sub-scores
Graphics/Compute from GPU Scene Render, FP32 Matmul, FP16 Matmul).

## base_650mhz_default  (3 iterations x 10 s cooldown, 51 s)

    GPU score          119   (Graphics 102, Compute 188)
    GPU Scene Render   3.06 frames/s   (score 102)
    GPU FP32 Matmul    8.23 GFLOPS     (score 368)
    GPU FP16 Matmul    20.4 GFLOPS     (score 96)
    score stability    +/-0.3 %
    CPU temp peak      ~55 C   (DevCheck run timeline)
    GPU temp peak      ~48 C
    battery temp       35 C flat, charging +0 mAh

## base_650mhz_sustained  (8 iterations x 0 s cooldown, 1 m 21 s)

    GPU score          117   (Graphics 100, Compute 184)
    GPU Scene Render   3.01 frames/s   (score 100)
    GPU FP32 Matmul    7.78 GFLOPS     (score 347)
    GPU FP16 Matmul    20.7 GFLOPS     (score 98)
    score stability    +/-0.2 %
    CPU temp peak      ~62 C
    GPU temp peak      ~51 C
    battery temp       36 C flat

No throttling at 650 MHz: the score holds across all 8 back-to-back
iterations (stability +/-0.2 %), which is the safety baseline the 768/
850 MHz runs get compared against.

## Kernel-side facts for the experiment

* the DDK's devfreq bookkeeping already knows the FULL untrimmed table -
  `/sys/class/devfreq/23100000.gpu/trans_stat` lists 850/768/614.4/512/384
  MHz - while `available_frequencies` shows the trimmed list
  (384/512/614.4/650) and the runtime ceiling is the T606 GPLL trim
  (`mali_freq_init` rewrites the 850 entry to 650 and drops 768;
  `mali_clock_on` clamps the GPLL source with `clk_set_rate(..., 650 MHz)`).
* so the experiment is: skip the trim (module parameter), which exposes
  768 and 850 MHz @ 800 mV (the DTS levels used by T615/T620 on the same
  Mali-G57 MP1 silicon).

Screenshots: `base_650mhz_default/`, `base_650mhz_sustained/`.
