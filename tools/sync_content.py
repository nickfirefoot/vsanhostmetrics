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

    # Named from build_dash.DASHBOARDS, the source of truth -- NOT by globbing
    # the output directory. ~/ops-content/out accumulates one-off artefacts
    # like "Rapid_vSAN_Network-1.4.4-reimport.zip", and a prefix match on
    # "Rapid_" shipped that as a ninth, duplicate dashboard.
    sys.path.insert(0, os.path.join(REPO, "tools"))
    sys.path.insert(0, os.path.join(REPO, "app"))
    import build_dash
    generated_dash = [n.replace(" ", "_") for n, _h, _p in build_dash.DASHBOARDS]

    # Every dashboard must have been generated, checked BEFORE anything is
    # written or removed. A missing zip used to be a WARNING: the committed
    # copy was reused, counted, and the run ended "synced ... dashboards"
    # with exit 0 -- so when build_dash.py crashed, the build went ahead with
    # the old dashboards and nothing said so.
    missing = [n for n in generated_dash if not os.path.exists(f"{OUT}/{n}.zip")]
    if missing:
        sys.exit(f"refusing to sync: {len(missing)} of {len(generated_dash)} "
                 f"dashboards were not generated ({', '.join(missing)}). "
                 f"Run python3 tools/build_dash.py and check it finished.")

    # content/reports is entirely generated, so a directory with no generated
    # source is a leftover. Renaming a view leaves one behind carrying the SAME
    # pinned GUID as its replacement, and a pak shipping two views under one
    # identity is a defect nothing downstream would catch.
    generated = {os.path.basename(x)[:-4] for x in glob.glob(f"{OUT}/*.xml")}
    for root in (REPO, proj):
        for d in sorted(glob.glob(f"{root}/content/reports/*/")):
            name = os.path.basename(d.rstrip("/"))
            if name not in generated:
                shutil.rmtree(d)
                print(f"  removed orphaned view directory {name}")

    # Views land in the REPO first. Since the CI workflow builds the pak from
    # the checkout, content/reports/ in this repository is what ships -- the
    # project tree is only still written for hand builds. Updating only the
    # project tree, as this did, meant a regenerated view reached the local
    # build and never the released pak.
    views = 0
    for xml in sorted(glob.glob(f"{OUT}/*.xml")):
        name = os.path.basename(xml)[:-4]
        if name.endswith(".content") or name == "ALL_VIEWS":
            continue                           # a bundle, not a view
        for root in (REPO, proj):
            d = f"{root}/content/reports/{name}"
            os.makedirs(d, exist_ok=True)
            shutil.copy2(xml, f"{d}/{name}.xml")
        views += 1

    # Iterate the GENERATED dashboards, not the repo's existing directories.
    # Keyed on the repo the other way round, a dashboard added to build_dash.py
    # has no directory yet, so it is silently skipped and never ships -- which
    # is exactly what happened the first time Rapid vSAN Backpressure was built.
    dash = 0
    for name in generated_dash:
        src = f"{REPO}/content/dashboards/{name}/"
        os.makedirs(src, exist_ok=True)
        z = zipfile.ZipFile(f"{OUT}/{name}.zip")
        inner = [x for x in z.namelist() if x.endswith(".json")][0]
        payload = json.dumps(json.loads(z.read(inner)), indent=1)
        with open(f"{src}{name}.json", "w", encoding="utf-8") as f:
            f.write(payload)               # keep the repo copy authoritative
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
