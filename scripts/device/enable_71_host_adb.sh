#!/system/bin/sh
# Host ADB on the 7.1 test kernel (Android userspace, slot b).
#
# Run from the COM6 root shell of boot_71_live17.img, after ~8 s:
#   sh /cache/h71/tcp_rndis.sh &     (or: setsid sh /cache/h71/tcp_rndis.sh &)
#
# It is intentionally self-contained: it dies with the shell's tty when
# the gadget is unbound, so every step after that is already in this file.
#
# Host side (from docs/30-7.1-host-adb-over-rndis.md):
#   adb connect "[fe80::ff:fe00:1%<RNDIS ifindex>]:5555"
#
# Replace HOST_ADB_PUBKEY with the public key of the host that will run adb.

set -e

HOST_ADB_PUBKEY='QAAAAEuEnSid2nobaJx/98JzRQsYqj5Cego+i9o2KyysDERzQFJH28hDbz1b7521FkA24zZdiJMAFILTv0zrTsOo+DZwAnZTrbgBoCqwD9jxFmiiF1JoYc71cEndb173Ply+J8W74DliTiRBy1rtlv1rdB3aZexmvaIT4HXrBzBOtawXVKdF+CLwftZv/R/oUih6tkpnA92DqWamB9WuZ5L2+L/QpvwShY8YywjKWqV6Kyc/3VL3YoSM7+4cDFA3+S7idz3YxBF1L7FwjKP9gQ0YEpXoBPKk4Fa2OrnmDon+8Tz4GbT/b8Hv47jXLV3AedqsGs0swqnoaWwq3cp9brqFI/ZQpBXIcvlus6VTuseKlzDJ/73W4a2wXXZgRDF3atLNb0S01vMrLoeSMsQPGXWbVvb573AhQYRcTBW4teJl3mudgkV2JvX4Uu+SMOf37PjkIUFmG98X2wZXoZ5dr6vk4uWvA1rVLINlpksBirfWp3nwoVJEp1DN1u//JlXhr8zqK0EzQhoIj/ZlIJBRYHgtG5s/vjU+WHsDLWUXe0kLRFNmGgurBLDvdbU/aBNIumoe+AzOhobVmSKg+7t7vWXfb0LMbIRpKvhu+zlDE3ztm0s0bTHKa27fnuWwQYFBgi2CvR1Jgh++14ELdh9e5wZ4jqSQOK26XyDa8nGDk1sqLmpYRH+VEgEAAQA= Creitin@DESKTOP-2US921D'

exec > /cache/h71/host_adb.log 2>&1
echo "=== START $(date) ==="

# 1. Authorize the host.  The real /data never mounts on 7.1
#    (dm-default-key needs Trusty), and ro.adb.secure=1 with no UI to
#    tap Allow, so adbd only reads keys if we give it a writable /data.
mount -t tmpfs tmpfs /data 2>/dev/null || true
mkdir -p /data/misc/adb
echo "$HOST_ADB_PUBKEY" > /data/misc/adb/adb_keys
chmod 0644 /data/misc/adb/adb_keys
wc -c /data/misc/adb/adb_keys

# 2. TCP adbd.  Regular properties DO work from this shell; only
#    ctl.* control properties are rejected.
setprop service.adb.tcp.port 5555
echo TCPPORT=$(getprop service.adb.tcp.port)

# 3. adbd lives in an APEX that apexd never activates on 7.1.  Extract
#    its payload once to /cache (survives reboots), then loop-mount it.
mkdir -p /cache/h71 /apex/com.android.adbd
if [ ! -f /cache/h71/apex_payload.img ]; then
    unzip -o -d /cache/h71 \
        /system/apex/com.google.android.adbd.apex apex_payload.img
fi
losetup -d /dev/block/loop26 2>/dev/null || true
losetup -r /dev/block/loop26 /cache/h71/apex_payload.img
mount -t ext4 -o ro /dev/block/loop26 /apex/com.android.adbd
pkill adbd 2>/dev/null || true
sleep 1
setsid env LD_LIBRARY_PATH=/apex/com.android.adbd/lib64 \
    /apex/com.android.adbd/bin/adbd > /cache/h71/adbd_tcp.log 2>&1 &
sleep 3
ps -A | grep adbd
grep -ai 'listening on tcp' /cache/h71/adbd_tcp.log | head -2

# 4. Rebuild the gadget while unbound.  VID/PID 04B3:4010 is in Windows'
#    inbox netimm.inf -> the "IBM USB Remote NDIS Network Device" driver
#    binds automatically.  Keep ONLY rndis.0: with acm0 also linked,
#    Windows binds that driver to the composite parent and fails (code 10).
cd /config/usb_gadget/h71 || exit 1
echo old=$(cat UDC)
echo 0x04b3 > idVendor
echo 0x4010 > idProduct
echo '' > UDC                 # unbind (COM6 dies here)
sleep 1
mkdir functions/rndis.0 2>/dev/null || true
echo 02:00:00:00:00:01 > functions/rndis.0/dev_addr
echo 02:00:00:00:00:02 > functions/rndis.0/host_addr
rm -f configs/c.1/rndis0 configs/c.1/acm0
ln -s /config/usb_gadget/h71/functions/rndis.0 configs/c.1/rndis0
echo LINKS=$(ls configs/c.1/)
echo musb-hdrc.10.auto > UDC
echo bound=$(cat UDC)
sleep 4

# 5. Give usb0 an address.  Windows takes APIPA (no admin needed) and
#    the two ends reach each other over IPv6 link-local.
echo ===NET===
ls /sys/class/net/
ip link set usb0 up 2>/dev/null || true
ip addr add 192.168.42.1/24 dev usb0 2>/dev/null || true
ip addr show usb0
echo "=== END $(date) ==="
