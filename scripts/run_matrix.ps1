# Reliability matrix for the Mali root exploit.
#
# Runs artifacts/mali_kroot on the connected device N times and reports
# success. Use -Reboot to start every cycle from a fresh boot (the realistic
# user scenario), or omit it to test repeated runs in the same boot.
#
#   .\scripts\run_matrix.ps1                 # 5 cycles, fresh boot each
#   .\scripts\run_matrix.ps1 -Cycles 3 -NoReboot
#
param(
    [int]$Cycles = 5,
    [switch]$NoReboot,
    [string]$Serial = "",
    [int]$SettleSeconds = 15
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$artifacts = Join-Path $root "artifacts"
$binary = Join-Path $artifacts "mali_kroot"

if (-not (Test-Path $binary)) {
    throw "missing $binary - build it first (aarch64-linux-android30-clang -static -O2 scripts/mali/mali_kroot.c)"
}

$adbArgs = @()
if ($Serial) { $adbArgs = @("-s", $Serial) }

function Invoke-Adb([string]$cmd) {
    & adb @adbArgs shell $cmd 2>&1
}

& adb @adbArgs push $binary /data/local/tmp/mali_kroot | Out-Null
Invoke-Adb "chmod 755 /data/local/tmp/mali_kroot" | Out-Null

$results = @()
for ($i = 1; $i -le $Cycles; $i++) {
    if (-not $NoReboot) {
        & adb @adbArgs reboot | Out-Null
        & adb @adbArgs wait-for-device | Out-Null
        $n = 0
        do {
            Start-Sleep -Seconds 2
            $boot = (Invoke-Adb "getprop sys.boot_completed") -join ""
            $n++
        } while ($boot -notmatch "1" -and $n -lt 90)
        Start-Sleep -Seconds $SettleSeconds
    }

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = (Invoke-Adb "/data/local/tmp/mali_kroot") -join "`n"
    $sw.Stop()

    $log = Join-Path $artifacts ("matrix_run_{0}.txt" -f $i)
    $out | Out-File -Encoding utf8 $log

    $ok = $out -match "ROOTPROOF_0_Permissive"
    $validated = $out -match "validated pg="
    $attempts = [regex]::Matches($out, "attempt (\d)/4")
    $attempt = if ($attempts.Count) { $attempts[$attempts.Count - 1].Groups[1].Value } else { "?" }

    $results += [pscustomobject]@{
        Run       = $i
        OK        = $ok
        Validated = $validated
        Attempt   = $attempt
        Seconds   = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        Log       = $log
    }
    Write-Output ("run {0}: OK={1} validated={2} attempt={3} {4}s" -f $i, $ok, $validated, $attempt, $results[-1].Seconds)
}

$results | Format-Table -AutoSize
$good = ($results | Where-Object { $_.OK }).Count
Write-Output ("{0}/{1} runs rooted" -f $good, $Cycles)
if ($good -ne $Cycles) { exit 1 }
