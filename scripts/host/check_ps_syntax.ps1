param([string]$Path)
$errs = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errs) | Out-Null
if ($errs -and $errs.Count -gt 0) {
    foreach ($e in $errs) { Write-Output ("line {0}: {1}" -f $e.Extent.StartLineNumber, $e.Message) }
    exit 1
}
Write-Output "syntax OK: $Path"
exit 0