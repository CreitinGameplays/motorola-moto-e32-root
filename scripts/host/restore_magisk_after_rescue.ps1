<#
.SYNOPSIS
    Restore the known-good Magisk boot after boot_a rescue has restored stock.

.DESCRIPTION
    This is used between the checkpoint positive control and target. It only
    runs after Android has returned on slot _b. If Magisk is absent, the
    verified mali_kroot path elevates one adb shell long enough to restore the
    known-good Magisk boot_b. The script checks both boot partition hashes,
    arms the proven one-attempt fallback, reboots, and requires Magisk root
    with SELinux Enforcing before returning.
#>
[CmdletBinding()]
param(
    # adb from PATH when available; the fallback is the author's layout
    [string]$Adb = $(if (Get-Command adb -ErrorAction SilentlyContinue) { 'adb' } else { 'D:\AndroidSDKTools\adb\adb.exe' }),
    # the known-good Magisk-patched stock boot image; the repo copy is the
    # default, override with -MagiskImage
    [string]$MagiskImage = "artifacts\kernel-build\magisk_boot_b_2026-11-01.img",
    [int]$WaitSeconds = 300,
    [string]$Out
)

$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# repo-relative default resolves against the repo root; an absolute
# -MagiskImage is taken as-is
if (-not [System.IO.Path]::IsPathRooted($MagiskImage)) {
    $MagiskImage = Join-Path $repoRoot $MagiskImage
}
$expectedMagisk = '90416c09f6359fdcc0711f36e214454421c42598518787f58c1916be6c5cad3c'
$expectedStock = 'ccd0faff51ab24d921b2671c562f0fe08e7a1ba2b7f19bb93a5f2650eb4f7b18'
$expectedRescue = 'fc3ca0efd6414d4f5d24c478b1592ea1ba9386f1476883a0bd8a1b8b1a3844c0'
$helperPath = Join-Path $repoRoot 'scripts\device\set_slot_b_tries1.sh'

if (-not $Out) {
    $Out = Join-Path $repoRoot ('docs\evidence\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-magisk-reroot.txt')
}
$outDir = Split-Path -Parent $Out
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }
function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).Trim() }
function SaveLog { $lines | Out-File -Append -Encoding utf8 $Out }

try {
    if (-not (Test-Path $MagiskImage)) { throw "Magisk image not found: $MagiskImage" }
    $imageInfo = Get-Item $MagiskImage
    $imageHash = (Get-FileHash $MagiskImage -Algorithm SHA256).Hash.ToLower()
    if ($imageInfo.Length -ne 67108864 -or $imageHash -ne $expectedMagisk) {
        throw "refusing unexpected Magisk image (bytes=$($imageInfo.Length), sha256=$imageHash)"
    }
    if ((Get-Content $helperPath -Raw) -match 'mali_kroot') {
        throw 'refusing unsafe one-attempt helper containing mali_kroot'
    }
    $helperHash = (Get-FileHash $helperPath -Algorithm SHA256).Hash.ToLower()

    Log "Magisk re-root, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Log "image: $MagiskImage ($($imageInfo.Length) bytes, sha256 $imageHash)"
    Log "adb state: $((& $Adb get-state 2>&1 | Out-String).Trim())"
    $slot = Sh 'getprop ro.boot.slot_suffix'
    $completed = Sh 'getprop sys.boot_completed'
    Log "slot=$slot boot_completed=$completed"
    if ($slot -ne '_b' -or $completed -ne '1') {
        throw 'expected completed Android userspace on slot _b after rescue'
    }

    $uid = Sh "su -c 'id -u'"
    if ($uid -eq '0') {
        $enforce = Sh 'getenforce'
        $bootHash = Sh "su -c 'sha256sum /dev/block/by-name/boot_b'"
        $bootHash = (($bootHash -split '\s+')[0]).ToLower()
        if ($enforce -ne 'Enforcing' -or $bootHash -ne $expectedMagisk) {
            throw "root already exists but state is unexpected (SELinux=$enforce, boot_b=$bootHash)"
        }
        Log 'known-good Magisk is already active; no re-root write needed.'
        SaveLog
        return
    }

    Log 'Magisk is absent; staging the verified image and root-only helper.'
    $pushImage = (& $Adb push $MagiskImage '/data/local/tmp/boot_magisk_avb.img' 2>&1 | Out-String).Trim()
    Log $pushImage
    $remoteImageHash = Sh 'sha256sum /data/local/tmp/boot_magisk_avb.img'
    $remoteImageHash = (($remoteImageHash -split '\s+')[0]).ToLower()
    if ($remoteImageHash -ne $expectedMagisk) { throw "staged Magisk hash mismatch: $remoteImageHash" }

    $pushHelper = (& $Adb push $helperPath '/data/local/tmp/set_slot_b_tries1.sh' 2>&1 | Out-String).Trim()
    Log $pushHelper
    Sh 'chmod 755 /data/local/tmp/set_slot_b_tries1.sh' | Out-Null
    $helperSyntax = Sh 'sh -n /data/local/tmp/set_slot_b_tries1.sh && echo HELPER_SYNTAX_OK'
    if ($helperSyntax -notmatch 'HELPER_SYNTAX_OK') { throw "device shell rejected helper: $helperSyntax" }
    $remoteHelperHash = Sh 'sha256sum /data/local/tmp/set_slot_b_tries1.sh'
    $remoteHelperHash = (($remoteHelperHash -split '\s+')[0]).ToLower()
    if ($remoteHelperHash -ne $helperHash) { throw "staged helper hash mismatch: $remoteHelperHash" }

    $rootCommand = @'
set -e
chmod 755 /data/local/tmp/mali_kroot
/data/local/tmp/mali_kroot >/dev/null 2>&1
[ "$(id -u)" = "0" ] || { echo "ABORT: exploit did not yield uid 0"; exit 20; }
[ "$(getprop ro.boot.slot_suffix)" = "_b" ] || { echo "ABORT: not on _b"; exit 21; }
boot_a_hash=$(sha256sum /dev/block/by-name/boot_a | awk '{print $1}')
boot_b_hash=$(sha256sum /dev/block/by-name/boot_b | awk '{print $1}')
echo "boot_a=$boot_a_hash boot_b=$boot_b_hash"
[ "$boot_a_hash" = "__RESCUE_HASH__" ] || { echo "ABORT: rescue hash mismatch"; exit 22; }
case "$boot_b_hash" in
  "__STOCK_HASH__")
    image_hash=$(sha256sum /data/local/tmp/boot_magisk_avb.img | awk '{print $1}')
    [ "$image_hash" = "__MAGISK_HASH__" ] || { echo "ABORT: staged image hash mismatch"; exit 24; }
    dd if=/data/local/tmp/boot_magisk_avb.img of=/dev/block/by-name/boot_b bs=1M
    sync
    readback_hash=$(sha256sum /dev/block/by-name/boot_b | awk '{print $1}')
    echo "boot_b_readback=$readback_hash"
    [ "$readback_hash" = "__MAGISK_HASH__" ] || { echo "ABORT: boot_b read-back mismatch"; exit 25; }
    ;;
  "__MAGISK_HASH__")
    echo "boot_b already contains the verified Magisk image, no partition rewrite needed"
    ;;
  *)
    echo "ABORT: boot_b is neither verified stock nor known-good Magisk"
    exit 23
    ;;
esac
sh /data/local/tmp/set_slot_b_tries1.sh
'@
    $rootCommand = $rootCommand.Replace('__RESCUE_HASH__', $expectedRescue).
        Replace('__STOCK_HASH__', $expectedStock).
        Replace('__MAGISK_HASH__', $expectedMagisk)
    Log 'Running the single-shell CVE re-root/write; the next reboot restores SELinux Enforcing.'
    $rootOutput = (& $Adb shell $rootCommand 2>&1 | Out-String).Trim()
    $rootExit = $LASTEXITCODE
    Log ($rootOutput -replace "`r?`n", ' | ')
    if ($rootExit -ne 0 -or $rootOutput -notmatch 'AB_TRIES1_OK') {
        throw "rooted Magisk restore command failed (adb exit $rootExit)"
    }

    Log 'Rebooting into the known-good Magisk boot.'
    & $Adb reboot 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $magiskReady = $false
    while ((Get-Date) -lt $deadline) {
        $state = ((& $Adb get-state 2>&1 | Out-String).Trim())
        if ($state -eq 'device') {
            $status = Sh 'getprop sys.boot_completed; getprop ro.boot.slot_suffix'
            if ($status -match '(?m)^1\r?\n_b\r?$') {
                $uid = Sh "su -c 'id -u'"
                $enforce = Sh 'getenforce'
                if ($uid -eq '0' -and $enforce -eq 'Enforcing') {
                    $bootHash = Sh "su -c 'sha256sum /dev/block/by-name/boot_b'"
                    $bootHash = (($bootHash -split '\s+')[0]).ToLower()
                    if ($bootHash -eq $expectedMagisk) { $magiskReady = $true; break }
                }
            }
        }
        Start-Sleep -Seconds 3
    }
    if (-not $magiskReady) {
        throw "Magisk did not return on _b within $WaitSeconds seconds; if the phone is hung, let the one-attempt boot_a rescue recover it with a power-cycle."
    }
    Log 'verified: boot_b is the known-good Magisk image, su uid=0, SELinux Enforcing, Android complete on _b.'
    SaveLog
} catch {
    Log "ERROR: $($_.Exception.Message)"
    SaveLog
    throw
}
