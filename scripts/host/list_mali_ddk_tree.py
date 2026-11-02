#!/usr/bin/env python3
"""Enumerate the Mali r28p0 DDK files in the Unplugged OS Gitea repo.

Walks the git tree API path-by-path to the mali-r28p0 subtree, then lists
every blob under it (recursively if the API supports it, else by walking).
"""
import json
import pathlib
import time
import urllib.request

API = ("https://os.unplugged.com/api/v1/repos/werunplugged/unplugged-kernel"
       "/git/trees")
COMMIT = "d30235b04cd3197d935dd42181b0730359fa010c"
PATH = ["drivers", "misc", "mediatek", "gpu", "gpu_mali", "mali_valhall",
        "mali-r28p0"]


def get_tree(sha):
    url = "%s/%s" % (API, sha)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            print("retry", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    raise SystemExit("tree fetch failed")


sha = COMMIT
for name in PATH:
    t = get_tree(sha)
    entry = next((e for e in t["tree"] if e["path"] == name), None)
    if entry is None:
        raise SystemExit("missing %s under %s" % (name, sha[:12]))
    sha = entry["sha"]
    print(name, "->", sha[:12])

# sha is now the mali-r28p0 tree; try recursive
t = get_tree(sha)
if t.get("truncated"):
    print("WARNING: recursive listing truncated")
blobs = [e for e in t["tree"] if e["type"] == "blob"]
print("entries under mali-r28p0:", len(t["tree"]),
      "blobs:", len(blobs), "truncated:", t.get("truncated"))
for e in t["tree"][:10]:
    print(" ", e["type"], e["path"])
out = pathlib.Path("artifacts/mali-ddk-r28p0.filelist.json")
out.write_text(json.dumps(t, indent=1))
print("saved to", out)
