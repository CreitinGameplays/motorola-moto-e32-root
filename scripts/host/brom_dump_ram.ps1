<#
.SYNOPSIS
    Dump a RAM range from the phone over BootROM/FDL, read-only.

.DESCRIPTION
    The kernel paints its progress bands into the bootloader's framebuffer at
    physical 0x9e000000.  Those bands live in DRAM, so if DRAM survives the
    reset that brings the phone into download mode, we can read the progress
    trace back *without looking at the screen* - no timing, no eyes.

    spd_dump implements this as `read_mem <addr> <size> <file>` (FDL2 stage).
    This script drives the same BROM -> FDL1 -> FDL2 -> exec sequence that
    brom_set_slot.ps1 uses, but issues only read_mem, never a write.

    Precondition: the phone must be in download mode with DRAM content from the
    hung boot still present.  That means resetting a hung phone with
    Power + Vol Down held, not a full power-off.

.PARAMETER Addr
    Start address, default 0x9e000000 (lcd_base / paint bands).

.PARAMETER Size
    Bytes to read, default 0x400000 (4 MiB: covers bands 0..31).

.PARAMETER OutDir
    Directory that receives paint_ram.bin.

.PARAMETER MaxAttempts
    How many times to wait for the 1782:4d00 window and retry.

.EXAMPLE
    .\scripts\host\brom_dump_ram.ps1
#>
[CmdletBinding()]
param(
    [string]$Addr = "0x9e000000",
    [string]$Size = "0x400000",
    [string]$OutDir = "artifacts\slot-probe\ram",
    [ValidateSet('brom', 'fdl1', 'fdl2')][string]$Stage = 'brom',
    [int]$MaxAttempts = 6
)

$ErrorActionPreference = 'Continue'

$FirmwareDir = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\withcboot"
$Fdl2Path    = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\candidate_fdl2_readonly.bin"
$spdDir      = "D:\AndroidSDKTools\spd\spd_dump_LibUSB_Release"
$exe         = Join-Path $spdDir "spd_dump.exe"
$fdl1        = Join-Path $FirmwareDir "fdl1-dl.bin"

foreach ($p in @($exe, $fdl1, $Fdl2Path)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$dumpName = "paint_ram.bin"
$dumpPath = Join-Path (Resolve-Path $OutDir) $dumpName

$pathCmd = "path $(Resolve-Path $OutDir)"
$readCmd = "read_mem $Addr $Size $dumpName"
switch ($Stage) {
    # BROM stage only: no FDL is loaded, so nothing has touched DRAM yet.
    'brom' { $seq = @($pathCmd, $readCmd, "reset") }
    # FDL1 only: FDL1 initialises external RAM, which may already wipe DRAM.
    'fdl1' { $seq = @("exec_addr 0x65015f08", "fdl $fdl1 0x65000800",
                      $pathCmd, $readCmd, "reset") }
    # Full chain (proven for partition work): FDL1 + FDL2.
    'fdl2' { $seq = @("exec_addr 0x65015f08", "fdl $fdl1 0x65000800",
                      "fdl $Fdl2Path 0x9efffe00", "exec",
                      $pathCmd, $readCmd, "reset") }
}
$sequence = $seq -join " "
$argv = @("--wait", "30") + @($sequence -split '\s+')

Write-Host "spd_dump $($argv -join ' ')"
Write-Host ""

for ($i = 1; $i -le $MaxAttempts; $i++) {
    if (Test-Path -LiteralPath $dumpPath) { Remove-Item -LiteralPath $dumpPath -Force }
    Write-Host "--- attempt $i at $(Get-Date -Format o) ---"
    Push-Location -LiteralPath $FirmwareDir
    try {
        $out = & $exe @argv 2>&1 | ForEach-Object { "$_" }
        $rc = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $out | ForEach-Object { Write-Host $_ }
    Write-Host "exit=$rc"

    if (Test-Path -LiteralPath $dumpPath) {
        $len = (Get-Item -LiteralPath $dumpPath).Length
        if ($len -gt 0) {
            Write-Host ""
            Write-Host "dump: $dumpPath ($len bytes)"
            $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
            $check = Join-Path $scriptDir "paint_dump_check.py"
            if (Test-Path -LiteralPath $check) {
                & python $check $dumpPath $Addr 0x20000
            }
            exit 0
        }
    }
    Write-Host "no dump yet; retry after re-entering download mode"
    Start-Sleep -Seconds 3
}

throw "no RAM dump obtained after $MaxAttempts attempts"