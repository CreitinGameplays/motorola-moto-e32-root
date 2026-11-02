<#
.SYNOPSIS
    Load a locally built mali_kbase.ko on a live device and capture exactly
    where the Mali bring-up dies.

.DESCRIPTION
    The built-in Mali driver hung the kernel before adb came up, so there was
    no way to see which glue step (syscon / clocks / PLL trim / QoS / DDK
    probe) deadlocked. This script keeps the kernel Mali-free, then loads the
    very same driver as a module from a running Android and streams dmesg to
    the host while it initialises:

      - a live device keeps adb and the log even if the probe hangs
      - the last line received is the step that killed it

    Order matters:
      1. disable the SPRD native hang monitor (`echo off > /proc/monitor_enable`)
         so its ~148 s "boot did not complete" panic cannot fire mid-probe
         (Android will NOT complete boot: SurfaceFlinger has no /dev/mali0)
      2. snapshot dmesg, push + hash-check the .ko
      3. start `dmesg -w` **before** insmod, writing straight to the evidence
         file on the host
      4. insmod, then report module state

.PARAMETER Ko
    Local path to mali_kbase.ko (built with CONFIG_MALI_MIDGARD=m).

.PARAMETER CrumbKo
    Local path to mdbg_crumb.ko (flash-persistent breadcrumb recorder).
    When given, it is loaded first and its armed state is verified by
    reading miscdata+0xA0000 on the device.

.PARAMETER WaitSeconds
    Seconds to wait for adb before giving up (default 300; a normal boot needs
    ~40 s).

.PARAMETER ProbeSeconds
    Seconds to keep watching after insmod (default 90).

.PARAMETER NoMonitorOff
    Keep the SPRD hang monitor running. By default it is left ENABLED on
    purpose now: on a non-boot_completed system it panics at ~148 s, which
    warm-resets the phone and leaves the dmesg breadcrumbs in ramoops
    (pstore) - the only post-mortem channel that survives this hang.
    Pass -NoMonitorOff only when the device must stay up for interactive
    debugging despite the hang.

.PARAMETER Out
    Evidence file; the live dmesg stream is written next to it as
    `<Out>.dmesg-stream.txt`.

.EXAMPLE
    .\scripts\host\mali_module_probe.ps1 -Ko artifacts\kernel-build\mali_kbase.ko `
        -Out docs\evidence\2026-11-02-mali-module-probe.txt
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Ko,
    [string]$CrumbKo,
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [int]$WaitSeconds = 300,
    [int]$ProbeSeconds = 90,
    [switch]$AfterReboot,
    [switch]$NoMonitorOff,
    [string]$Out
)

$ErrorActionPreference = 'Continue'
if (-not (Test-Path $Ko)) { throw "module not found: $Ko" }
if (-not $Out) { $Out = "docs\evidence\$((Get-Date -Format 'yyyy-MM-dd'))-mali-module-probe.txt" }
$streamOut = "$Out.dmesg-stream.txt"

$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }
function Save { $lines | Set-Content -Path $Out -Encoding utf8 }
function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).TrimEnd() }
function Shu([string]$cmd) { (& $Adb shell "su -c `"$cmd`"" 2>&1 | Out-String).TrimEnd() }
function AdbUp { (((& $Adb devices 2>&1 | Out-String) -split "`r?`n") | Where-Object { $_ -match '\sdevice\s*$' }).Count -gt 0 }

$koBytes = (Get-Item $Ko).Length
$koHash = (Get-FileHash $Ko -Algorithm SHA256).Hash.ToLower()
$remoteKo = '/data/local/tmp/mali_kbase.ko'

Log ("mali module probe, " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Log "module : $Ko"
Log "         $koBytes bytes, sha256 $koHash"
Log ""

Log "--- 1. wait for adb ---"
if ($AfterReboot) {
    # The caller just issued `adb reboot`; the running Android still answers
    # for a moment. Wait for the link to drop first, otherwise the probe would
    # run against the old kernel and report a bogus success.
    $td = Get-Date
    $dropped = $false
    while (((Get-Date) - $td).TotalSeconds -lt 90) {
        if (-not (AdbUp)) { $dropped = $true; break }
        Start-Sleep -Seconds 2
    }
    Log ("adb dropped after " + [int]((Get-Date) - $td).TotalSeconds + "s: " + $dropped)
}
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $WaitSeconds) {
    if (AdbUp) { break }
    Start-Sleep -Seconds 3
}
$el = [int]((Get-Date) - $t0).TotalSeconds
if (-not (AdbUp)) {
    Log "ABORT: adb never came up within $WaitSeconds s"
    Save; exit 1
}
Log "adb up after ${el}s"
Start-Sleep -Seconds 2

Log ""
Log "--- 2. pre-flight ---"
$suUid = (Sh 'su -c id -u' -split "`n" | Select-Object -Last 1).Trim()
Log "su uid            : $suUid"
if ($suUid -ne '0') { Log "ABORT: no persistent root (module loading needs it)"; Save; exit 2 }
Log "kernel            : $(Sh 'cat /proc/version')"
Log "slot              : $(Sh 'getprop ro.boot.slot_suffix')"
Log "selinux           : $(Sh 'getenforce')"
Log "/dev/mali0        : $(Sh 'ls -l /dev/mali0 2>&1')"
Log "mali in modules   : $(Sh 'grep -c mali /proc/modules 2>/dev/null')"

Log ""
Log "--- 3. SPRD hang monitor (left ENABLED: its ~148 s panic warm-resets the phone and pushes the dmesg breadcrumbs into ramoops/pstore, which is the only post-mortem channel that survives this hang) ---"
Log "monitor state    : $(Sh 'cat /proc/monitor_enable 2>&1')"
if ($NoMonitorOff) {
    Log "keeping the monitor enabled"
} else {
    Log "note: on a hung CPU the monitor thread dies too - the reset then comes from the rescue path, and pstore may be empty; the on-device dmesg file below is the primary evidence"
}

# 4. on-device dmesg ring capture: this survives an adb drop and a manual
#    power-cycle ONLY if the filesystem syncs first; started before insmod
#    and synced continuously by `dmesg -w >>` with stdbuf.
Log ""
Log "--- 4. push the module ---"
$push = (& $Adb push $Ko $remoteKo 2>&1 | Out-String).Trim()
Log $push
$devHash = (Sh "sha256sum $remoteKo | awk '{print `$1}'").ToLower()
Log "device sha256     : $devHash"
if ($devHash -ne $koHash) { Log "ABORT: push hash mismatch"; Save; exit 3 }

if ($CrumbKo) {
    if (-not (Test-Path $CrumbKo)) { Log "ABORT: crumb module not found: $CrumbKo"; Save; exit 3 }
    $crumbHash = (Get-FileHash $CrumbKo -Algorithm SHA256).Hash.ToLower()
    $remoteCrumb = '/data/local/tmp/mdbg_crumb.ko'
    (& $Adb push $CrumbKo $remoteCrumb 2>&1 | Out-Null) | Out-Null
    $crumbDev = (Sh "sha256sum $remoteCrumb | awk '{print `$1}'").ToLower()
    Log "crumb module      : $CrumbKo"
    Log "crumb sha256      : $crumbDev"
    if ($crumbDev -ne $crumbHash) { Log "ABORT: crumb push hash mismatch"; Save; exit 3 }

    # Zero the scratch area first (the shell helper's step 0), then load the
    # recorder and verify the magic landed on flash.
    Log "crumb area before : $(Shu 'dd if=/dev/block/by-name/miscdata bs=1 skip=655360 count=16 2>/dev/null | od -An -c | head -1')"
    Log "crumb insmod      : $(Shu "insmod $remoteCrumb; echo RC=\`$?")"
    Log "crumb area after  : $(Shu 'dd if=/dev/block/by-name/miscdata bs=1 skip=655360 count=16 2>/dev/null | od -An -c | head -1')"
    $armed = Shu "dd if=/dev/block/by-name/miscdata bs=1 skip=655360 count=7 2>/dev/null"
    Log "crumb armed check : $armed"
    if ($armed -notmatch 'CRUMB01') {
        Log "ABORT: crumb recorder did not arm (magic not on flash); not loading mali"
        Save; exit 4
    }
}

Sh "su -c 'dmesg -c > /dev/null'" | Out-Null
Log ""
Log "--- 5. streaming dmesg to $streamOut (host) AND /data/local/tmp/mali_probe.log (device), then insmod ---"
Log "    (on a hang: power-cycle; the rescue restores Android and the on-device log is the primary evidence)"
# On-device log: dmesg -w appends continuously; run it under nohup so it keeps
# running even if its parent (this adb shell) dies with the USB link.
Sh "su -c 'rm -f /data/local/tmp/mali_probe.log; nohup sh -c \"dmesg -w >> /data/local/tmp/mali_probe.log\" > /dev/null 2>&1 &'" | Out-Null
$stream = Start-Process -FilePath $Adb -ArgumentList @('shell', 'su -c "dmesg -w"') `
    -RedirectStandardOutput $streamOut -RedirectStandardError "$streamOut.err" `
    -NoNewWindow -PassThru
Start-Sleep -Seconds 3

$ins = Shu "insmod $remoteKo; echo INS_OK=\`$?; dmesg | tail -5"
Log "insmod output:"
Log $ins

$t1 = Get-Date
$alive = $true
while (((Get-Date) - $t1).TotalSeconds -lt $ProbeSeconds) {
    if (-not (AdbUp)) { $alive = $false; break }
    Start-Sleep -Seconds 3
}
try { if (-not $stream.HasExited) { $stream.Kill() } } catch {}
Log ""
Log ("device alive after probe window: " + $(if ($alive) { 'YES' } else { 'NO (adb vanished -> hang during probe)' }))

Log ""
Log "--- 6. post state ---"
if ($alive) {
    Log (Sh 'cat /proc/modules | grep -i mali')
    Log ("/dev/mali0        : " + (Sh 'ls -l /dev/mali0 2>&1'))
    Log ("uptime            : " + (Sh 'cat /proc/uptime'))
} else {
    Log "skipped: adb gone"
}

if ($CrumbKo) {
    Log ""
    Log "--- 6b. crumb readout (miscdata+0xA0000) ---"
    Log (Shu 'dd if=/dev/block/by-name/miscdata bs=1 skip=655360 count=64 2>/dev/null | od -An -tx1')
}

Log ""
Log "--- 7. streamed dmesg (last 60 lines) ---"
if (Test-Path $streamOut) {
    $tail = Get-Content $streamOut -Tail 60
    $tail | ForEach-Object { Log $_ }
    if (-not $tail) { Log "(empty)" }
}
Log ""
Log "post-recovery checklist (run after the rescue restores Android):"
Log "  adb shell su -c 'dd if=/dev/block/by-name/miscdata bs=1 skip=655360 count=64 | od -An -tx1'"
Log "    <- PRIMARY evidence; survives any reset. magic 'CRUMB01' then one byte per step:"
Log "       60/61 module init / 62 probe / 63 power_control_init / 70+i dev_init[i] / 10..43 glue"
Log "  adb shell su -c 'cat /data/local/tmp/mali_probe.log'         <- secondary (page cache, may be lost)"
Log "  adb shell su -c 'ls -l /sys/fs/pstore/'                      <- ramoops, may hold the panic"

Save
Write-Host "[+] written: $Out"
Write-Host "[+] stream : $streamOut"
