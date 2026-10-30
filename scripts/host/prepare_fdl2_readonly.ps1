param(
    [string]$InputPath = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\withcboot\fdl2-dl.bin",
    [string]$OutputPath = "D:\AndroidSDKTools\firmware\hawaii_xt2227_fdl\candidate_fdl2_readonly.bin"
)

$bytes = [System.IO.File]::ReadAllBytes($InputPath)
if ($bytes.Length -ne 1174808) { throw "Unexpected FDL2 size: $($bytes.Length)" }

# Verify the exact source instructions before applying either documented gate patch.
$gateExpected = [byte[]](0x3b, 0x21, 0x02, 0x94)
for ($i = 0; $i -lt $gateExpected.Length; $i++) {
    if ($bytes[0x7234 + $i] -ne $gateExpected[$i]) {
        throw ("Unexpected byte at 0x{0:x}: 0x{1:x2}" -f (0x7234 + $i), $bytes[0x7234 + $i])
    }
}

# The supplied FDL2-DL already contains the documented NOPs at 0x812bc.
# Accept only that exact NOP sequence or the exact reported source sequence.
$validationOriginal = [byte[]](0xaa, 0x14, 0x03, 0xe1, 0x2c, 0xdd, 0xff, 0x97, 0x80, 0x00, 0x00, 0x34, 0x60, 0x8e, 0x40, 0xf8, 0x60, 0xff, 0xff, 0xb5)
$validationNops = [byte[]](0x1f, 0x20, 0x03, 0xd5, 0x1f, 0x20, 0x03, 0xd5, 0x1f, 0x20, 0x03, 0xd5, 0x1f, 0x20, 0x03, 0xd5, 0x1f, 0x20, 0x03, 0xd5)
$isOriginal = $true
$isNopped = $true
for ($i = 0; $i -lt $validationOriginal.Length; $i++) {
    if ($bytes[0x812bc + $i] -ne $validationOriginal[$i]) { $isOriginal = $false }
    if ($bytes[0x812bc + $i] -ne $validationNops[$i]) { $isNopped = $false }
}
if (-not ($isOriginal -or $isNopped)) { throw "Unexpected bytes at FDL2 validation site 0x812bc" }

# NOP only the documented write-authorization call. Keep the validation NOPs
# if already present; the stock source variant is also patched here offline.
$bytes[0x7234] = 0x1f
$bytes[0x7235] = 0x20
$bytes[0x7236] = 0x03
$bytes[0x7237] = 0xd5
if ($isOriginal) {
    for ($i = 0x812bc; $i -lt 0x812d0; $i += 4) {
        $bytes[$i] = 0x1f
        $bytes[$i + 1] = 0x20
        $bytes[$i + 2] = 0x03
        $bytes[$i + 3] = 0xd5
    }
}
[System.IO.File]::WriteAllBytes($OutputPath, $bytes)

$check = [System.IO.File]::ReadAllBytes($OutputPath)
$context = for ($i = 0x7230; $i -lt 0x723c; $i += 4) {
    "0x{0:x4}: {1}" -f $i, (($check[$i..($i + 3)] | ForEach-Object { $_.ToString('x2') }) -join ' ')
}
$context += for ($i = 0x812b8; $i -lt 0x812d8; $i += 4) {
    "0x{0:x5}: {1}" -f $i, (($check[$i..($i + 3)] | ForEach-Object { $_.ToString('x2') }) -join ' ')
}

Write-Output "Input SHA256:  $((Get-FileHash $InputPath -Algorithm SHA256).Hash)"
Write-Output "Output SHA256: $((Get-FileHash $OutputPath -Algorithm SHA256).Hash)"
Write-Output $context
Write-Output "Wrote offline candidate only: $OutputPath"
