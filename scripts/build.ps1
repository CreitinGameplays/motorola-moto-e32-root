<#
.SYNOPSIS
    Build the Mali root exploit for 64-bit Android.

.DESCRIPTION
    Cross-compiles scripts/mali/mali_kroot.c (or a given source file) with the
    Android NDK LLVM toolchain. The NDK location is taken from the
    ANDROID_NDK_HOME / ANDROID_NDK_ROOT environment variables, or -Ndk.

.EXAMPLE
    $env:ANDROID_NDK_HOME = "<path-to-android-ndk>"
    .\scripts\build.ps1

.EXAMPLE
    .\scripts\build.ps1 -Source .\scripts\mali\mali_rwtest3.c -Out .\artifacts\mali_rwtest3
#>
param(
    [string]$Ndk = $env:ANDROID_NDK_HOME,
    [string]$Source = (Join-Path (Join-Path $PSScriptRoot "mali") "mali_kroot.c"),
    [string]$Out = "",
    [int]$Api = 30
)

$ErrorActionPreference = "Stop"

if (-not $Ndk) { $Ndk = $env:ANDROID_NDK_ROOT }
if (-not $Ndk) {
    throw "NDK not found: set ANDROID_NDK_HOME (or ANDROID_NDK_ROOT) or pass -Ndk <path>"
}

$hostTag = "windows-x86_64"
$binDir = Join-Path $Ndk "toolchains\llvm\prebuilt\$hostTag\bin"
$clang = Join-Path $binDir "aarch64-linux-android$Api-clang.cmd"
if (-not (Test-Path $clang)) { $clang = Join-Path $binDir "clang.cmd" }
if (-not (Test-Path $clang)) { throw "clang not found under $binDir" }

if (-not $Out) {
    $Out = Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) "artifacts") "mali_kroot"
}
if (-not (Test-Path $Source)) { throw "source not found: $Source" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
& $clang --target="aarch64-linux-android$Api" -static -O2 -Wall -o $Out $Source
if ($LASTEXITCODE -ne 0) { throw "build failed (exit $LASTEXITCODE)" }

Write-Output "built $Out"
