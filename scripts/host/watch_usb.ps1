# Watch USB device transitions while the user power-cycles the phone.
# Logs every appear/disappear of a USB device, plus the Unisoc/Motorola IDs.
# Usage: powershell -ExecutionPolicy Bypass -File watch_usb.ps1 [-Minutes 15]
param([int]$Minutes = 15)

$log = Join-Path $env:TEMP "usbwatch.log"
$end = (Get-Date).AddMinutes($Minutes)
$seen = @{}

function Snapshot {
    Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like "USB\*" -or $_.InstanceId -like "USBSTOR\*" } |
        ForEach-Object { $_.InstanceId }
}

"=== watch start $(Get-Date -Format o) for $Minutes min ===" | Out-File -Append -Encoding utf8 $log
foreach ($id in Snapshot) { $seen[$id] = $true }

while ((Get-Date) -lt $end) {
    Start-Sleep -Milliseconds 1500
    $now = @{}
    foreach ($id in Snapshot) { $now[$id] = $true }

    foreach ($id in $now.Keys) {
        if (-not $seen.ContainsKey($id)) {
            $d = Get-PnpDevice -InstanceId $id -ErrorAction SilentlyContinue
            $name = if ($d) { $d.FriendlyName } else { "?" }
            $cls  = if ($d) { $d.Class } else { "?" }
            "$(Get-Date -Format HH:mm:ss) ADD    $id   [$cls] $name" | Out-File -Append -Encoding utf8 $log
        }
    }
    foreach ($id in $seen.Keys) {
        if (-not $now.ContainsKey($id)) {
            "$(Get-Date -Format HH:mm:ss) REMOVE $id" | Out-File -Append -Encoding utf8 $log
        }
    }
    $seen = $now
}
"=== watch end $(Get-Date -Format o) ===" | Out-File -Append -Encoding utf8 $log