#!/usr/bin/env python3
"""Probe the Unisoc/Moto unlock command variants over raw USB fastboot.

Motivation
----------
`patrislav1/unisoc-unlock` signs the device's *identifier token* with the leaked
Unisoc `rsa4096_vbmeta.pem` and then issues `flashing unlock_bootloader`. That
command is stubbed out ("Not implemet.") on this Moto bootloader, but the plain
`oem unlock` handler is alive and answers "Unlock bootloader fail.".

This script tries the plausible combinations (with/without the downloaded
signature, different command spellings) so we can tell *why* unlock fails:
  * "unknown cmd."      -> command not in the dispatch table
  * "Not implemet."     -> stubbed handler
  * "Unlock bootloader fail." -> real handler, rejected by the verification

Requires: pip install pyusb pycryptodome, device in fastboot mode, and the
`sig`-signing key from the unisoc-unlock package (same key that is already in
artifacts/bootloader/rsa4096_vbmeta.pem).

Usage:
    python scripts/host/unisoc_unlock_variants.py [--key PATH]
"""

import argparse
import base64
import io
import sys
import time

import usb.core
import usb.util
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5


VID = 0x18D1
PID = 0x4EE0


class Fastboot:
    """Minimal raw fastboot client (enough for oem/download/flashing probes)."""

    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise SystemExit("no fastboot device (%04x:%04x) found" % (VID, PID))
        self.dev.set_configuration()
        cfg = self.dev.get_active_configuration()
        self.ep_in = usb.util.find_descriptor(
            cfg[(0, 0)],
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN,
        )
        self.ep_out = usb.util.find_descriptor(
            cfg[(0, 0)],
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        if self.ep_in is None or self.ep_out is None:
            raise SystemExit("could not locate fastboot bulk endpoints")

    def close(self):
        usb.util.dispose_resources(self.dev)

    def _read(self, timeout=5000):
        try:
            return bytes(self.ep_in.read(4096, timeout=timeout))
        except usb.core.USBTimeoutError:
            return b""

    def command(self, cmd, timeout=8000):
        """Send one fastboot command and drain INFO lines until OKAY/FAIL."""
        self.ep_out.write(cmd, timeout=timeout)
        infos = []
        while True:
            pkt = self._read(timeout)
            if not pkt:
                return "TIMEOUT", infos
            status = pkt[:4]
            if status == b"INFO":
                infos.append(pkt[4:].rstrip(b"\x00").decode("utf-8", "replace"))
                continue
            if status == b"TEXT":
                infos.append(pkt[4:].rstrip(b"\x00").decode("utf-8", "replace"))
                continue
            if status in (b"OKAY", b"FAIL"):
                return status.decode(), infos
            # Unknown packet: keep whatever we got for debugging.
            infos.append(repr(pkt[:32]))
            return "UNKNOWN", infos

    def download(self, payload, timeout=15000):
        status, infos = self.command(b"download:%08x" % len(payload), timeout)
        if status != "DATA":
            # Some bootloaders answer OKAY directly.
            if status != "OKAY":
                return status, infos
        self.ep_out.write(payload, timeout=timeout)
        while True:
            pkt = self._read(timeout)
            if not pkt:
                return "TIMEOUT", infos
            if pkt[:4] in (b"OKAY", b"FAIL", b"INFO"):
                if pkt[:4] == b"INFO":
                    infos.append(pkt[4:].rstrip(b"\x00").decode("utf-8", "replace"))
                    continue
                return pkt[:4].decode(), infos
            return "UNKNOWN", infos + [repr(pkt[:32])]


def get_token(fb):
    fb.command(b"oem get_identifier_token")
    status, infos = fb.command(b"oem get_identifier_token")
    for line in infos:
        s = line.strip()
        if s and all(c in "0123456789abcdefABCDEF" for c in s) and len(s) >= 8:
            return s.lower()
    raise SystemExit("token not found in %r" % (infos,))


def sign_token(token_hex, key_path):
    padded = token_hex.ljust(2 * 64, "0")
    raw = base64.b16decode(padded, casefold=True)
    key = RSA.importKey(open(key_path).read())
    sig = PKCS1_v1_5.new(key).sign(SHA256.new(raw))
    return raw, sig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None, help="RSA private key PEM")
    args = ap.parse_args()

    if not args.key:
        raise SystemExit("--key <rsa4096_vbmeta.pem> is required")

    variants = [
        ("oem unlock (bare, no sig)", b"oem unlock", False),
        ("oem unlock <token> (no sig)", None, False),
        ("download(sig) + oem unlock", b"oem unlock", True),
        ("download(sig) + oem unlock <token>", None, True),
        ("download(sig) + flashing unlock_bootloader <token>", None, True),
    ]

    for name, cmd, with_sig in variants:
        print("\n=== %s ===" % name)
        fb = Fastboot()
        try:
            token = get_token(fb)
            print("  token:", token)
            raw, sig = sign_token(token, args.key)
            if cmd is None:
                cmd = (b"oem unlock " if "oem unlock" in name else
                       b"flashing unlock_bootloader " + token.encode())
            if with_sig:
                st, infos = fb.download(sig)
                print("  download ->", st, infos)
            if cmd == b"oem unlock ":
                cmd = b"oem unlock " + token.encode()
            st, infos = fb.command(cmd, timeout=30000)
            print("  %r -> %s %r" % (cmd, st, infos))
        except SystemExit as e:
            print("  skipped:", e)
        except Exception as e:  # noqa: BLE001 - diagnostic script
            print("  error:", type(e).__name__, e)
        finally:
            fb.close()
        time.sleep(0.4)


if __name__ == "__main__":
    main()
