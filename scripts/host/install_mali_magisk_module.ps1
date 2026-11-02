<#
.SYNOPSIS
    Install the Mali kbase Magisk module on the connected device.

.DESCRIPTION
    Packages artifacts/mali-module (module.prop + post-fs-data.sh) plus the
    proven mali_kbase.ko into /data/adb/modules/mali-kbase-custom via adb
    root (no zip round-trip needed). The module insmods the GPU driver at
    post-fs-data on every boot of the custom kernel.

    The .ko must be the build matching the running custom kernel
    (vermagic 4.14.199+ SMP preempt mod_unload modversions aarch64,
    module_layout CRC 0x22ad1303). On the stock kernel the module is
    useless (vendor mali_kbase is already loaded).

.EXAMPLE
    .\scripts\host\install_mali_magisk_module.ps1 -Ko artifacts\kernel-build\mali_kbase_fix.ko
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Ko,
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [string]$Src = "$PSScriptRoot\..\..\artifacts\mali-module"
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Ko)) { throw "module not found: $Ko" }
$modDir = '/data/adb/modules/mali-kbase-custom'
$koHash = (Get-FileHash $Ko -Algorithm SHA256).Hash.ToLower()

function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).TrimEnd() }

# sanity: must be the custom kernel with Magisk root
$ver = Sh 'cat /proc/version'
if ($ver -notmatch 'debian@vm') {
    throw "not the custom kernel (running: $ver); the module only matters there"
}
$suUid = (Sh 'su -c id -u' -split "`n" | Select-Object -Last 1).Trim()
if ($suUid -ne '0') { throw "no Magisk root (su uid=$suUid)" }

Write-Host "kernel : $($ver -replace '\s+', ' ')"
Write-Host "ko     : $Ko ($koHash)"

Write-Host "staging module files..."
Sh "su -c 'mkdir -p $modDir'" | Out-Null
foreach ($f in @('module.prop', 'post-fs-data.sh')) {
    (& $Adb push "$Src\$f" "/data/local/tmp/mali_mod_$f" | Out-Null)
    Sh "su -c 'cp /data/local/tmp/mali_mod_$f $modDir/$f && chmod 755 $modDir/$f && rm /data/local/tmp/mali_mod_$f'" | Out-Null
}
(& $Adb push $Ko '/data/local/tmp/mali_mod.ko' | Out-Null)
Sh "su -c 'cp /data/local/tmp/mali_mod.ko $modDir/mali_kbase.ko && chmod 644 $modDir/mali_kbase.ko && rm /data/local/tmp/mali_mod.ko'" | Out-Null

$devHash = (Sh "su -c 'sha256sum $modDir/mali_kbase.ko'" -split '\s+')[0].ToLower()
if ($devHash -ne $koHash) { throw "staged .ko hash mismatch: $devHash" }

Sh "su -c 'touch $modDir/update; rm -f $modDir/disable $modDir/remove'" | Out-Null
Write-Host "installed: $modDir"
Sh "su -c 'ls -l $modDir'" | Write-Host
Write-Host ""
Write-Host "next reboot on the custom kernel will insmod mali_kbase at post-fs-data."
Write-Host "verify after reboot: ls -l /dev/mali0 ; grep -i mali /proc/modules"
Write-Host "log: /data/local/tmp/mali_module_load.log"
