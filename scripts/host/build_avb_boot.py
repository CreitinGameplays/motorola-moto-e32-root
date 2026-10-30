"""Rebuild the custom boot image with a *self-signed* AVB hash footer.

Why: TrustOS runs its own libavb `avb_slot_verify` before handing over to the
kernel. The custom image has no vbmeta at all, so the secure world returns
a0=6 (AVB_SLOT_VERIFY_RESULT_ERROR_INVALID_METADATA) and U-Boot reboots.
U-Boot's caller only tolerates 0 (OK) and 5 (PUBLIC_KEY_REJECTED), and 5 is
exactly what an unlocked device returns for a vbmeta signed with a key the
device does not trust. So: sign the image with a throwaway key.

Reproduces the stock layout:
    [ ANDROID! payload ][ 0x2b000 SPD trailer ][ vbmeta AVB0 ][ zero pad ][ AVBf ]

Usage:
    python scripts/host/build_avb_boot.py

Inputs : artifacts/kernel-build/boot_custom.img
Outputs: artifacts/kernel-build/boot_custom_avb.img
         artifacts/kernel-build/avb-test-key.pem   (throwaway, never used elsewhere)
"""
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD = ROOT / "artifacts" / "kernel-build"
SRC = BUILD / "boot_custom.img"
OUT = BUILD / "boot_custom_avb.img"
KEY = BUILD / "avb-test-key.pem"
AVBTOOL = pathlib.Path(r"D:\AndroidSDKTools\avb\avbtool.py")
PARTITION_SIZE = 67108864          # 64 MiB, /sys/class/block/sda40 size
PARTITION_NAME = "boot"
ALGORITHM = "SHA256_RSA4096"       # same as the stock vbmeta
ROLLBACK_INDEX = 2                 # stock value; must be <= stored index


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not SRC.exists():
        sys.exit("missing %s" % SRC)

    if not KEY.exists():
        print("generating throwaway RSA-4096 key -> %s" % KEY)
        subprocess.run(
            ["openssl", "genrsa", "-traditional", "-out", str(KEY), "4096"],
            check=True,
        )

    print("input : %s  %d bytes  sha256 %s" % (SRC.name, SRC.stat().st_size, sha256(SRC)))
    if SRC.stat().st_size >= PARTITION_SIZE:
        sys.exit("image does not fit the partition")

    cmd = [
        sys.executable, str(AVBTOOL), "add_hash_footer",
        "--image", str(OUT),
        "--partition_name", PARTITION_NAME,
        "--partition_size", str(PARTITION_SIZE),
        "--key", str(KEY),
        "--algorithm", ALGORITHM,
        "--rollback_index", str(ROLLBACK_INDEX),
        "--salt", "f83b993601311bca149a573c1e737666ff011f6cf2aa2a5ae822f91b97af0991",
    ]
    # add_hash_footer rewrites the image in place; give it a copy of our input
    OUT.write_bytes(SRC.read_bytes())
    print("running avbtool add_hash_footer ...")
    subprocess.run(cmd, check=True)

    print("\noutput: %s  %d bytes  sha256 %s"
          % (OUT.name, OUT.stat().st_size, sha256(OUT)))

    # confirm the kernel payload survived unchanged
    a = SRC.read_bytes()
    b = OUT.read_bytes()[:len(a)]
    print("payload identical to input: %s (%d bytes compared)"
          % (a == b, len(a)))

    print("\n--- avbtool info_image ---")
    subprocess.run([sys.executable, str(AVBTOOL), "info_image", "--image", str(OUT)])


if __name__ == "__main__":
    main()