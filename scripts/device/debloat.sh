#!/system/bin/sh
# Uninstall Motorola/OOBE bloat on the Moto E32 (hawaii).
#
# System packages are removed for user 0 only (`pm uninstall -k --user 0`),
# which keeps the APK on the read-only system partition: the removal is
# reversible with `pm install-existing <package>` and survives only until a
# factory reset, which restores everything.
#
# Third-party packages are removed completely (they are all reinstallable
# from the Play Store).
#
# Kept on purpose (functional, not bloat):
#   com.motorola.launcher3                     home screen
#   com.motorola.android.providers.settings    Settings data provider
#   com.motorola.timezonedata                  timezone data
#   com.motorola.paks                          feature packs (camera/gestures)
#   com.motorola.livewallpaper3                wallpapers
#   com.motorola.timeweatherwidget             clock/weather widget
#   com.ontim.launcher3.overlay                launcher RRO overlay
#   com.ontim.cit                              vendor factory test tool
#   com.fpsensor.*, egistec.*                  fingerprint sensor services
#   com.sprd.*, com.spreadtrum.*, com.unisoc.phone, com.lsar.sar.lsarservice
#   com.qualcomm.qtil.aptxui                   modem/IMS/VoWiFi/SAR/BT codec
#   flar2.devcheck                             CPU/system info (kept on request)

SYS="
com.aura.oobe.motorola
com.facebook.appmanager
com.facebook.services
com.facebook.system
com.motorola.brapps
com.motorola.help
com.motorola.motocare
com.motorola.motosignature.app
com.motorola.genie
com.motorola.demo
android.autoinstalls.config.motorola.layout
com.motorola.ccc.notification
com.motorola.ccc.mainplm
com.motorola.ccc.devicemanagement
com.motorola.ccc.ota
com.motorola.bach.modemstats
com.lenovo.lsf.user
com.motorola.motocit
com.ontim.fmradio
"

USR="
com.amelosinteractive.snake
com.block.juggle
com.shopee.br
com.vitastudio.mahjong
in.playsimple.triple.tile.matchgame.pair.three.puzzle.object.royale
com.facebook.katana
com.adobe.scan.android
com.amazon.mp3
"

for p in $SYS; do
    printf 'SYS %-46s ' "$p"
    pm uninstall -k --user 0 "$p" 2>&1 | tr -d '\r\n'
    echo
done

for p in $USR; do
    printf 'USR %-70s ' "$p"
    pm uninstall "$p" 2>&1 | tr -d '\r\n'
    echo
done
