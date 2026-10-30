#!/usr/bin/env python3
"""Probe the Unisoc BROM (1782:4d00) for a live command channel.

The reference tool (spd_dump) attaches but gets no reply to BSL_CMD_CONNECT,
i.e. the device's USB stack enumerates while its command handler is dead.
This tries several ways to kick that handler back into life without writing
anything to storage:

  1. claim the interface and read whatever the device already wants to send
  2. clear_halt on both bulk endpoints
  3. USB port reset (libusb_reset_device) then re-open
  4. send the 0x7e fill byte, then BSL_CMD_CONNECT, with a long timeout

Exit code 0 = something answered.
"""

import sys
import time

import usb.core
import usb.util

VID, PID = 0x1782, 0x4D00
EP_IN, EP_OUT = 0x85, 0x06

CONNECT_FRAME = bytes([0x7E, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0x7E])


def crc16_ccitt(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def find():
    return usb.core.find(idVendor=VID, idProduct=PID)


def read_any(ep, label, timeout_ms=3000):
    try:
        data = ep.read(512, timeout=timeout_ms)
        print(f"  {label}: got {len(data)} bytes: {bytes(data).hex()}")
        return bytes(data)
    except usb.core.USBTimeoutError:
        print(f"  {label}: timeout (no data)")
    except usb.core.USBError as e:
        print(f"  {label}: USBError {e}")
    return None


def main():
    dev = find()
    if dev is None:
        print("device 1782:4d00 not found - is the cable plugged in?")
        return 2
    print(f"found on bus {dev.bus} addr {dev.address}")

    # ---- 1. passive read, in case data is already queued -------------------
    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        print(f"set_configuration: {e}")
    try:
        usb.util.claim_interface(dev, 0)
    except usb.core.USBError as e:
        print(f"claim_interface: {e}")

    ep_in = usb.util.find_descriptor(dev[0][(0, 0)], bEndpointAddress=EP_IN)
    ep_out = usb.util.find_descriptor(dev[0][(0, 0)], bEndpointAddress=EP_OUT)
    print(f"endpoints: in={ep_in} out={ep_out}")

    read_any(ep_in, "passive read")

    # ---- 2. clear halts ----------------------------------------------------
    for ep in (ep_in, ep_out):
        try:
            ep.clear_halt()
            print(f"  clear_halt {ep.bEndpointAddress:#x}: ok")
        except usb.core.USBError as e:
            print(f"  clear_halt {ep.bEndpointAddress:#x}: {e}")

    # ---- 3. speak the protocol, long timeout -------------------------------
    print("sending 0x7e fill + CONNECT ...")
    for attempt in range(3):
        try:
            ep_out.write(bytes([0x7E]), timeout=1000)
        except usb.core.USBError as e:
            print(f"  write fill: {e}")
        if read_any(ep_in, f"read after fill #{attempt + 1}"):
            return 0
        try:
            ep_out.write(CONNECT_FRAME, timeout=1000)
        except usb.core.USBError as e:
            print(f"  write connect: {e}")
        if read_any(ep_in, f"read after CONNECT #{attempt + 1}", 4000):
            return 0

    # ---- 4. USB port reset, then re-open and retry -------------------------
    print("attempting USB port reset ...")
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass
    try:
        dev.reset()
        print("  dev.reset() ok")
    except usb.core.USBError as e:
        print(f"  dev.reset(): {e}")
    time.sleep(3)

    dev = find()
    if dev is None:
        print("device gone after reset (this can be normal) - waiting 8 s for re-enumeration")
        for _ in range(16):
            time.sleep(0.5)
            dev = find()
            if dev is not None:
                break
    if dev is None:
        print("device did not come back yet")
        return 3
    print(f"re-enumerated on bus {dev.bus} addr {dev.address} bcdDevice {dev.bcdDevice:#x}")

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    ep_in = usb.util.find_descriptor(dev[0][(0, 0)], bEndpointAddress=EP_IN)
    ep_out = usb.util.find_descriptor(dev[0][(0, 0)], bEndpointAddress=EP_OUT)

    try:
        ep_out.write(bytes([0x7E]), timeout=1000)
        ep_out.write(CONNECT_FRAME, timeout=1000)
    except usb.core.USBError as e:
        print(f"  write after reset: {e}")
    if read_any(ep_in, "read after reset", 5000):
        return 0

    print("no response to CONNECT after reset either")
    return 1


if __name__ == "__main__":
    sys.exit(main())