<#
.SYNOPSIS
    Run one custom-kernel image in `boot_b` and classify the result as
    RESET or HANG, unattended.

.DESCRIPTION
    Flashes a boot image into `boot_b` over adb as root (this bootloader's
    `fastboot boot` is a no-op, so boot_b is the only channel), forces slot b
    to exactly one boot attempt, reboots, and then watches adb.

    Why waiting for adb is the verdict:
      - a RESET (PSCI SYSTEM_RESET from a stage hook, or any watchdog reset)
        is followed by the SPL falling back to slot a because slot b's single
        try is spent; the boot_a rescue rewrites stock boot_b and Android
        comes back in ~2.5 min.  adb therefore reappears.
      - a HANG means the CPU is stalled: no adb, no fastboot, no reset.  adb
        never reappears and the phone sits on the Motorola logo.
    So: adb back within the window => RESET (the stage was reached);
        nothing within the window => HANG (the kernel died before it).

    On success the script also prints the misc block, so the post-reset
    state is on the record.

.PARAMETER Image
    The 64 MiB boot image to test (e.g. artifacts\kernel-build\boot_p0a0s1.img).

.PARAMETER WaitSeconds
    How long to wait for adb after the reboot.  Measured recovery after a
    hang is ~12 min (the SPL falls back to the slot-a rescue, which restores
    boot_b and reboots), so the default is 900 s - with the old 330 s the
    recovery was misreported as a HANG.

.PARAMETER Out
    Evidence file to append to.  Default: docs\evidence\<date>-boot_b-tests.txt

.EXAMPLE
    .\scripts\host\run_boot_b_test.ps1 -Image artifacts\kernel-build\boot_p0a0s1.img
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Image,
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [int]$WaitSeconds = 900,
    [string]$Out
)

$ErrorActionPreference = 'Continue'
if (-not (Test-Path $Image)) { throw "image not found: $Image" }
if (-not $Out) { $Out = "docs\evidence\$((Get-Date -Format yyyy-MM-dd))-boot_b-tests.txt" }

$lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $lines.Add($s); Write-Host $s }
function Sh([string]$cmd) { (& $Adb shell $cmd 2>&1 | Out-String).Trim() }

$imgBytes = (Get-Item $Image).Length
$imgHash = (Get-FileHash $Image -Algorithm SHA256).Hash
if ($imgBytes -gt 67108864) { throw "image is larger than boot_b (64 MiB)" }

Log ""
Log ("=" * 72)
Log "boot_b test, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "image : $Image"
Log "        $imgBytes bytes, sha256 $imgHash"
Log ("=" * 72)

Log "--- pre-flight ---"
$slot = Sh 'getprop ro.boot.slot_suffix'
$ver = Sh 'cat /proc/version'
$bak = (Get-Item $Image).BaseName
Log "slot            : $slot"
Log "running kernel  : $ver"
if ($slot -ne '_b') { Log "ABORT: not on slot _b (running $slot); the test channel needs _b"; $lines | Out-File -Append -Encoding utf8 $Out; throw "wrong slot" }

Log "--- push ---"
(& $Adb push $Image "/data/local/tmp/$bak.img" 2>&1 | Out-Null)
$devHash = Sh "sha256sum /data/local/tmp/$bak.img | awk '{print `$1}'"
Log "pushed sha256   : $devHash"
if ($devHash.ToLower() -ne $imgHash.ToLower()) { Log "ABORT: push hash mismatch"; $lines | Out-File -Append -Encoding utf8 $Out; throw "push hash mismatch" }

Log "--- flash boot_b (root) ---"
# Use persistent Magisk su, not mali_kroot: the exploit temporarily leaves
# SELinux permissive and can spoil integrity measurements. Keep the privileged
# write and hash in one su invocation.
$rb = $null
for ($i = 1; $i -le 4; $i++) {
    $w = Sh ("su -c 'dd if=/data/local/tmp/$bak.img of=/dev/block/by-name/boot_b bs=1M && " +
             "sync && sha256sum /dev/block/by-name/boot_b | head -c 64'")
    Log "attempt $i : $($w -replace "`r?`n", ' | ')"
    $rb = ($w -split "`n" | Where-Object { $_ -match '^[0-9a-f]{64}$' } | Select-Object -Last 1)
    if ($rb) { break }
    Start-Sleep -Seconds 2
}
if (-not $rb -or $rb.ToLower() -ne $imgHash.ToLower()) {
    Log "ABORT: boot_b read-back does not match the image (read back: $rb)"
    $lines | Out-File -Append -Encoding utf8 $Out
    throw "read-back mismatch"
}
Log "read-back match : YES"

Log "--- one-attempt slot b ---"
# This step MUST succeed: it is what makes the SPL fall back to slot a when the
# kernel hangs, i.e. what makes a hang recoverable without BROM. Retry until
# the block really shows b.tries = 1.
$slotOk = $false
for ($i = 1; $i -le 5; $i++) {
    $s = Sh "su -c 'sh /data/local/tmp/set_slot_b_tries1.sh'"
    Log "attempt $i : $($s -replace "`r?`n", ' | ')"
    if ($s -match '1f 00' ) { $slotOk = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $slotOk) {
    Log "ABORT: could not set slot b to one attempt (root failed); a hang would"
    Log "        not fall back to slot a. Nothing was rebooted."
    $lines | Out-File -Append -Encoding utf8 $Out
    throw "slot b one-attempt not set"
}

Log "--- reboot ---"
$t0 = Get-Date
(& $Adb reboot 2>&1 | Out-Null)
Log ("reboot issued at " + $t0.ToString('HH:mm:ss'))

$verdict = 'HANG'
$last = ''
while (((Get-Date) - $t0).TotalSeconds -lt $WaitSeconds) {
    $raw = (& $Adb devices 2>&1 | Out-String)
    $line = ($raw -split "`n" | Where-Object { $_ -match '\sdevice$' } | Select-Object -First 1)
    $state = if ($null -eq $line) { 'absent' } else { 'device' }
    $el = [int]((Get-Date) - $t0).TotalSeconds
    if ($state -ne $last) { Log ("t+{0,4}s  {1}" -f $el, $state); $last = $state }
    if ($state -eq 'device') {
        $r = Sh 'getprop sys.boot_completed; getprop ro.boot.slot_suffix; cat /proc/uptime'
        Log ("t+{0,4}s  {1}" -f $el, ($r -replace "`r?`n", ' '))
        if ($r -match '^\s*1') { $verdict = 'RESET'; break }
    }
    Start-Sleep -Seconds 3
}

$elapsed = [int]((Get-Date) - $t0).TotalSeconds
Log ""
Log "VERDICT: $verdict  (adb back after ${elapsed}s)" 
if ($verdict -eq 'RESET') {
    Log "  => the device reset and Android returned; inspect captured pstore records"
} else {
    Log "  => no adb and no reset observed; the watchdog may not have armed or fired"
    Log "     recover with a power cycle (slot b's try is spent, the SPL takes slot a"
    Log "     and the rescue restores Android), or brom_set_slot.ps1 -Slot a -ConfirmWrite"
}
Log "post-reset state:"
Log (Sh "su -c 'dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null | od -An -tx1'")

# Preserve the warm-reset ramoops records immediately. A manual cold power
# cycle clears DRAM and loses these; the rescue boot can continue Android, but
# capture before doing any more diagnosis/reboots.
if ($verdict -eq 'RESET') {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $pstoreDir = 'artifacts\kernel-build\pstore-' + $stamp
    New-Item -ItemType Directory -Force -Path $pstoreDir | Out-Null
    foreach ($name in @('console-ramoops-0', 'dmesg-ramoops-0', 'pmsg-ramoops-0')) {
        $remote = "/data/local/tmp/diag-$stamp-$name"
        $local = Join-Path $pstoreDir $name
        $copy = Sh ("su -c 'cat /sys/fs/pstore/$name > $remote 2>/dev/null'")
        $pull = (& $Adb pull $remote $local 2>&1 | Out-String).Trim()
        if (Test-Path $local) {
            $size = (Get-Item $local).Length
            Log "pstore capture  : $name ($size bytes) -> $local"
            Sh "su -c 'rm -f $remote'" | Out-Null
        } else {
            Log "pstore missing : $name ($pull)"
        }
    }
}

$lines | Out-File -Append -Encoding utf8 $Out
Write-Host "appended to $Out"
