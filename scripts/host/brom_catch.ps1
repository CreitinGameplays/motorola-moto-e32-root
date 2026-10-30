# Catch a FRESH Unisoc BootROM enumeration and immediately read its state.
#
# Why this exists (see docs/13-recovery-brom.md):
#   * A BootROM node that has been sitting on the bus enumerates, but its
#     command handler is idle and it answers nothing. spd_dump then reports
#     "wrong command or wrong mode detected".
#   * A BootROM entered with Power + Vol Down answers immediately
#     (CHECK_BAUD -> BSL_REP_VER "SPRD3") but only for a couple of minutes.
#   * So we must wait for the current node to disappear, then fire the very
#     instant a NEW 1782:4D00 node enumerates.
#
# The default command set is read-only on purpose. All of these are
# BootROM-stage reads (spd_cmd.h):
#   0x07 BSL_CMD_READ_CHIP_TYPE   -> 0x94
#   0x0D BSL_CMD_READ_FLASH_INFO  -> 0x9B
#   0x2D BSL_CMD_READ_PARTITION   -> 0xBA
#   0x1A BSL_CMD_READ_CHIP_UID    -> 0xAB
#   0x19 BSL_CMD_CHECK_ROOT       -> 0xA7 / 0x80
# None of them writes storage. Do NOT put 0x2A (SET_FIRST_MODE), 0x49
# (WRITE_PARTITION_VALUE) or 0x47 (WRITE_EFUSE) in here.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File brom_catch.ps1 [-Attempts 12]
#
# Procedure while this runs:
#   1. unplug the cable, wait ~5 s (the catcher logs "device gone")
#   2. hold Volume Down
#   3. with Volume Down held, press and hold Power ~4 s
#   4. keep Volume Down held, plug the cable in, hold 2 s, release
param(
    [int]$Attempts = 12,
    [string]$Cmd = "sendcmdv 0x07 0 sendcmdv 0x0D 0 sendcmdv 0x2D 0 sendcmdv 0x1A 0 sendcmdv 0x19 0"
)

$spdDir = "D:\AndroidSDKTools\spd\spd_dump_LibUSB_Release"
$exe    = Join-Path $spdDir "spd_dump.exe"
$log    = Join-Path $env:TEMP "bromcatch.log"

function PhoneNodePresent {
    $d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
         Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -or $_.InstanceId -like "*VID_0000&PID_0002*" }
    return [bool]$d
}

function RealBromPresent {
    # only a node whose descriptors were read successfully
    $d = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
         Where-Object { $_.InstanceId -like "*VID_1782&PID_4D00*" -and $_.Status -eq "OK" }
    return [bool]$d
}

function Note($text) {
    "$(Get-Date -Format HH:mm:ss) $text" | Out-File -Append -Encoding utf8 $log
}

"=== brom catch start $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log
Note "cmd: $Cmd"
Note "waiting for the phone node to disappear (unplug the cable now)"

$gotResponse = $false

for ($a = 1; $a -le $Attempts; $a++) {
    if (-not (PhoneNodePresent)) { break }

    # 1. wait for the current (stale) node to go away
    $t0 = Get-Date
    while ((PhoneNodePresent) -and ((Get-Date) -lt $t0.AddMinutes(10))) {
        Start-Sleep -Milliseconds 400
    }
    if (PhoneNodePresent) {
        Note "attempt ${a}: node never disappeared after 10 min - stopping"
        break
    }
    Note "attempt ${a}: node gone, waiting for a fresh BootROM"

    # 2. wait for a node that actually enumerated
    $t0 = Get-Date
    while ((-not (RealBromPresent)) -and ((Get-Date) -lt $t0.AddMinutes(10))) {
        Start-Sleep -Milliseconds 200
    }
    if (-not (RealBromPresent)) {
        Note "attempt ${a}: no real 1782:4D00 within 10 min"
        continue
    }
    Note "attempt ${a}: REAL BootROM enumerated - firing immediately"

    # 3. pounce: no extra sleep, the idle window is short
    Push-Location $spdDir
    $argv = $Cmd -split '\s+' | Where-Object { $_ -ne "" }
    $out = & $exe --wait 20 @argv 2>&1 | Out-String
    Pop-Location

    "--- spd_dump output (attempt ${a}) ---" | Out-File -Append -Encoding utf8 $log
    $out | Out-File -Append -Encoding utf8 $log
    "--- end attempt ${a} ---" | Out-File -Append -Encoding utf8 $log

    if ($out -match "BSL_REP_VER") {
        Note "attempt ${a}: BootROM answered (BSL_REP_VER seen)"
        $gotResponse = $true
        break
    }
    Note "attempt ${a}: no answer, retrying"

    # let the node settle so the next pass waits for a genuine removal
    Start-Sleep -Seconds 2
}

if (-not $gotResponse) { Note "finished without a BootROM response" }
"=== brom catch end $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log