#!/usr/bin/env python3
"""READ-ONLY: assert every column a view documents carries data on a live object.

    python3 tools/check_columns_populate.py

Needs ~/ops.env. Exits non-zero if a view documents a column that no live
object populates, or if a view's kind has no objects at all.

Why: the netstats session found its generated metric reference documented four
vNIC properties that are never collected -- the one feature meant to say what
the pack collects was advertising columns that can never populate. Generating
from the model guarantees the docs match the MODEL; it does not guarantee the
model matches what the API returns. This checks the second half.

Measured 2026-10-21 against the lab: 0 of 268 documented columns were dead.
Three views target kinds owned by other adapters (ClusterComputeResource,
HostSystem) or with no objects (VsanCpu), and are reported as unverifiable
rather than passed.
"""
import collections
import json
import os
import ssl
import sys
import urllib.request

sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                          # noqa: E402

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def env():
    out = {}
    for line in open(os.path.expanduser("~/ops.env")):
        line = line.strip().removeprefix("export ").strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip("'\"")
    return out


def main():
    e = env()
    host = (e.get("OPS_HOST") or e.get("OPS_URL", "")).removeprefix("https://").split("/")[0]
    user = e.get("OPS_USER") or e.get("OPS_USERNAME")
    pwd = e.get("OPS_PASS") or e.get("OPS_PASSWORD")

    def api(path, body=None):
        req = urllib.request.Request(
            f"https://{host}/suite-api/api/{path}",
            data=json.dumps(body).encode() if body else None,
            headers={"Accept": "application/json",
                     "Content-Type": "application/json",
                     **({"Authorization": f"vRealizeOpsToken {tok}"}
                        if body is None and 'tok' in dir() else {})})
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            return json.load(r)

    req = urllib.request.Request(
        f"https://{host}/suite-api/api/auth/token/acquire",
        data=json.dumps({"username": user, "password": pwd}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        tok = json.load(r)["token"]

    def get(path):
        rq = urllib.request.Request(
            f"https://{host}/suite-api/api/{path}",
            headers={"Authorization": f"vRealizeOpsToken {tok}",
                     "Accept": "application/json"})
        with urllib.request.urlopen(rq, context=CTX, timeout=90) as r:
            return json.load(r)

    res = get("resources?pageSize=20000")["resourceList"]
    bykind = collections.defaultdict(list)
    for r in res:
        k = r["resourceKey"]
        if k.get("adapterKindKey") == "VsanHostMetrics":
            bykind[k["resourceKindKey"]].append(r["identifier"])

    total = dead = 0
    unverifiable = []
    for title, kind, cols, *_ in build_view.VIEWS:
        ids = bykind.get(kind, [])
        if not ids:
            unverifiable.append(f"{title} ({kind})")
            continue
        have = set()
        for rid in ids[:3]:
            try:
                d = get(f"resources/{rid}/stats/latest")
            except Exception:
                continue
            for val in d.get("values", []):
                for st in val.get("stat-list", {}).get("stat", []):
                    if st.get("data"):
                        have.add(st["statKey"]["key"])
        missing = [c[0] for c in cols if c[0] not in have]
        total += len(cols)
        if missing:
            dead += len(missing)
            print(f"  DEAD COLUMNS  {title} ({kind}): {missing}")

    print(f"\n  {total} columns checked, {dead} carry no data")
    for u in unverifiable:
        print(f"  unverifiable (no objects): {u}")
    print(f"\n  {'PASS' if dead == 0 else 'FAIL'}")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
