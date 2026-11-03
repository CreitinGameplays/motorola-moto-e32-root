<#
.SYNOPSIS
    Collect the camera / vendor-module state of the phone.

.DESCRIPTION
    Dumps everything needed to judge whether the vendor camera stack
    (sprd_sensor -> sprd_flash_drv -> sprd_camera -> sprd_cpp -> mmdvfs ->
    sprd_fd) loaded on a vendor-module-compatible kernel:
      - kernel release / vermagic and slot
      - /proc/modules entries for the sprd modules
      - dmesg filtered for module-load and camera messages
      - /dev/video* nodes, CameraService and media.camera state

.EXAMPLE
    .\scripts\host\collect_camera_state.ps1 -Out docs\evidence\2026-11-03-camera-test.txt
#>
[CmdletBinding()]
param(
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [string]$Out = 'docs\evidence\camera-state.txt'
)

$ErrorActionPreference = 'Continue'

function Su([string]$cmd) {
    & $Adb shell ("su -c '" + $cmd + "'") 2>&1 | Out-String
}

$report = New-Object System.Collections.Generic.List[string]
function Add([string]$title, $lines) {
    $report.Add("===== $title =====")
    foreach ($l in @($lines)) { $report.Add([string]$l) }
    $report.Add("")
}

Add 'identity' (Su 'uname -a; getprop ro.boot.slot_suffix; getprop sys.boot_completed; getprop init.svc.cameraserver; getprop init.svc.vendor.camera-provider-2-4')
Add 'modules' (Su 'grep -E "^(sprd|mmdvfs|aw9610x|flash_ic|incrementalfs|mali)" /proc/modules')
Add 'device nodes' (Su 'ls -l /dev/video* /dev/v4l-subdev* /dev/mali0 2>&1')
Add 'camera rc load results' (& $Adb logcat -d -b all 2>&1 | Select-String -Pattern 'insmod|sprd_camera|sprd_sensor|sprd_cpp|mmdvfs|sprd_fd|CameraService|cameraserver|CRC differs|disagrees about version' | Select-Object -First 400 | ForEach-Object { $_.Line })
Add 'dmesg module+camera' (Su 'dmesg | grep -iE "sprd_camera|sprd_sensor|sprd_cpp|mmdvfs|sprd_fd|flash_ic|sprd_flash|CRC differs|disagrees|Unknown symbol|camera" | tail -250')
Add 'media.camera' (Su 'dumpsys media.camera 2>&1 | head -60')

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$report -join "`r`n" | Out-File -Encoding utf8 $Out
Write-Host "written: $Out"
$report | Select-Object -First 60
