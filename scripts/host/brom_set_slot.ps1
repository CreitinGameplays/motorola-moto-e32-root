param(
    [ValidateSet("a", "b")][string]$Slot = "a",
    [int]$WaitMinutes = 45,
    [int]$MaxAttempts = 20,
    [switch]$AllowPresent,
    # Writing requires this switch. Without it the script only reports the plan.
    [switch]$ConfirmWrite,
    [string]$FirmwareDir = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\withcboot",
    [string]$Fdl2Path = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\candidate_fdl2_readonly.bin",
    [string]$ReadDir = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\readback_write"
)

# Purpose: force the A/B metadata in `misc` to select one slot, then verify by
# reading the block back, then reset. This writes exactly 32 bytes at
# misc+0x800 (a scratch metadata block Android rewrites on every boot), through
# the tool's own set_active implementation:
#   chosen slot: priority 15, tries 6, successful 0
#   other slot : priority 14, tries 1, successful 0
#   slot_suffix set to "_{Slot}", crc32_le recomputed over the first 28 bytes.
#
# Restore path if anything looks wrong: write the saved block back, or use an
# unmodified misc image and `wof misc 0x800 <file>`.

$ErrorActionPreference = "Stop"
$spdDir = "D:\AndroidSDKTools\spd\spd_dump_LibUSB_Release"
$exe = Join-Path $spdDir "spd_dump.exe"
$payload = Join-Path $FirmwareDir "custom_exec_no_verify_65015f08.bin"
$fdl1 = Join-Path $FirmwareDir "fdl1-dl.bin"

$expected = @{
    $payload = "32D8B796FF484C168D7FC63D9ED75D056D0833B55C7D65FBDAF2C548474F3C62"
    $fdl1 = "153F3A33074D6EE9AE22EBD9580ADDCBBA6970B45C5D6A6E6D5B23723C259C15"
    (Join-Path $FirmwareDir "fdl2-dl.bin") = "499F75FBC911CFFD8E44ED8E8F23F83C8090F677F79E3885FFD011FDCBA2F6BF"
    $Fdl2Path = "06ED520CB4B273782649B1481BC3860DB790BFFAC1594A6DC8180882A61D29C2"
}
foreach ($path in $expected.Keys) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required file missing: $path" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $expected[$path]) { throw "Hash mismatch for $path ($actual)" }
}
if (-not (Test-Path -LiteralPath $exe)) { throw "spd_dump missing: $exe" }
New-Item -ItemType Directory -Force -Path $ReadDir | Out-Null

$log = Join-Path $ReadDir "brom_set_slot.log"

function Write-Log {
    param([string]$Text)
    $Text | Out-File -Append -Encoding utf8 $log
    Write-Host $Text
}

function NodePresent {
    return [bool](Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -or $_.InstanceId -like "*VID_0000&PID_0002*" })
}

function RealBromPresent {
    return [bool](Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -and $_.Status -eq "OK" })
}

Write-Log "=== start $(Get-Date -Format o) ==="
Write-Log "All inputs passed SHA-256 verification."
Write-Log "Target slot: $Slot"

if (-not $ConfirmWrite) {
    Write-Log "DRY RUN: no -ConfirmWrite, so nothing will be written."
    Write-Log "Planned sequence: exec_addr, fdl1, fdl2, exec, set_active $Slot, r misc, reset"
    Write-Log "To execute: add -ConfirmWrite"
    Write-Log "=== end $(Get-Date -Format o) ==="
    return
}

# Keep a copy of the current block so it can be restored byte for byte.
# The hash is the verified live dump (18:25): a=0x008e, b=0x000f, suffix _b.
$prevMisc = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\readback\misc.bin"
$knownLive = "DFC266B5DD8975DEB176247B3A35189C2AA16209BBFE57386D2EF88941250E01"
$backup = Join-Path $ReadDir "misc_before_setslot.bin"
if (-not (Test-Path -LiteralPath $prevMisc)) {
    throw "No verified pre-write misc dump at $prevMisc - refusing to write without a rollback copy."
}
$h = (Get-FileHash -LiteralPath $prevMisc -Algorithm SHA256).Hash
if ($h -ne $knownLive) {
    throw "Pre-write misc dump hash $h does not match the verified live image $knownLive - re-read misc first."
}
Copy-Item -LiteralPath $prevMisc -Destination $backup -Force
Write-Log "Saved verified pre-write misc image to $backup (SHA-256 $h)"

$sequence = @(
    "exec_addr 0x65015f08",
    "fdl $fdl1 0x65000800",
    "fdl $Fdl2Path 0x9efffe00",
    "exec",
    "path $ReadDir",
    "set_active $Slot",
    "r misc",
    "reset"
) -join " "
$argv = @("--wait", "30") + @($sequence -split '\s+')

function Invoke-Attempt {
    param([int]$Number)
    $target = Join-Path $ReadDir "misc.bin"
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }

    Write-Log ("--- attempt {0} at {1} ---" -f $Number, (Get-Date -Format o))
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Push-Location -LiteralPath $FirmwareDir
    try {
        $output = & $exe @argv 2>&1 | ForEach-Object { "$_" }
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $oldPreference
    }
    foreach ($line in $output) { Write-Log $line }
    Write-Log "spd_dump exit code: $exitCode"

    $text = ($output -join "`n")
    if ($text -match 'does not exist' -or $text -match 'current exec_addr is 0x0') {
        Write-Log "FATAL: exec_addr payload was not found; bypass did not run."
        throw "exec_addr payload missing"
    }
    return [pscustomobject]@{
        Fdl2Reached = ($text -match 'FDL2')
        Wrote       = ($text -match 'Reading Partition List' -and (Test-Path -LiteralPath $target))
        MiscFile    = $target
        ExitCode    = $exitCode
    }
}

$attempt = 0
$result = $null
while ($true) {
    $attempt++

    if ($attempt -eq 1 -and $AllowPresent) {
        Write-Log "AllowPresent: attempting the node that is already enumerated."
        $until = (Get-Date).AddMinutes($WaitMinutes)
        while ((-not (RealBromPresent)) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 150 }
        if (-not (RealBromPresent)) { throw "No node present within $WaitMinutes minutes." }
    } else {
        if ((NodePresent) -and -not ($attempt -eq 1 -and $AllowPresent)) {
            Write-Log "Waiting for the current node to disappear."
            $until = (Get-Date).AddMinutes($WaitMinutes)
            while ((NodePresent) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 200 }
        }
        Write-Log "Waiting for a fresh 1782:4D00 BootROM."
        $until = (Get-Date).AddMinutes($WaitMinutes)
        while ((-not (RealBromPresent)) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 100 }
        if (-not (RealBromPresent)) { Write-Log "No fresh BootROM within $WaitMinutes min."; break }
        Write-Log "Fresh BootROM at $(Get-Date -Format o)."
    }

    $result = Invoke-Attempt -Number $attempt
    if ($result.Fdl2Reached) { break }
    Write-Log "Attempt did not reach FDL2; retrying on the next fresh window."
    if (($MaxAttempts -gt 0) -and ($attempt -ge $MaxAttempts)) { Write-Log "MaxAttempts reached."; break }
}

if ($result -and (Test-Path -LiteralPath $result.MiscFile)) {
    Write-Log "Read back the misc block after the write: $($result.MiscFile)"
    $py = Join-Path $PSScriptRoot "misc_ab.py"
    $decode = python $py $result.MiscFile 2>&1 | Out-String
    foreach ($line in ($decode -split "`r?`n")) { if ($line) { Write-Log $line } }
} else {
    Write-Log "No post-write misc dump was produced."
}
Write-Log "=== end $(Get-Date -Format o) ==="