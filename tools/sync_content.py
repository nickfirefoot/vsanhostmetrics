#!/usr/bin/env python3
"""Copy generated views and dashboards into the mp-build project tree.

    python3 tools/build_view.py && python3 tools/build_dash.py
    python3 tools/sync_content.py ~/vsan-host-metrics

The generators write to ~/ops-content/out. The project tree does NOT update
itself, and nothing warns when it is stale -- the 1.4.5 build was staged with
project content four days older than the fixes it was supposed to carry, and
only a mtime check caught it. Views ship as content/reports/<name>/<name>.xml,
dashboards as content/dashboards/<name>/<name>.json.
"""
import glob
import json
import os
import shutil
import sys
import zipfile

OUT = os.path.expanduser("~/ops-content/out")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    proj = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1
                              else "~/vsan-host-metrics")
    if not os.path.isdir(proj):
        sys.exit(f"no such project: {proj}")

    # content/reports is entirely generated, so a directory with no generated
    # source is a leftover. Renaming a view leaves one behind carrying the SAME
    # pinned GUID as its replacement, and a pak shipping two views under one
    # identity is a defect nothing downstream would catch.
    generated = {os.path.basename(x)[:-4] for x in glob.glob(f"{OUT}/*.xml")}
    for d in sorted(glob.glob(f"{proj}/content/reports/*/")):
        name = os.path.basename(d.rstrip("/"))
        if name not in generated:
            shutil.rmtree(d)
            print(f"  removed orphaned view directory {name}")

    views = 0
    for xml in sorted(glob.glob(f"{OUT}/*.xml")):
        name = os.path.basename(xml)[:-4]
        if name.endswith(".content") or name == "ALL_VIEWS":
            continue                           # a bundle, not a view
        d = f"{proj}/content/reports/{name}"
        os.makedirs(d, exist_ok=True)
        shutil.copy2(xml, f"{d}/{name}.xml")
        views += 1

    dash = 0
    for src in sorted(glob.glob(f"{REPO}/content/dashboards/*/")):
        name = os.path.basename(src.rstrip("/"))
        zp = f"{OUT}/{name}.zip"
        if not os.path.exists(zp):
            print(f"  WARNING: no generated {name}.zip; leaving the "
                  f"committed copy in place")
            payload = open(f"{src}{name}.json", encoding="utf-8").read()
        else:
            z = zipfile.ZipFile(zp)
            inner = [x for x in z.namelist() if x.endswith(".json")][0]
            payload = json.dumps(json.loads(z.read(inner)), indent=1)
            with open(f"{src}{name}.json", "w", encoding="utf-8") as f:
                f.write(payload)           # keep the repo copy authoritative
        t = f"{proj}/content/dashboards/{name}"
        os.makedirs(t, exist_ok=True)
        with open(f"{t}/{name}.json", "w", encoding="utf-8") as f:
            f.write(payload)
        dash += 1

    if not views or not dash:
        sys.exit(f"refusing to report success: {views} views, {dash} "
                 f"dashboards -- did the generators run?")
    print(f"synced {views} views and {dash} dashboards into {proj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
