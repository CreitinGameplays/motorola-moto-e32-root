param(
    [int]$WaitMinutes = 20,
    # Attempt against the node that is already present instead of insisting on a
    # physical unplug first. A stale BootROM simply times out, so this is safe.
    [switch]$AllowPresent,
    # Number of fresh-BROM windows to try. 0 = a single attempt.
    [int]$MaxAttempts = 0,
    # Partitions to read back (read-only). FDL2 `r <name>` per entry.
    # Comma-separated string so it survives `-File` invocation.
    [string]$Parts = 'splloader',
    [string]$FirmwareDir = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\withcboot",
    [string]$Fdl2Path = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\candidate_fdl2_readonly.bin",
    [string]$ReadDir = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\readback"
)

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

$log = Join-Path $ReadDir "brom_read_spl.log"

function Write-Log {
    param([string]$Text)
    $Text | Out-File -Append -Encoding utf8 $log
    Write-Host $Text
}

function Get-PhoneNodes {
    return @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -or $_.InstanceId -like "*VID_0000&PID_0002*" })
}

function NodePresent {
    return [bool](Get-PhoneNodes)
}

function RealBromPresent {
    $d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -and $_.Status -eq "OK" }
    return [bool]$d
}

Write-Log "=== start $(Get-Date -Format o) ==="
Write-Log "All inputs passed SHA-256 verification."

# Wait until the current node disappears and a new one is enumerated. A BootROM
# session only answers for ~2 minutes, so a window that never vanished is dead.
function Wait-ForFreshNode {
    param([string]$Why)
    Write-Log "Waiting for the current node to disappear ($Why)."
    $until = (Get-Date).AddMinutes($WaitMinutes)
    while ((NodePresent) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 200 }
    if (NodePresent) { Write-Log "Node never disappeared within $WaitMinutes min."; return $false }

    Write-Log "Node gone. Waiting for a fresh 1782:4D00 BootROM (Power + Vol Down, then plug in)."
    $until = (Get-Date).AddMinutes($WaitMinutes)
    while ((-not (RealBromPresent)) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 100 }
    if (-not (RealBromPresent)) { Write-Log "No fresh BootROM within $WaitMinutes min."; return $false }
    Write-Log "Fresh BootROM enumerated at $(Get-Date -Format o)."
    return $true
}

# Safe by construction: execute CVE payload + FDL1/FDL2 in RAM, then list GPT
# and read splloader only. No partition write/erase, cboot, or reset command.
$sequence = @(
    "exec_addr 0x65015f08",
    "fdl $fdl1 0x65000800",
    "fdl $Fdl2Path 0x9efffe00",
    "exec",
    "path $ReadDir",
    "p"
)
foreach ($part in ($Parts -split ',')) {
    $part = $part.Trim()
    if (-not $part) { continue }
    if ($part -notmatch '^[A-Za-z0-9_]+$') { throw "Unsafe partition name: $part" }
    $sequence += "r $part"
}
$sequence += "poweroff"
$sequence = $sequence -join " "
$argv = @("--wait", "30") + @($sequence -split '\s+')

function Invoke-Attempt {
    param([int]$Number)
    $before = @(Get-ChildItem -LiteralPath $ReadDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "brom_read_spl.log" } | ForEach-Object { $_.Name })

    Write-Log ("--- attempt {0} at {1} ---" -f $Number, (Get-Date -Format o))
    # Windows PowerShell 5.1 turns native stderr into ErrorRecords. Do not let
    # the executable's normal version banner terminate the capture pipeline.
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # exec_addr resolves custom_exec_no_verify_<addr>.bin relative to the
    # current working directory, so spd_dump MUST run inside $FirmwareDir.
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
    # A missing CVE payload means the bypass never ran, so FDL1 would be
    # refused. That is a host configuration fault: stop instead of retrying.
    if ($text -match 'does not exist' -or $text -match 'current exec_addr is 0x0') {
        Write-Log "FATAL: exec_addr payload was not found; bypass did not run. Fix the working directory."
        throw "exec_addr payload missing - refusing to continue"
    }
    $staleMode = $text -match 'wrong command or wrong mode'
    $anyConnect = $text -match 'CMD_CONNECT'
    $fdl2Reached = $text -match 'FDL2'

    $after = @(Get-ChildItem -LiteralPath $ReadDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "brom_read_spl.log" } | ForEach-Object { $_.Name })
    $newFiles = @($after | Where-Object { $before -notcontains $_ })
    if ($newFiles.Count -gt 0) { Write-Log ("New readback files: " + ($newFiles -join ", ")) }

    return [pscustomobject]@{
        StaleMode   = $staleMode
        Connected   = $anyConnect
        PayloadSent = ($text -match 'SEND custom_exec_no_verify')
        Fdl2Reached = $fdl2Reached
        NewFiles    = $newFiles
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
        if (-not (RealBromPresent)) { throw "No 1782:4D00 node present within $WaitMinutes minutes." }
    } elseif ($attempt -eq 1 -and -not (NodePresent)) {
        $until = (Get-Date).AddMinutes($WaitMinutes)
        while ((-not (RealBromPresent)) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 100 }
        if (-not (RealBromPresent)) { throw "No BootROM enumerated within $WaitMinutes minutes." }
        Write-Log "BootROM was already absent; using the new enumeration."
    } else {
        if (-not (Wait-ForFreshNode -Why "attempt $attempt needs a live BROM window")) {
            Write-Log "Out of fresh windows; stopping."
            break
        }
    }

    Write-Log "Starting RAM-only FDL sequence at $(Get-Date -Format o)."
    $result = Invoke-Attempt -Number $attempt

    # Any outcome that did not actually reach FDL2 and produce a dump is
    # retryable: expired windows fail in several different ways (silent
    # timeouts, endpoint STALL, send timeout). Only FDL2 is a real result.
    $reachedFdl2 = $result.Fdl2Reached -or ($result.NewFiles.Count -gt 0)
    if ($reachedFdl2) { break }
    Write-Log "Attempt did not reach FDL2. Will retry on the next fresh window."
    if (($MaxAttempts -gt 0) -and ($attempt -ge $MaxAttempts)) {
        Write-Log "Reached MaxAttempts=$MaxAttempts; stopping."
        break
    }
}

if ($result) {
    Write-Log ("Summary: connected={0} payloadSent={1} fdl2={2} stale={3} newFiles={4}" -f
        $result.Connected, $result.PayloadSent, $result.Fdl2Reached, $result.StaleMode, ($result.NewFiles -join ","))
} else {
    Write-Log "Summary: no attempt was executed."
}
Write-Log "=== end $(Get-Date -Format o) ==="