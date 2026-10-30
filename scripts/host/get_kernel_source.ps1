<#
.SYNOPSIS
    Fetch the public Motorola/Unisoc kernel source for the Moto E32 ("hawaii").

.DESCRIPTION
    The Moto E32 (XT2227-1, Unisoc T606 / UMS9230, "qogirl6") runs the
    Motorola/Unisoc 4.14.199 kernel ("Petit Gorille").  Motorola publishes
    that tree in the GPL repository:

        https://github.com/MotorolaMobilityLLC/kernel-sprd
        branch  R-11-release-RORS   (tag MMI-RORS31.193-14-6)

    This script clones it blobless (fast, ~2.4 GB of git objects, ~4 GB
    checked out) and fixes the two Windows specific problems:

      * core.protectNTFS=false  -> allows checkout of "aux.h"/"aux.c"
        (Windows reserved device names; 3 files in this tree)
      * core.autocrlf=false      -> keeps LF line endings, otherwise every
        header differs from the device's IKHEADERS copy

    See docs/10-kernel-source.md for the full analysis.

.EXAMPLE
    .\scripts\host\get_kernel_source.ps1
    .\scripts\host\get_kernel_source.ps1 -Verify
#>
[CmdletBinding()]
param(
    [string]$Dest = 'D:\AndroidSDKTools\kernel-sprd',
    [string]$Branch = 'R-11-release-RORS',
    [string]$Repo = 'https://github.com/MotorolaMobilityLLC/kernel-sprd.git',
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = & git @GitArgs 2>&1 | ForEach-Object { $_.ToString() }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    foreach ($l in $out) { Write-Host "    $l" }
    return $code
}

$parent = Split-Path $Dest -Parent
if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

if (-not (Test-Path (Join-Path $Dest '.git'))) {
    Write-Host "[*] cloning $Repo (blobless) into $Dest ..."
    Invoke-Git clone --filter=blob:none --no-checkout $Repo $Dest | Out-Null
} else {
    Write-Host "[*] reusing existing clone at $Dest"
}

# Windows-friendly checkout settings
Invoke-Git -C $Dest config core.protectNTFS false | Out-Null   # reserved names (aux.h)
Invoke-Git -C $Dest config core.autocrlf false | Out-Null      # keep LF (kernel sources)
Invoke-Git -C $Dest config core.symlinks false | Out-Null      # no symlink support on NTFS

$head = (& git -C $Dest rev-parse $Branch 2>$null)
Write-Host "[*] branch $Branch = $head"
Write-Host "[*] checking out $Branch (git reports 3 'aux.*' errors on Windows - they are reserved device names)"
Invoke-Git -C $Dest checkout -f $Branch | Out-Null

$files = (Get-ChildItem $Dest -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "[+] $files files in $Dest"

Write-Host ""
Write-Host "Next steps:"
Write-Host "  * board files : arch/arm64/boot/dts/sprd/ums9230-4h10-overlay.dts"
Write-Host "  * defconfig   : arch/arm64/configs/sprd_qogirl6_defconfig"
Write-Host "  * release cfg : sprd-diffconfig/androidr/qogirl6/arm64/"
Write-Host "  * version     : Makefile -> 4.14.199 'Petit Gorille'"

# The public snapshot is 16 months older than the shipping kernel; apply the
# measured header delta so that the tree matches the running kernel's headers
# again (see docs/10-kernel-source.md).
$deltaScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                       'scripts\host\apply_shipping_header_delta.py'
if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "[*] applying the measured RORS31.335-58-1 header delta ..."
    python $deltaScript --tree $Dest | ForEach-Object { "    $_" }

    # ... and the matching .c half (fs/file.c, fs/file_table.c, mm/rmap.c):
    # without it the backported headers do not compile.
    $codeScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) `
                           'scripts\host\apply_shipping_code_delta.py'
    Write-Host "[*] applying the matching RORS31.335-58-1 code delta + build fixes ..."
    python $codeScript --tree $Dest | ForEach-Object { "    $_" }
}

if ($Verify) {
    $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Warning "python not found, skipping verification"; return
    }
    $kh = Join-Path $root 'artifacts\kheaders_full'
    $cfg = Join-Path $root 'artifacts\kernel-config'
    if (-not (Test-Path $kh)) { $kh = Join-Path $root 'artifacts\kheaders' }
    if (-not (Test-Path $cfg)) { Write-Warning "artifacts\kernel-config missing, skipping"; return }
    $def = Join-Path $Dest 'arch\arm64\configs\sprd_qogirl6_defconfig'
    $d1 = Join-Path $Dest 'sprd-diffconfig\androidr\qogirl6\arm64\aarch64_user_diff_config'
    $d2 = Join-Path $Dest 'sprd-diffconfig\androidr\qogirl6\arm64\ums9230_4h10_diff_config'
    $d3 = Join-Path $root 'artifacts\kernel-src\reconstructed_release_diff_config'
    $diffArgs = @('--diffconfig', $d1, '--diffconfig', $d2)
    if (Test-Path $d3) { $diffArgs += @('--diffconfig', $d3) }
    python (Join-Path $root 'scripts\host\compare_kernel_source.py') `
        --tree $Dest --kheaders $kh --config $cfg `
        --defconfig $def @diffArgs `
        --out (Join-Path $root 'artifacts\kernel-src\source_vs_device.md')
}
