#!/usr/bin/env python3
"""Walk the Unplugged Gitea git tree under mali_valhall and enumerate blobs."""
import json
import pathlib
import time
import urllib.request

API = ("https://os.unplugged.com/api/v1/repos/werunplugged/unplugged-kernel"
       "/git/trees")
CACHE = pathlib.Path("artifacts/mali-ddk-tree-cache")


def get_tree(sha):
    cache = CACHE / (sha + ".json")
    if cache.exists():
        return json.load(cache.open(encoding="utf-8"))
    url = "%s/%s" % (API, sha)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.load(r)
            CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(d), encoding="utf-8")
            return d
        except Exception as e:
            print("retry", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    raise SystemExit("tree fetch failed " + sha)


def walk(sha, prefix, out, depth=0):
    if depth > 12:
        return
    t = get_tree(sha)
    for e in t["tree"]:
        p = prefix + e["path"]
        if e["type"] == "blob":
            out.append((p, e.get("size", 0)))
        else:
            walk(e["sha"], p + "/", out, depth + 1)


# mali_valhall tree = 6fdcda6a6643 (from the previous walk)
t = get_tree("6fdcda6a6643")
print("=== mali_valhall children ===")
for e in t["tree"]:
    print(" ", e["type"], e["path"], e.get("size", ""))

out = []
walk("6fdcda6a6643", "mali_valhall/", out)
print("=== total blobs under mali_valhall: %d ===" % len(out))
total = sum(s for _, s in out)
print("total bytes: %d" % total)
for p, s in out[:40]:
    print("  %8d  %s" % (s, p))
pathlib.Path("artifacts/mali-ddk-filelist.txt").write_text(
    "\n".join("%d %s" % (s, p) for p, s in out), encoding="utf-8")
print("full list saved to artifacts/mali-ddk-filelist.txt")
