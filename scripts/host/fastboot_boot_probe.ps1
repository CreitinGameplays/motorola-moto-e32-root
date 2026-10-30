<#
.SYNOPSIS
    Probe whether this bootloader accepts `fastboot boot` at all.

.DESCRIPTION
    `fastboot boot <img>` would be the way to run a kernel without writing
    flash, so it is worth knowing what the command really does on this device.

    Result (2026-10-30): in fastbootd (`is-userspace: yes`) it is not
    implemented at all (`Unrecognized command boot`). In the real bootloader
    (`is-userspace: no`) it is a stub: it replies `Sending OKAY` +
    `Booting OKAY` for *any* payload, including 4 KiB of random bytes, then
    reboots the phone. The payload is never executed - the phone always comes
    back on the flashed stock kernel. See
    docs/evidence/2026-10-30-fastboot-ram-boot-dead-end.txt.

    So this script is a probe of the reply behaviour, not a boot path.
    Nothing is written to flash either way.

.EXAMPLE
    .\scripts\host\fastboot_boot_probe.ps1
#>
[CmdletBinding()]
param(
    [string]$Fastboot = 'fastboot',
    [string]$Serial,
    [string]$Out = 'docs\evidence\2026-10-30-fastboot-boot-probe.txt',
    [int]$WaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }

function Invoke-Fb {
    param([string[]]$FbArgs, [int]$TimeoutSec = 45)
    $argList = @()
    if ($Serial) { $argList += @('-s', $Serial) }
    $argList += $FbArgs
    $p = Start-Process -FilePath $Fastboot -ArgumentList $argList `
                       -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\fb.out" `
                       -RedirectStandardError "$env:TEMP\fb.err"
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        try { $p.Kill() } catch {}
        Log "    [timeout after ${TimeoutSec}s - command killed]"
        return
    }
    foreach ($f in @("$env:TEMP\fb.out", "$env:TEMP\fb.err")) {
        if (Test-Path $f) {
            Get-Content $f | Where-Object { $_ -ne '' } | ForEach-Object { Log "    $_" }
        }
    }
}

function Wait-Fastboot {
    param([int]$Seconds)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $out = & $Fastboot devices 2>&1 | Out-String
        if ($out -match 'fastboot') { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

Log "fastboot-boot probe, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "device: $(& adb get-serialno 2>&1)"
Log ""

Log "===== 1. reboot to bootloader ====="
& adb reboot bootloader 2>&1 | ForEach-Object { Log "    $_" }
if (-not (Wait-Fastboot -Seconds $WaitSeconds)) { Log "[!] device did not reach fastboot"; exit 1 }
Start-Sleep -Seconds 2
Log "    device is in fastboot"

Log ""
Log "===== 2. state sanity (nothing should change) ====="
Log "--- fastboot getvar current-slot"
Invoke-Fb @('getvar', 'current-slot')
Log "--- fastboot getvar unlocked"
Invoke-Fb @('getvar', 'unlocked')

Log ""
Log "===== 3. a payload that cannot boot: 4 KiB of 0xFF ====="
$dummy = Join-Path $env:TEMP 'fb_boot_probe.bin'
[IO.File]::WriteAllBytes($dummy, [byte[]]::new(4096))
(Get-Item $dummy) | ForEach-Object { Log "    payload: $($_.FullName) $($_.Length) bytes" }

Log ""
Log "===== 4. fastboot boot <payload>  (the actual question) ====="
Log "--- fastboot boot $dummy"
Invoke-Fb @('boot', $dummy) 60

Log ""
Log "===== 5. does oem expose any boot-from-RAM command? ====="
Log "--- fastboot oem help"
Invoke-Fb @('oem', 'help') 30

Log ""
Log "===== 6. back to Android ====="
Log "--- fastboot reboot"
Invoke-Fb @('reboot') 20
Start-Sleep -Seconds 3
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$ok = $false
while ((Get-Date) -lt $deadline) {
    $st = & adb get-state 2>&1 | Out-String
    if ($st -match 'device') { $ok = $true; break }
    Start-Sleep -Seconds 2
}
Log "    adb state: $(if ($ok) { 'device (booted)' } else { 'NOT back yet' })"
if ($ok) {
    Log "    ro.boot.slot_suffix = $((& adb shell getprop ro.boot.slot_suffix 2>&1) -join '')"
    Log "    ro.boot.flash.locked = $((& adb shell getprop ro.boot.flash.locked 2>&1) -join '')"
    Log "    ro.boot.verifiedbootstate = $((& adb shell getprop ro.boot.verifiedbootstate 2>&1) -join '')"
}

$dir = Split-Path $Out -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$lines | Set-Content -Path $Out -Encoding utf8
Write-Host "[+] written: $Out"
