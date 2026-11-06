# Restore the Magisk daily-driver boot_b after the rescue flashed the
# stock image back.  Automates the manual cycle from
# docs/14-brom-recovery-runbook.md / docs/19-rescue-image-howto.md:
#
#   1. wait for adb + a booted Android (stock boot_b, no root),
#   2. push the Magisk boot image + mali_kroot (the exploit is allowed
#      here: the next step reboots, so the SELinux-permissive side
#      effect never reaches an integrity-test boot),
#   3. verify boot_b is the stock image (refuse to touch anything else),
#   4. dd the Magisk image over boot_b, sync, verify the readback,
#   5. reboot and wait for `su` to answer.
#
# Usage (from the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass `
#     -File scripts\host\restore_magisk_boot_b.ps1 `
#     [-Image artifacts\kernel-build\magisk_boot_b_2026-11-01.img]
#
# The two sha256 checks below are the byte-exact identities from the
# docs; if either changes, the docs need updating first.
param(
	[string]$Image = "artifacts/kernel-build/magisk_boot_b_2026-11-01.img"
)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ($env:ADB) {
	$Adb = $env:ADB
} else {
	$Adb = "D:/AndroidSDKTools/adb/adb.exe"
}
$StockSha = "ccd0faff51ab24d921b2671c562f0fe08e7a1ba2b7f19bb93a5f2650eb4f7b18"
$MagiskSha = "90416c09f6359fdcc0711f36e214454421c42598518787f58c1916be6c5cad3c"

function AdbShell($cmd) {
	(& $Adb shell $cmd 2>&1 | Out-String).Trim()
}

Write-Output "waiting for adb + boot_completed..."
for ($i = 0; $i -lt 120; $i++) {
	$b = AdbShell "getprop sys.boot_completed"
	if ($b -eq "1") { break }
	Start-Sleep -Seconds 5
}
if ($b -ne "1") { Write-Output "no booted Android after 10 min"; exit 1 }
Write-Output "Android is up"

$img = Join-Path $repo $Image
if (-not (Test-Path $img)) { Write-Output "missing image: $img"; exit 1 }
Write-Output "pushing $Image and mali_kroot..."
& $Adb push $img /data/local/tmp/magisk_restore.img 2>&1 | Out-Null
& $Adb push (Join-Path $repo "artifacts/mali_kroot") /data/local/tmp/mali_kroot 2>&1 | Out-Null
AdbShell "chmod 755 /data/local/tmp/mali_kroot" | Out-Null

# everything privileged runs inside ONE mali_kroot session: the exploit
# leaves SELinux permissive until reboot, which is fine - step 5 reboots
$script = @'
set -e
/data/local/tmp/mali_kroot >/dev/null 2>&1
echo "uid=$(id -u)"
cur=$(dd if=/dev/block/by-name/boot_b bs=1M count=64 2>/dev/null | sha256sum | cut -d" " -f1)
echo "current boot_b: $cur"
if [ "$cur" != "ccd0faff51ab24d921b2671c562f0fe08e7a1ba2b7f19bb93a5f2650eb4f7b18" ]; then
	echo "REFUSED: boot_b is not the stock image (already Magisk? nothing to do)"
	exit 2
fi
dd if=/data/local/tmp/magisk_restore.img of=/dev/block/by-name/boot_b bs=1M
sync
new=$(dd if=/dev/block/by-name/boot_b bs=1M count=64 2>/dev/null | sha256sum | cut -d" " -f1)
echo "new boot_b: $new"
if [ "$new" != "90416c09f6359fdcc0711f36e214454421c42598518787f58c1916be6c5cad3c" ]; then
	echo "FAILED: readback does not match the Magisk image"
	exit 3
fi
echo "boot_b = Magisk daily driver, verified"
rm -f /data/local/tmp/magisk_restore.img
'@
$tmp = Join-Path $env:TEMP "restore_boot_b.sh"
Set-Content -Path $tmp -Value $script -NoNewline
& $Adb push $tmp /data/local/tmp/restore_boot_b.sh | Out-Null
Remove-Item $tmp
AdbShell "chmod 755 /data/local/tmp/restore_boot_b.sh" | Out-Null
Write-Output (AdbShell "sh /data/local/tmp/restore_boot_b.sh")

Write-Output "rebooting into the Magisk daily driver..."
& $Adb reboot | Out-Null
for ($i = 0; $i -lt 120; $i++) {
	Start-Sleep -Seconds 5
	$b = AdbShell "getprop sys.boot_completed"
	$s = AdbShell "su -c 'id -u'"
	if ($b -eq "1" -and $s -eq "0") {
		Write-Output "DONE: Android booted, su = 0 - ready for the next boot_b test"
		AdbShell "rm -f /data/local/tmp/restore_boot_b.sh"
		exit 0
	}
}
Write-Output "reboot finished but su did not answer - check manually"
exit 1
