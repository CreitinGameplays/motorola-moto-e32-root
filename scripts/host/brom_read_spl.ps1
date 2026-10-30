param(
    [int]$WaitMinutes = 20,
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

function PhoneNodePresent {
    $d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -or $_.InstanceId -like "*VID_0000&PID_0002*" }
    return [bool]$d
}

function RealBromPresent {
    $d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -and $_.Status -eq "OK" }
    return [bool]$d
}

$log = Join-Path $ReadDir "brom_read_spl.log"
"=== start $(Get-Date -Format o) ===" | Out-File -Encoding utf8 $log
"All inputs passed SHA-256 verification." | Out-File -Append -Encoding utf8 $log

if (PhoneNodePresent) {
    "Waiting for current USB node to disappear; unplug the cable now." | Out-File -Append -Encoding utf8 $log
    $until = (Get-Date).AddMinutes($WaitMinutes)
    while ((PhoneNodePresent) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 250 }
    if (PhoneNodePresent) { throw "Current node did not disappear within $WaitMinutes minutes." }
}

"Waiting for a fresh 1782:4D00 BootROM. Enter it with Power + Vol Down, then plug in." | Out-File -Append -Encoding utf8 $log
$until = (Get-Date).AddMinutes($WaitMinutes)
while ((-not (RealBromPresent)) -and ((Get-Date) -lt $until)) { Start-Sleep -Milliseconds 150 }
if (-not (RealBromPresent)) { throw "No real BootROM enumerated within $WaitMinutes minutes." }

"Fresh BootROM at $(Get-Date -Format o). Starting RAM-only FDL sequence." | Out-File -Append -Encoding utf8 $log

# Safe by construction: execute CVE payload + FDL1/FDL2 in RAM, then list GPT
# and read splloader only. No partition write/erase, cboot, or reset command.
$commands = @(
    "exec_addr 0x65015f08",
    "fdl `"$fdl1`" 0x65000800",
    "fdl `"$Fdl2Path`" 0x9efffe00",
    "exec",
    "path `"$ReadDir`"",
    "p",
    "r splloader"
) -join " "
$argv = @("--wait", "30") + @($commands -split '\s+')

Push-Location $FirmwareDir
try {
    $output = & $exe @argv 2>&1 | Out-String
    $output | Tee-Object -FilePath $log -Append
} finally {
    Pop-Location
}

"=== end $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log
