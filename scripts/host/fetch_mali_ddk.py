#!/usr/bin/env python3
"""Download the Mali r28p0 DDK subtree from the Unplugged OS Gitea instance.

Walks drivers/misc/mediatek/gpu/gpu_mali/mali_valhall/mali-r28p0 via the
Gitea contents API at the pinned commit and downloads every file into
artifacts/mali-ddk-r28p0/.
"""
import json
import pathlib
import time
import urllib.request

BASE = ("https://os.unplugged.com/api/v1/repos/werunplugged/unplugged-kernel"
        "/contents")
REF = "d30235b04cd3197d935dd42181b0730359fa010c"
ROOT = "drivers/misc/mediatek/gpu/gpu_mali/mali_valhall/mali-r28p0"
OUT = pathlib.Path("artifacts/mali-ddk-r28p0")

count = 0
total = 0


def walk(rel):
    global count, total
    url = "%s/%s?ref=%s" % (BASE, rel, REF)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                entries = json.load(r)
            break
        except Exception as e:
            print("retry %d for %s: %s" % (attempt + 1, rel, e))
            time.sleep(2 * (attempt + 1))
    else:
        raise SystemExit("failed to list " + rel)
    for e in entries:
        if e["type"] == "dir":
            walk(e["path"])
        elif e["type"] == "file":
            dest = OUT / pathlib.Path(e["path"]).relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dl = e.get("download_url") or e.get("url")
            if not dl:
                print("no download url for", e["path"])
                continue
            if not dl.startswith("http"):
                dl = "https://os.unplugged.com" + dl
            try:
                req = urllib.request.Request(dl)
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
            except Exception as ex:
                print("DOWNLOAD FAIL", e["path"], ex)
                continue
            dest.write_bytes(data)
            count += 1
            total += len(data)
            if count % 50 == 0:
                print("%d files, %d bytes" % (count, total))


walk(ROOT)
print("done: %d files, %d bytes" % (count, total))
