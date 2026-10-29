# 08 - Debloat (Motorola / OOBE / Facebook)

After the unlock and the `/data` wipe, the setup wizard reinstalled
Motorola's app suggestions. Everything below was removed with adb, no root
needed (`pm uninstall` works from the `shell` uid on this build).

Script: `scripts/device/debloat.sh` (list is reviewable and re-runnable).

## What was removed

### System packages (`pm uninstall -k --user 0`)

The APK stays on the read-only system partition, so this is reversible with
`pm install-existing <package>` and is undone by a factory reset.

| package | what it is |
|---|---|
| `com.aura.oobe.motorola` | the OOBE "app suggestions" installer - the component that auto-installed the games/apps during setup; removing it stops that happening again |
| `android.autoinstalls.config.motorola.layout` | OOBE layout config, only used during initial setup |
| `com.facebook.appmanager` / `.services` / `.system` | Facebook background services/updater |
| `com.motorola.brapps` | regional (Brazil) app bundle |
| `com.motorola.help` | Moto Help |
| `com.motorola.motocare` | Moto Care / diagnostics |
| `com.motorola.motosignature.app` | Moto Signature |
| `com.motorola.genie` | Moto Genie / device advice |
| `com.motorola.demo` | retail demo mode |
| `com.motorola.ccc.notification` | Motorola cloud notification service |
| `com.motorola.ccc.mainplm` | Motorola cloud/PLM service |
| `com.motorola.ccc.devicemanagement` | Motorola device management |
| `com.motorola.ccc.ota` | Motorola OTA updater (removed on request - **system updates are disabled**) |
| `com.motorola.bach.modemstats` | modem statistics/telemetry collector |
| `com.lenovo.lsf.user` | Lenovo account framework (Moto sign-in) |
| `com.motorola.motocit` | factory hardware test app (Moto CIT) |
| `com.ontim.fmradio` | FM radio app |

### Third-party packages (`pm uninstall`, fully removed)

| package | installer |
|---|---|
| `com.amelosinteractive.snake` | `com.aura.oobe.motorola` |
| `com.block.juggle` | `com.aura.oobe.motorola` |
| `com.shopee.br` | `com.aura.oobe.motorola` |
| `com.vitastudio.mahjong` | `com.aura.oobe.motorola` |
| `in.playsimple.triple.tile.matchgame...royale` | `com.aura.oobe.motorola` |
| `com.facebook.katana` | preinstalled (installer `null`) |
| `com.adobe.scan.android` | Play Store (setup queue) |
| `com.amazon.mp3` | Play Store (setup queue) |

## What was kept on purpose

| package | why |
|---|---|
| `com.motorola.launcher3` | home screen |
| `com.motorola.android.providers.settings` | Settings data provider |
| `com.motorola.timezonedata` | timezone data |
| `com.motorola.paks` | feature packs used by camera/gestures |
| `com.motorola.livewallpaper3` | live wallpapers |
| `com.motorola.timeweatherwidget` | clock/weather widget (may be placed on the home screen) |
| `com.ontim.launcher3.overlay` | RRO overlay for the launcher |
| `com.ontim.cit` | vendor factory test tool (kept; same class as `motocit`) |
| `flar2.devcheck` | CPU/system info (kept on request) |
| `com.fpsensor.fpSensorExtensionSvc2`, `egistec.ets.inlinetool` | fingerprint sensor |
| `com.sprd.*`, `com.spreadtrum.*`, `com.unisoc.phone`, `com.lsar.sar.lsarservice`, `com.qualcomm.qtil.aptxui` | modem/IMS/VoWiFi/SAR/Bluetooth codec |

Everything Google (`com.google.*`, `com.android.*`) was left untouched.

## Result

* 258 -> 239 system packages, 18 -> 10 third-party packages (9 Google + `devcheck`).
* No residual Motorola/Facebook/OOBE package outside the kept list.
* `com.motorola.launcher3` and `com.android.systemui` still running, crash
  buffer empty after the removals.

## Revert

```sh
adb shell pm install-existing <package>       # one package
adb shell pm install-existing                 # every removed user-0 package
```

A factory reset also restores all system packages. The fully removed
third-party apps have to be reinstalled from the Play Store.

## Caveat

With `com.motorola.ccc.ota` removed the device no longer checks for Motorola
system updates. If an OTA is wanted later, restore it first:

```sh
adb shell pm install-existing com.motorola.ccc.ota
```

## Note: this applies to the stock system

The list above was applied to the **stock Motorola system** (Android 11).
While an Android 15 GSI is running as a userspace DSU, its own package set
is in effect instead - the GSI has no Motorola packages at all (it is a
generic AOSP image), so there is nothing to debloat there. The removals
live in `/data` and therefore still apply to the stock system when you
reboot back into it.

The GSI does have its own bloat profile (AOSP apps plus whatever the image
adds) and no Play Store, so it is a separate cleanup job if it becomes the
daily driver.
