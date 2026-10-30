<#
.SYNOPSIS
    Write a boot image to `boot_b` with fastboot and verify the read-back.

.DESCRIPTION
    This is the only remaining way to run a locally built kernel on this phone:
    `fastboot boot` is a stub on this bootloader (it ACKs any payload and
    reboots), so the kernel has to live in `boot_b`.

    Safety:
      - refuses to run unless `is-userspace: no` (real bootloader) and
        `current-slot: b`
      - refuses an image larger than the partition (`getvar partition-size:boot_b`)
      - records every step, waits for Android, and prints the running
        /proc/version so success/failure is unambiguous
      - does NOT restore anything automatically; the pristine stock image is
        artifacts/bootloader/bl3/boot_b.img (sha256 CCD0FAFF...). Restore with:
            fastboot flash boot_b artifacts\bootloader\bl3\boot_b.img

.EXAMPLE
    # round trip: prove flash + restore works with the pristine image
    .\scripts\host\flash_boot_b.ps1 -Image artifacts\bootloader\bl3\boot_b.img `
        -Out docs\evidence\2026-10-30-flash-roundtrip.txt

.EXAMPLE
    # the custom kernel
    .\scripts\host\flash_boot_b.ps1 -Image artifacts\kernel-build\boot_custom.img `
        -Out docs\evidence\2026-10-30-custom-kernel-boot.txt
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [string]$Fastboot = 'fastboot',
    [string]$Adb = 'adb',
    [int]$BootWaitSeconds = 420,
    [string]$Out
)

# Native tools (fastboot/adb) write their normal output to stderr, which
# PowerShell turns into ErrorRecords; do not let that abort the script. Failures
# are detected by parsing the captured output instead.
$ErrorActionPreference = 'Continue'
if (-not (Test-Path $Image)) { throw "image not found: $Image" }
if (-not $Out) { $Out = "docs\evidence\$((Get-Date -Format yyyy-MM-dd))-flash-boot_b.txt" }

$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }

$imgBytes = (Get-Item $Image).Length
$imgHash = (Get-FileHash $Image -Algorithm SHA256).Hash

Log "flash boot_b, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "image   : $Image"
Log "          $imgBytes bytes, sha256 $imgHash"
Log "device  : $((& $Adb get-serialno 2>&1 | Out-String).Trim())"
Log ""

Log "===== 1. pre-flight (stock state) ====="
try { Log "    /proc/version: $((& $Adb shell 'cat /proc/version' 2>&1 | Out-String).Trim())" } catch {}
Log "    slot: $((& $Adb shell 'getprop ro.boot.slot_suffix' 2>&1 | Out-String).Trim())"
Log "    flash.locked: $((& $Adb shell 'getprop ro.boot.flash.locked' 2>&1 | Out-String).Trim())"
Log "    verifiedbootstate: $((& $Adb shell 'getprop ro.boot.verifiedbootstate' 2>&1 | Out-String).Trim())"
Log ""

Log "===== 2. reboot into the real bootloader ====="
& $Adb reboot bootloader 2>&1 | ForEach-Object { Log "    $_" }
$deadline = (Get-Date).AddSeconds(120)
$inFb = $false
while ((Get-Date) -lt $deadline) {
    if ((& $Fastboot devices 2>&1 | Out-String) -match 'fastboot') { $inFb = $true; break }
    Start-Sleep -Milliseconds 800
}
if (-not $inFb) { Log "[!] device never reached fastboot"; $lines | Set-Content $Out; exit 1 }

$us = ((& $Fastboot getvar is-userspace 2>&1 | Out-String) -replace '\s+', ' ').Trim()
$slot = ((& $Fastboot getvar current-slot 2>&1 | Out-String) -replace '\s+', ' ').Trim()
$psize = ((& $Fastboot getvar partition-size:boot_b 2>&1 | Out-String) -replace '\s+', ' ').Trim()
Log "    $us"
Log "    $slot"
Log "    $psize"
if ($us -notmatch 'is-userspace:\s*no') {
    Log "[!] not the real bootloader (fastbootd); run 'fastboot reboot bootloader' and retry"
    $lines | Set-Content $Out; exit 2
}
if ($slot -notmatch 'current-slot:\s*b') {
    Log "[!] current slot is not b; refusing to flash"
    $lines | Set-Content $Out; exit 3
}
$m = [regex]::Match($psize, '0x([0-9a-fA-F]+)')
if ($m.Success) {
    $partSize = [Convert]::ToInt64($m.Groups[1].Value, 16)
    Log "    partition size: $partSize bytes, image: $imgBytes bytes"
    if ($imgBytes -gt $partSize) {
        Log "[!] image larger than partition; refusing"
        $lines | Set-Content $Out; exit 4
    }
}
Log ""

Log "===== 3. fastboot flash boot_b ====="
$sw = [Diagnostics.Stopwatch]::StartNew()
& $Fastboot flash boot_b $Image 2>&1 | ForEach-Object { Log "    $_" }
Log "    (flash took $([math]::Round($sw.Elapsed.TotalSeconds,1)) s)"
Log ""

Log "===== 4. re-read the partition and compare the hash ====="
Log "    sending the device back to Android..."
& $Fastboot reboot 2>&1 | ForEach-Object { Log "    $_" }
$deadline = (Get-Date).AddSeconds($BootWaitSeconds)
$up = $false
while ((Get-Date) -lt $deadline) {
    $st = ''
    try { $st = (& $Adb get-state 2>&1 | Out-String).Trim() } catch { $st = '' }
    if ($st -match '^(device|recovery|sideload)$') { $up = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $up) {
    Log "[!] Android did not come back within $BootWaitSeconds s"
    Log "    fastboot devices: $((& $Fastboot devices 2>&1 | Out-String).Trim())"
    Log "    If the phone is black: hold Power + Volume-Down until the bootloader"
    Log "    screen appears, then: fastboot flash boot_b artifacts\\bootloader\\bl3\\boot_b.img"
    $lines | Set-Content $Out
    exit 5
}
Log "    adb is up"
Start-Sleep -Seconds 4

# root is needed to read the block device; run the exploit in the same shell
$rb = (& $Adb shell '/data/local/tmp/mali_kroot >/dev/null 2>&1; dd if=/dev/block/by-name/boot_b of=/data/local/tmp/bootb_check.img bs=4096 2>/dev/null; sha256sum /data/local/tmp/bootb_check.img' 2>&1 | Out-String).Trim()
Log "    read-back: $rb"
$hashLine = ($rb -split "`n" | Where-Object { $_ -match '^[0-9a-f]{64}' } | Select-Object -First 1)
if ($hashLine) {
    $rbHash = ($hashLine -split '\s+')[0].ToUpper()
    if ($rbHash -eq $imgHash) { Log "    [OK] read-back hash matches the image" }
    else { Log "    [!] read-back hash $rbHash differs from $imgHash" }
}
Log ""

Log "===== 5. running kernel ====="
Log "    /proc/version : $((& $Adb shell 'cat /proc/version' 2>&1 | Out-String).Trim())"
Log "    /proc/uptime  : $((& $Adb shell 'cat /proc/uptime' 2>&1 | Out-String).Trim())"
Log "    slot          : $((& $Adb shell 'getprop ro.boot.slot_suffix' 2>&1 | Out-String).Trim())"
Log "    boot.git      : $((& $Adb shell 'getprop ro.boot.build.id 2>/dev/null' 2>&1 | Out-String).Trim())"
Log ""

Log "===== 6. KVM / modules / dmesg ====="
Log "    /dev/kvm      : $((& $Adb shell 'ls -l /dev/kvm 2>&1' 2>&1 | Out-String).Trim())"
Log "    /proc/modules :"
Log ((& $Adb shell 'cat /proc/modules 2>&1' 2>&1 | Out-String).TrimEnd())
Log "    dmesg errors  :"
Log ((& $Adb shell 'dmesg 2>/dev/null | grep -iE "error|fail|panic|unable|invalid version|disagrees" | head -40' 2>&1 | Out-String).TrimEnd())

$dir = Split-Path $Out -Parent
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$lines | Set-Content -Path $Out -Encoding utf8
Write-Host "[+] written: $Out"