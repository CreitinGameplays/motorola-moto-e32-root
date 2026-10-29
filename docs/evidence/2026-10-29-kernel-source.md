Kernel source evidence - Moto E32 (hawaii), 2026-10-29
=======================================================

Full write-up: docs/10-kernel-source.md
Reports:    artifacts/kernel-src/source_vs_device.md, artifacts/kernel-src/dt_vs_tree.md


1. The public source (Motorola GPL repository)

   $ git ls-remote --heads https://github.com/MotorolaMobilityLLC/kernel-sprd.git
   c4e610cd833c47f08969678fa58f9bfcb57bd3a5  refs/heads/R-11-release-RORS

   $ git ls-remote --tags  ... | grep RORS
   ac619e614ce867b4914a9fd2371fc445f0470849  refs/tags/MMI-RORS31.193-14-6
   c4e610cd833c47f08969678fa58f9bfcb57bd3a5  refs/tags/MMI-RORS31.193-14-6^{}

   Local clone (blobless, Windows-safe checkout):
   $ powershell -File scripts/host/get_kernel_source.ps1
   [*] branch R-11-release-RORS = c4e610cd833c47f08969678fa58f9bfcb57bd3a5
   [+] 63927 files in D:\AndroidSDKTools\kernel-sprd

   The newest published tag for this platform is RORS31.193-14-6 (2022-10-25);
   the phone runs RORS31.335-58-1 (2024-02-20).


2. Version / build identity (from the phone's own IKHEADERS headers)

   artifacts/kheaders_full/include/generated/utsrelease.h
     #define UTS_RELEASE "4.14.199+-ab612c2"
   artifacts/kheaders_full/include/generated/compile.h
     #define UTS_VERSION "#0 SMP PREEMPT Tue Feb 20 11:31:04 CST 2024"
     #define LINUX_COMPILE_BY "xscm"
     #define LINUX_COMPILE_HOST "ontimbjlx020"
     #define LINUX_COMPILER "Android (6443078 based on r383902) clang version 11.0.1 ..."

   Public tree: Makefile -> VERSION=4 PATCHLEVEL=14 SUBLEVEL=199
                              NAME = "Petit Gorille"
   => 4.14.199 matches exactly.

   "612c2" is the build id of the firmware fingerprint
   (motorola/hawaii/hawaii:11/RORS31.335-58-1/612c2:user/release-keys),
   i.e. the kernel localversion is a build stamp, not a git hash.


3. Build config (public defconfig + release fragments vs /proc/config.gz)

   $ python scripts/host/compare_kernel_source.py --tree D:\AndroidSDKTools\kernel-sprd \
       --kheaders artifacts/kheaders_full --config artifacts/kernel-config \
       --defconfig artifacts/kernel-src/sprd_qogirl6_defconfig \
       --diffconfig artifacts/kernel-src/aarch64_user_diff_config \
       --diffconfig artifacts/kernel-src/ums9230_4h10_diff_config

   defconfig alone          : 3950 symbols, 64 mismatches
   defconfig + fragments    : 3941 symbols, 3878 shared, 40 mismatches
   (all 40 = debug/monitor options the production build disables, e.g.
    CONFIG_SPRD_DJTAG, CONFIG_FUNCTION_TRACER, CONFIG_KGDB_SERIAL_CONSOLE;
    plus CONFIG_TOUCHSCREEN_ILITEK_MODEL="" which only the phone has)


4. Kconfig symbol coverage

   - Kconfig symbols defined in the public tree: 17984
   - symbols used by the running kernel: 3912
   - running symbols NOT defined in the public tree: 0


5. Header-level match (tree include/ vs the phone's IKHEADERS include/)

   Before the backport:
   - identical (code, comments/whitespace normalised): 4842
   - different content: 10  -> 3 of them are a Windows case-insensitivity
     artifact (xt_CONNMARK.h vs xt_connmark.h, verified identical against
     git), so 7 are real differences:
       linux/file.h          + fget_many() / fput_many()
       linux/fs.h            get_file_rcu() -> get_file_rcu_many()
       linux/rmap.h          anon_vma.degree -> num_children/num_active_vmas
       linux/sipc.h          sbuf_copy_from_user() (Unisoc SIPC hardening)
       uapi/video/sprd_jpg.h + SPRD_JPG_MAP_SIZE 0x6000
       uapi/video/sprd_vsp.h SPRD_VSP_MAP_SIZE 0xA000 -> 0x14000
       uapi/video/sprd_sensor_k.h + SENSOR_IOC_PRIVATE_KEY / SENSOR_IO_PRI_KEY
   - only in exact build: 0

   After applying the measured delta
   (scripts/host/apply_shipping_header_delta.py /
    patches/kernel-sprd/0001-sprd-backport-rors31.335-58-1-header-delta.patch):
   - identical: 4852
   - different content: 0
   - only in exact build: 0
   - case-collision artifacts resolved from the git object store: 5
     (xt_MARK/xt_mark, xt_TCPMSS/xt_tcpmss, ipt_ECN/ipt_ecn,
      ipt_TTL/ipt_ttl, ip6t_HL/ip6t_hl - identical content on ext4)


6. Provenance of the backported hunks (upstream cross-check)

   $ curl -sL https://raw.githubusercontent.com/gregkh/linux/linux-4.19.y/include/linux/file.h
   linux-4.19.y  file.h  fget_many=True
   linux-4.19.y  fs.h    get_file_rcu_many=True
   linux-4.19.y  rmap.h  num_active_vmas=True
   linux-5.10.y  file.h  fget_many=True
   linux-5.10.y  fs.h    get_file_rcu_many=True
   linux-5.10.y  rmap.h  num_active_vmas=True
   linux-6.1.y   file.h  fget_many=False   (removed upstream again in 6.2)
   torvalds v6.9 rmap.h  num_active_vmas=True (the anon_vma rework)

   The shipped fget_many/fput_many/get_file_rcu_many declarations are
   byte-identical to the stable branches; Unisoc only deviates in the field
   order of struct anon_vma (num_children/num_active_vmas behind rb_root).
   The four uapi/video hunks and the sipc.h helper have no upstream
   equivalent - they are Unisoc specific.


7. The same delta in the shipped symbol table (artifacts/System.map, 119878 symbols)

   ffffffff8008415f5c T fput_many
   ffffffff800843fbac T fget_many

   Both exist in the running kernel and in NEITHER the public tree nor its
   git history -> the public snapshot (2022-10-25) predates the shipped
   build (2024-02-20).  Their .c implementation is not part of the header
   delta and has to be taken from upstream stable (fs/file.c).


8. Device tree (live /proc/device-tree vs the public DTS)

   $ adb shell sh /data/local/tmp/dump_device_tree.sh /data/local/tmp/dt
   $ adb pull /data/local/tmp/dt artifacts/dt-live
   $ python scripts/host/compare_device_tree.py --dt artifacts/dt-live \
       --dts .../qogirl6.dtsi --dts .../ums9230.dts --dts .../ums9230.dtsi \
       --dts .../ums9230-mach.dtsi --dts .../ums9230-modem.dtsi \
       --dts .../ums9230-wcn.dtsi --dts .../ums9230-4h10-overlay.dts \
       --dts .../sc2730.dtsi --dts .../sprd-sound-fe-be.dtsi \
       --dts .../sprd-sound-sharkl.dtsi

   - live nodes: 943, live property files: 3154
   - live 'compatible'/'model' strings: 184
   - strings present in both: 184
   - only in the live tree: 0

   Live board identity:
     /proc/device-tree/model      = "Spreadtrum UMS9230 4H10 Board"
     /proc/device-tree/compatible = "sprd,ums9230-4h10"
   which is what arch/arm64/boot/dts/sprd/ums9230-4h10-overlay.dts declares.


9. Exact build inputs extracted from the phone

   /proc/config.gz                                  -> artifacts/kernel-config
   insmod /vendor/lib/modules/kheaders.ko
     /sys/kernel/kheaders.tar.xz                    -> artifacts/kheaders.tar.xz
       (6,550 files: include/generated/autoconf.h, utsrelease.h, compile.h,
        include/config/<symbol>/**, arch/arm64/include/generated/**)
   /proc/device-tree                               -> artifacts/dt-live/
   physical kernel Image dump                       -> artifacts/kimage_ok.bin
   live kallsyms                                   -> artifacts/System.map


10. Reconstructed production config fragment

   $ python scripts/host/reconstruct_release_config.py \
       --defconfig artifacts/kernel-src/sprd_qogirl6_defconfig \
       --diffconfig artifacts/kernel-src/aarch64_user_diff_config \
       --diffconfig artifacts/kernel-src/ums9230_4h10_diff_config \
       --config artifacts/kernel-config \
       --out-fragment patches/kernel-sprd/reconstructed_release_diff_config \
       --out-config   patches/kernel-sprd/reconstructed_release.config --check

   tree config symbols : 3941
   shipping config     : 3912
   conflicts to fix    : 40  (all "disable")
   symbols only in the shipping config: 34
   verification: 0 conflict(s) left, 0 shipping symbol(s) not covered

   With that fragment the full comparison reports
   "value conflicts: 0" and "different content: 0" for the headers.


11. End-to-end run (clean public checkout -> backport -> verify)

   $ powershell -ExecutionPolicy Bypass -File scripts/host/get_kernel_source.ps1 -Verify
   [*] branch R-11-release-RORS = c4e610cd833c47f08969678fa58f9bfcb57bd3a5
   [*] applying the measured RORS31.335-58-1 header delta ...
       [+] shipping header delta fully applied
   exit=0

   Final numbers:
     build config : 0 value conflicts (defconfig + release fragments +
                    reconstructed fragment)
     Kconfig      : 17,984 symbols in the tree, 0 of the running kernel's
                    3,912 symbols missing
     headers      : 4,852 identical, 0 different, 0 build-only
     device tree  : 184/184 live strings found in the public DTS
