<#
.SYNOPSIS
    Install the SC2355 WLAN combo Magisk module on the connected device.

.DESCRIPTION
    Packages modules/sprd-wlan-combo (module.prop + post-fs-data.sh) plus the
    proven sprdwl_ng.ko into /data/adb/modules/sprd-wlan-combo via adb
    root (no zip round-trip needed). The module insmods the GPU driver at
    post-fs-data on every boot of the custom kernel.

    The .ko must be the build matching the running kernel - same vermagic
    (4.14.199+-ab612c2 since the stock-config compat kernel) and same
    module_layout CRC. Re-run this script with the fresh .ko after every
    kernel rebuild, before rebooting into it.

.EXAMPLE
    .\scripts\host\install_wlan_magisk_module.ps1 -Ko artifacts\kernel-build\sprdwl_ng.ko
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Ko,
    # adb from PATH when available; the fallback is the author's layout
    [string]$Adb = $(if (Get-Command adb -ErrorAction SilentlyContinue) { 'adb' } else { 'D:\AndroidSDKTools\adb\adb.exe' }),
    [string]$Src = "modules\sprd-wlan-combo"
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Src = Join-Path $repoRoot $Src
if (-not (Test-Path $Ko)) { throw "module not found: $Ko" }
$modDir = '/data/adb/modules/sprd-wlan-combo'
$koHash = (Get-FileHash $Ko -Algorithm SHA256).Hash.ToLower()

function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).TrimEnd() }

# sanity: warn (but allow) when not the custom kernel, so the module can be
# staged from a stock boot too (the .ko only takes effect on the custom one).
$ver = Sh 'cat /proc/version'
if ($ver -notmatch 'debian@vm') {
    Write-Host "note: running the stock kernel; staging anyway (module is inert there)" 
}
$suUid = (Sh 'su -c id -u' -split "`n" | Select-Object -Last 1).Trim()
if ($suUid -ne '0') { throw "no Magisk root (su uid=$suUid)" }

Write-Host "kernel : $($ver -replace '\s+', ' ')"
Write-Host "ko     : $Ko ($koHash)"

Write-Host "staging module files..."
Sh "su -c 'mkdir -p $modDir'" | Out-Null
foreach ($f in @('module.prop', 'post-fs-data.sh')) {
    (& $Adb push "$Src\$f" "/data/local/tmp/wlan_mod_$f" | Out-Null)
    Sh "su -c 'cp /data/local/tmp/wlan_mod_$f $modDir/$f && chmod 755 $modDir/$f && rm /data/local/tmp/wlan_mod_$f'" | Out-Null
}
(& $Adb push $Ko '/data/local/tmp/wlan_mod.ko' | Out-Null)
Sh "su -c 'cp /data/local/tmp/wlan_mod.ko $modDir/sprdwl_ng.ko && chmod 644 $modDir/sprdwl_ng.ko && rm /data/local/tmp/wlan_mod.ko'" | Out-Null

$devHash = (Sh "su -c 'sha256sum $modDir/sprdwl_ng.ko'").Split(" ")[0].ToLower()
if ($devHash -ne $koHash) { throw "staged .ko hash mismatch: $devHash" }

Sh "su -c 'touch $modDir/update; rm -f $modDir/disable $modDir/remove'" | Out-Null
Write-Host "installed: $modDir"
Sh "su -c 'ls -l $modDir'" | Write-Host
Write-Host ""
Write-Host "next reboot on the custom kernel will insmod sprd_wlan_combo at post-fs-data."
Write-Host "verify after reboot: ip link show wlan0 ; grep sprd_wlan /proc/modules"
Write-Host "log: /data/local/tmp/wlan_module_load.log"
