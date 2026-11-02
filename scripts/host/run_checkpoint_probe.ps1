<#
.SYNOPSIS
    Run a PSCI checkpoint positive control, then one selected boundary probe.

.DESCRIPTION
    This is intentionally a dry run unless -ExecuteOnDevice and the exact
    confirmation token are supplied. The positive-control image must contain
    a direct SYSTEM_RESET hook at a checkpoint independently known to execute.
    The target image contains one setup/initcall checkpoint selector.

    Each device attempt delegates to run_boot_b_test.ps1, which uses the
    one-attempt boot_b/rescue path and captures ramoops as soon as Android
    returns. A failed positive control stops the workflow before the target
    image is written. A missing pstore breadcrumb is not evidence that an
    early checkpoint was missed: do_basic_setup() runs before ramoops_init().
    Both inputs must be packaged Android boot images (ANDROID! magic); raw
    kernel Images are rejected before any device access.

    No device test is authorized by merely creating this script.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PositiveControlImage,
    [Parameter(Mandatory = $true)][string]$PositiveControlLabel,
    [Parameter(Mandatory = $true)][string]$TargetImage,
    [Parameter(Mandatory = $true)][string]$TargetLabel,
    [string]$Adb = 'D:\AndroidSDKTools\adb\adb.exe',
    [int]$WaitSeconds = 900,
    [switch]$RequireTargetBreadcrumb,
    [switch]$ExecuteOnDevice,
    [string]$Confirm
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runner = Join-Path $PSScriptRoot 'run_boot_b_test.ps1'
$reroot = Join-Path $PSScriptRoot 'restore_magisk_after_rescue.ps1'
$evidenceRoot = Join-Path $repoRoot 'docs\evidence'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$controlOut = Join-Path $evidenceRoot "$stamp-checkpoint-positive-control.txt"
$rerootOut = Join-Path $evidenceRoot "$stamp-magisk-reroot.txt"
$targetOut = Join-Path $evidenceRoot "$stamp-checkpoint-target.txt"
$manifest = Join-Path $evidenceRoot "$stamp-checkpoint-probe.txt"

function Get-ImageInfo([string]$Path) {
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        $Path = Join-Path $repoRoot $Path
    }
    $resolved = (Resolve-Path $Path).Path
    $item = Get-Item $resolved
    if ($item.Length -gt 67108864) {
        throw "image exceeds the boot_b partition size: $resolved"
    }
    $stream = [System.IO.File]::OpenRead($resolved)
    try {
        $magic = New-Object byte[] 8
        if ($stream.Read($magic, 0, 8) -ne 8 -or
            [System.Text.Encoding]::ASCII.GetString($magic) -ne 'ANDROID!') {
            throw "not an Android boot image (raw kernel Images are not flashable here): $resolved"
        }
    } finally {
        $stream.Dispose()
    }
    return [pscustomobject]@{
        Path = $resolved
        Bytes = $item.Length
        Sha256 = (Get-FileHash $resolved -Algorithm SHA256).Hash.ToLower()
    }
}

$control = Get-ImageInfo $PositiveControlImage
$target = Get-ImageInfo $TargetImage

$manifestLines = New-Object System.Collections.Generic.List[string]
$manifestLines.Add("PSCI checkpoint probe plan, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$manifestLines.Add("positive-control image: $($control.Path)")
$manifestLines.Add("  bytes=$($control.Bytes) sha256=$($control.Sha256)")
$manifestLines.Add("positive-control label: $PositiveControlLabel")
$manifestLines.Add("target image: $($target.Path)")
$manifestLines.Add("  bytes=$($target.Bytes) sha256=$($target.Sha256)")
$manifestLines.Add("target label: $TargetLabel")
$manifestLines.Add("target pstore breadcrumb required: $([bool]$RequireTargetBreadcrumb)")
$manifestLines.Add("runner outputs: $controlOut ; $rerootOut ; $targetOut")

if (-not $ExecuteOnDevice) {
    $manifestLines.Add('MODE: DRY-RUN; no ADB command or device write was issued.')
    $manifestLines | Out-File -Encoding utf8 $manifest
    Write-Host "DRY-RUN only; no device access. Manifest: $manifest"
    Write-Host "To execute later, first verify capture and rescue, then pass -ExecuteOnDevice and the required confirmation token."
    return
}

if ($Confirm -cne 'I_VERIFIED_CAPTURE_AND_RESCUE_PATH') {
    throw 'execution requires -Confirm I_VERIFIED_CAPTURE_AND_RESCUE_PATH'
}
if ($control.Sha256 -eq $target.Sha256) {
    throw 'positive-control and target images have identical hashes'
}

$manifestLines.Add('MODE: DEVICE EXECUTION explicitly confirmed.')
$manifestLines.Add("start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$manifestLines | Out-File -Encoding utf8 $manifest

$controlArgs = @{
    Image = $control.Path
    Adb = $Adb
    WaitSeconds = $WaitSeconds
    Out = $controlOut
    CheckpointLabel = $PositiveControlLabel
    RequireReset = $true
}
try {
    & $runner @controlArgs
    $controlLog = if (Test-Path $controlOut) { Get-Content $controlOut -Raw } else { '' }
    if ($controlLog -notmatch '(?m)^VERDICT:\s+RESET\b') {
        throw 'positive-control runner did not record VERDICT: RESET'
    }
    $manifestLines.Add("positive control: RESET observed; output=$controlOut")
    $manifestLines | Out-File -Append -Encoding utf8 $manifest

    & $reroot -Adb $Adb -MagiskImage 'D:\AndroidSDKTools\pi\boot_magisk_avb.img' `
        -WaitSeconds $WaitSeconds -Out $rerootOut
    $rerootLog = if (Test-Path $rerootOut) { Get-Content $rerootOut -Raw } else { '' }
    if ($rerootLog -notmatch 'verified: boot_b is the known-good Magisk image') {
        throw 'Magisk re-root did not record its verified completion state'
    }
    $manifestLines.Add("Magisk restored and verified Enforcing before target; output=$rerootOut")
    $manifestLines | Out-File -Append -Encoding utf8 $manifest
} catch {
    $manifestLines.Add("positive control/re-root FAILED; target was not run: $($_.Exception.Message)")
    $manifestLines | Out-File -Append -Encoding utf8 $manifest
    throw "positive control or Magisk re-root failed; refusing to write the target image. See $controlOut, $rerootOut, and $manifest"
}

$targetArgs = @{
    Image = $target.Path
    Adb = $Adb
    WaitSeconds = $WaitSeconds
    Out = $targetOut
    CheckpointLabel = $TargetLabel
    RequireReset = $true
}
if ($RequireTargetBreadcrumb) {
    $targetArgs.RequireCheckpointBreadcrumb = $true
}
try {
    & $runner @targetArgs
    $targetLog = if (Test-Path $targetOut) { Get-Content $targetOut -Raw } else { '' }
    if ($targetLog -notmatch '(?m)^VERDICT:\s+RESET\b') {
        throw 'target runner did not record VERDICT: RESET'
    }
    $manifestLines.Add("target: RESET observed; checkpoint reached according to the validated control; output=$targetOut")
} catch {
    $targetLog = if (Test-Path $targetOut) { Get-Content $targetOut -Raw } else { '' }
    if ($targetLog -match '(?m)^VERDICT:\s+HANG\b') {
        $manifestLines.Add("target: NO RESET observed (checkpoint not reached, reset failure, or recovery failure); output=$targetOut")
        $manifestLines.Add('The device may still need a manual power cycle to enter the one-attempt slot-a rescue path.')
        Write-Warning 'The phone may still be stalled. If ADB did not return, power-cycle only when ready to let the one-attempt slot-a rescue recover it.'
    } else {
        $manifestLines.Add("target: TEST ERROR: $($_.Exception.Message); output=$targetOut")
    }
    $manifestLines | Out-File -Append -Encoding utf8 $manifest
    throw "target probe did not complete successfully; see $targetOut and $manifest"
}

$manifestLines.Add("finish: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$manifestLines | Out-File -Append -Encoding utf8 $manifest
Write-Host "checkpoint probe complete. Manifest: $manifest"
