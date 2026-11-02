<#
.SYNOPSIS
    Collect the bring-up state of a booted custom kernel (Mali built-in).

.DESCRIPTION
    Run as soon as adb answers after a test boot. It captures everything needed
    to judge a `mali_kbase` built-in boot and, first of all, disables the SPRD
    native hang monitor (`echo off > /proc/monitor_enable`) so the ~148 s
    "Android did not boot" panic cannot kill the device mid-inspection.

    Read-only except for the hang monitor switch. Uses persistent Magisk `su`
    when available and never invokes the runtime exploit, so SELinux stays
    Enforcing and the boot's integrity verdict is not spoiled.

.EXAMPLE
    .\scripts\host\collect_mali_boot_state.ps1 -Out docs\evidence\2026-11-01-mali-builtin-boot-state.txt
#>
[CmdletBinding()]
param(
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [string]$Out,
    [switch]$NoMonitorOff
)

$ErrorActionPreference = 'Continue'
if (-not $Out) { $Out = "docs\evidence\$((Get-Date -Format 'yyyy-MM-dd'))-mali-boot-state.txt" }
$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }
function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).TrimEnd() }
function Shu([string]$cmd) { (& $Adb shell "su -c `"$cmd`"" 2>&1 | Out-String).TrimEnd() }

$suUid = (Sh 'su -c id -u' -split "`n" | Select-Object -Last 1).Trim()
$haveSu = ($suUid -eq '0')
Log ("collect mali boot state, " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Log "serial      : $((& $Adb get-serialno 2>&1 | Out-String).Trim())"
Log "su uid      : $suUid$(if (-not $haveSu) { ' (no persistent root; root-only steps skipped)' })"
Log ""

if (-not $NoMonitorOff) {
    Log "--- hang monitor ---"
    Log ("monitor_enable before: " + (Sh 'cat /proc/monitor_enable 2>&1'))
    if ($haveSu) { Log ("echo off             : " + (Shu 'echo off > /proc/monitor_enable; cat /proc/monitor_enable')) }
    else { Log "skipped (needs root)" }
    Log ""
}

Log "--- boot ---"
Log ("/proc/version : " + (Sh 'cat /proc/version'))
Log ("/proc/uptime  : " + (Sh 'cat /proc/uptime'))
Log ("cmdline       : " + (Sh 'cat /proc/cmdline'))
Log ("slot          : " + (Sh 'getprop ro.boot.slot_suffix'))
Log ("boot_completed: " + (Sh 'getprop sys.boot_completed'))
Log ("verifiedboot  : " + (Sh 'getprop ro.boot.verifiedbootstate'))
Log ("flash.locked  : " + (Sh 'getprop ro.boot.flash.locked'))
Log ("selinux       : " + (Sh 'getenforce'))
Log ""

Log "--- gpu device nodes ---"
Log ("/dev/mali0    : " + (Sh 'ls -lZ /dev/mali0 2>&1'))
Log ("/dev/kvm      : " + (Sh 'ls -lZ /dev/kvm 2>&1'))
Log ""

Log "--- loaded modules (mali should NOT be here: built-in) ---"
Log (Sh 'cat /proc/modules 2>&1')
Log ""

Log "--- surfaceflinger / zygote ---"
Log (Sh 'ps -A 2>/dev/null | grep -E "surfaceflinger|zygote|system_server" || ps -A 2>/dev/null | head -20')
Log ("boot anim/props: " + (Sh 'getprop init.svc.surfaceflinger; getprop init.svc.bootanim; getprop sys.boot_completed'))
Log ("SF exit count  : " + (Sh 'dmesg 2>/dev/null | grep -c "surfaceflinger"'))
Log ""

Log "--- dmesg: mali / kbase ---"
Log (Sh 'dmesg 2>/dev/null | grep -iE "mali|kbase|midgard|gpu" | head -120')
Log ""

Log "--- dmesg: errors / faults / panics ---"
Log (Sh 'dmesg 2>/dev/null | grep -iE "error|fail|panic|unable|invalid version|disagrees|BUG:|Oops|call trace" | head -80')
Log ""

Log "--- pstore (previous boot, if any) ---"
foreach ($n in @('console-ramoops-0', 'dmesg-ramoops-0')) {
    $sz = Sh "wc -c < /sys/fs/pstore/$n 2>/dev/null"
    Log ("$n : $sz bytes")
}

$dir = Split-Path $Out -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$lines | Set-Content -Path $Out -Encoding utf8
Write-Host "[+] written: $Out"
