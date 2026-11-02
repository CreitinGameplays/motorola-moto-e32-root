
import sys

p = sys.argv[1]
s = open(p, encoding='utf-8').read()

BS = chr(92)  # backslash
NL = BS + 'n'  # literal \n in C source

subs = [
 ('\tdev_info(dev, "MDBG: freq_init: top-force-shutdown lookup' + NL + '");', '\tmdbg_crumb(10);'),
 ('\tdev_info(dev, "MDBG: freq_init: gpu_top_state lookup' + NL + '");', '\tmdbg_crumb(11);'),
 ('\tdev_info(dev, "MDBG: freq_init: topdvfs-controller lookup' + NL + '");', '\tmdbg_crumb(12);'),
 ('\tdev_info(dev, "MDBG: freq_init: gpu-apb-syscon lookup' + NL + '");', '\tmdbg_crumb(13);'),
 ('\tdev_info(dev, "MDBG: freq_init: gpu-dvfs-apb-syscon lookup' + NL + '");', '\tmdbg_crumb(14);'),
 ('\tdev_info(dev, "MDBG: freq_init: gpu_bin nvmem read' + NL + '");', '\tmdbg_crumb(15);'),
 ('\tdev_info(dev, "MDBG: freq_init: of_clk_get 0..3' + NL + '");', '\tmdbg_crumb(16);'),
 ('\tdev_info(dev, "MDBG: freq_init: %u src clocks fetched' + NL + '",\n\t\t gpu_dvfs_ctx.gpu_clk_num);', '\tmdbg_crumb(17);'),
 ('\tdev_info(kbdev->dev, "MDBG: platform_init enter' + NL + '");', '\tmdbg_crumb(20);'),
 ('\tdev_info(kbdev->dev, "MDBG: platform_init: freq_init done' + NL + '");', '\tmdbg_crumb(21);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: power_on: top_force write enter' + NL + '");', '\tmdbg_crumb(22);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: power_on: top_force write done' + NL + '");', '\tmdbg_crumb(23);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: power_on: top_pwr_state_check enter' + NL + '");', '\tmdbg_crumb(24);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: power_on: top_pwr_state_check done' + NL + '");', '\tmdbg_crumb(25);'),
 ('\tdev_info(kbdev->dev, "MDBG: platform_init: power_on done' + NL + '");', '\tmdbg_crumb(26);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: efuse=%s' + NL + '",', '\tmdbg_crumb(27);'),
 ('\t\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: src[%d] enable' + NL + '", i);', '\t\tmdbg_crumb(28 + (i & 7));'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: gate enables (i/core/mem/sys)' + NL + '");', '\tmdbg_crumb(36);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: gate enables done' + NL + '");', '\tmdbg_crumb(37);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: top_pwr_state_check' + NL + '");', '\tmdbg_crumb(38);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: top_pwr_state_check done' + NL + '");', '\tmdbg_crumb(39);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: freq_upd_cfg write' + NL + '");', '\tmdbg_crumb(40);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: dvfs_index_cfg write' + NL + '");', '\tmdbg_crumb(41);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: qos_config' + NL + '");', '\tmdbg_crumb(42);'),
 ('\tdev_info(gpu_dvfs_ctx.dev, "MDBG: clock_on: done' + NL + '");', '\tmdbg_crumb(43);'),
]

count = 0
for anchor, crumb in subs:
    if anchor not in s:
        print('MISS:', anchor[:60])
        continue
    s = s.replace(anchor, anchor + '\n' + crumb, 1)
    count += 1

open(p, 'w', encoding='utf-8', newline='').write(s)
print('applied', count, 'of', len(subs))
