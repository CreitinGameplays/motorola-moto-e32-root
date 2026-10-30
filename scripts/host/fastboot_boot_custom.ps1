<#
.SYNOPSIS
    Run `fastboot boot` with a custom kernel image and collect the diagnostics.

.DESCRIPTION
    Historically this was expected to boot a locally built kernel from RAM.
    It does not: on this product's U-Boot `fastboot boot` acknowledges ANY
    payload (even random bytes) and then reboots, so the image is never
    executed. The script is kept because it captures the proof: it records
    `is-userspace`, the boot reply, the wait time and the kernel that actually
    came back.

    Two different fastboot implementations must be distinguished:
      - fastbootd (`adb reboot fastboot`):        is-userspace: yes
        and `boot` is simply not implemented.
      - real bootloader (`fastboot reboot bootloader`): is-userspace: no
        and `boot` is a stub that ACKs and reboots.

    Nothing is written to any partition by `fastboot boot`, so the run is safe
    either way. See docs/05-bootloader-unlock-research.md and
    docs/evidence/2026-10-30-fastboot-ram-boot-dead-end.txt.

.EXAMPLE
    .\scripts\host\fastboot_boot_custom.ps1 `
        -Image artifacts\kernel-build\boot_custom.img
#>
[CmdletBinding()]
param(
    [string]$Image = 'artifacts\kernel-build\boot_custom.img',
    [string]$Fastboot = 'fastboot',
    [string]$Adb = 'adb',
    [int]$BootWaitSeconds = 300,
    [string]$Out = 'docs\evidence\2026-10-30-custom-kernel-boot.txt'
)

$ErrorActionPreference = 'Stop'
$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }

function Invoke-Fb {
    param([string[]]$FbArgs, [int]$TimeoutSec = 120)
    $p = Start-Process -FilePath $Fastboot -ArgumentList $FbArgs `
                       -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\fb.out" `
                       -RedirectStandardError "$env:TEMP\fb.err"
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
        try { $p.Kill() } catch {}
        Log "    [timeout after ${TimeoutSec}s]"
        return
    }
    foreach ($f in @("$env:TEMP\fb.out", "$env:TEMP\fb.err")) {
        if (Test-Path $f) {
            Get-Content $f | Where-Object { $_ -ne '' } | ForEach-Object { Log "    $_" }
        }
    }
}

function Adb([string]$cmd) {
    $out = & $Adb shell $cmd 2>&1 | Out-String
    return $out.TrimEnd()
}

Log "custom kernel boot, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "image   : $Image ($((Get-Item $Image).Length) bytes, sha256 $((Get-FileHash $Image -Algorithm SHA256).Hash.ToLower()))"
Log "device  : $((& $Adb get-serialno 2>&1) -join '')"
Log ""

Log "===== 1. current (stock) state ====="
Log "    /proc/version: $(Adb 'cat /proc/version')"
Log ""

Log "===== 2. reboot into bootloader ====="
& $Adb reboot bootloader 2>&1 | ForEach-Object { Log "    $_" }
$deadline = (Get-Date).AddSeconds(120)
$inFb = $false
while ((Get-Date) -lt $deadline) {
    if ((& $Fastboot devices 2>&1 | Out-String) -match 'fastboot') { $inFb = $true; break }
    Start-Sleep -Milliseconds 800
}
if (-not $inFb) { Log "[!] device never reached fastboot"; $lines | Set-Content $Out; exit 1 }
Start-Sleep -Seconds 2
Log "    device is in fastboot"
$slotOut = (& $Fastboot getvar current-slot 2>&1 | Out-String) -replace '\s+', ' '
$usOut = (& $Fastboot getvar is-userspace 2>&1 | Out-String) -replace '\s+', ' '
Log "    $($slotOut.Trim())"
Log "    $($usOut.Trim())"
Log ""

if ($usOut -match 'is-userspace:\s*yes') {
    Log "[!] this is FASTBOOTD (userspace fastboot), which has no 'boot' command."
    Log "    run: fastboot reboot bootloader   and try again against the real bootloader"
    $lines | Set-Content $Out
    exit 3
}

Log "===== 3. fastboot boot (RAM only, nothing is flashed) ====="
Log "    NOTE: on this product the real bootloader ACKs 'boot' and reboots; the"
Log "          payload is not executed. Expect 'Booting OKAY' plus the stock kernel."
Invoke-Fb @('boot', $Image) 180
Log ""

Log "===== 4. wait for Android ====="
$deadline = (Get-Date).AddSeconds($BootWaitSeconds)
$up = $false
while ((Get-Date) -lt $deadline) {
    # adb prints "error: no devices/emulators found" on stderr while the device
    # is rebooting; with $ErrorActionPreference = 'Stop' that would abort the
    # whole script, so keep the probes non-fatal.
    $st = ''
    try { $st = (& $Adb get-state 2>&1 | Out-String).Trim() } catch { $st = '' }
    if ($st -match 'device') { $up = $true; break }
    $fb = ''
    try { $fb = (& $Fastboot devices 2>&1 | Out-String).Trim() } catch { $fb = '' }
    if ($fb -match 'fastboot') { Log "    [still in fastboot at $(Get-Date -Format HH:mm:ss)]" }
    Start-Sleep -Seconds 3
}
if (-not $up) {
    Log "[!] Android did not come back within $BootWaitSeconds s"
    Log "    fastboot devices: $((& $Fastboot devices 2>&1 | Out-String).Trim())"
    $lines | Set-Content $Out
    exit 2
}
Log "    adb is up"
Start-Sleep -Seconds 5
Log ""

Log "===== 5. running kernel ====="
Log "    /proc/version : $(Adb 'cat /proc/version')"
Log "    /proc/cmdline : $(Adb 'cat /proc/cmdline')"
Log "    /proc/uptime  : $(Adb 'cat /proc/uptime')"
Log ""

Log "===== 6. device state ====="
foreach ($p in @('ro.boot.slot_suffix','ro.build.display.id','ro.boot.flash.locked',
                 'ro.boot.verifiedbootstate','ro.boot.bootreason','ro.boot.hardware')) {
    Log ("    {0,-28} = {1}" -f $p, (Adb "getprop $p"))
}
Log ""

Log "===== 7. modules (did the vendor modules load?) ====="
Log (Adb 'cat /proc/modules')
Log ""

Log "===== 8. KVM / virtualization ====="
Log "    /dev/kvm present : $((Adb 'ls -l /dev/kvm') -replace "`n", ' ')"
Log "    /dev/vhost*      : $((Adb 'ls /dev/vhost* 2>/dev/null') -replace "`n", ' ')"
Log ""

Log "===== 9. dmesg (first 120 lines) ====="
Log (Adb 'dmesg 2>/dev/null | head -120')
Log ""

Log "===== 10. dmesg errors ====="
Log (Adb 'dmesg 2>/dev/null | grep -iE "error|fail|panic|unable|invalid version|disagrees" | head -60')

$dir = Split-Path $Out -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$lines | Set-Content -Path $Out -Encoding utf8
Write-Host "[+] written: $Out"
