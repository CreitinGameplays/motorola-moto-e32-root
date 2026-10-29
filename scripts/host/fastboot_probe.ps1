# Non-destructive fastboot probe for the Moto E32 (XT2227-1 / hawaii).
#
# Runs only read-only / informational fastboot commands. It never issues an
# unlock, erase, flash or format command, so it cannot wipe userdata or change
# the lock state.
#
# Usage:
#   adb reboot bootloader
#   .\scripts\host\fastboot_probe.ps1            # prints to stdout
#   .\scripts\host\fastboot_probe.ps1 -OutFile docs/evidence/foo.txt

param(
    [string]$OutFile = ""
)

$ErrorActionPreference = "Continue"

function Probe {
    param([string]$Label, [string[]]$Args)
    Write-Output ""
    Write-Output "===== $Label :: fastboot $($Args -join ' ') ====="
    $out = & fastboot @Args 2>&1 | Out-String
    Write-Output $out.TrimEnd()
}

$lines = @()
$lines += "device: $( & fastboot devices 2>&1 | Out-String )".TrimEnd()

$cmds = @(
    @{ L = "getvar all";               A = @("getvar", "all") },
    @{ L = "getvar current-slot";      A = @("getvar", "current-slot") },
    @{ L = "getvar is-userspace";      A = @("getvar", "is-userspace") },
    @{ L = "getvar unlock_raw_data";   A = @("getvar", "unlock_raw_data") },
    @{ L = "getvar secure";            A = @("getvar", "secure") },
    @{ L = "getvar serialno";          A = @("getvar", "serialno") },
    @{ L = "oem get_identifier_token"; A = @("oem", "get_identifier_token") },
    @{ L = "oem get_unlock_data";      A = @("oem", "get_unlock_data") },
    @{ L = "oem device-info";          A = @("oem", "device-info") },
    @{ L = "oem help";                 A = @("oem", "help") },
    @{ L = "oem getversions";          A = @("oem", "getversions") },
    @{ L = "oem getsecurityversion";   A = @("oem", "getsecurityversion") },
    @{ L = "oem get_unlock_bootloader_nonce"; A = @("oem", "get_unlock_bootloader_nonce") },
    @{ L = "flashing get_unlock_ability";     A = @("flashing", "get_unlock_ability") }
)

foreach ($c in $cmds) {
    $out = & fastboot @($c.A) 2>&1 | Out-String
    $lines += ""
    $lines += "===== $($c.L) :: fastboot $($c.A -join ' ') ====="
    $lines += $out.TrimEnd()
}

$text = $lines -join "`r`n"
if ($OutFile) {
    $dir = Split-Path -Parent $OutFile
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    Set-Content -Path $OutFile -Value $text -Encoding UTF8
    Write-Output "wrote $OutFile"
} else {
    Write-Output $text
}
