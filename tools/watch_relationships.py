#!/usr/bin/env python3
"""READ-ONLY: alarm if any non-template VM has lost its HostSystem parent.

    python3 tools/watch_relationships.py      # silent unless something is lost

This is the mitigation that makes attach_to_vcenter=true acceptable. The
damage on 2026-10-21 went unnoticed for weeks because nothing watched. Run it
behind the same cron as the issue and CI watchers.

TWO THINGS IT GETS RIGHT THAT THE EARLIER MANUAL CHECK DID NOT:

  * It checks from the CHILD side. Counting foreign children on a host is not
    sufficient -- on 2026-10-16 this pack was declared clean because hosts
    showed 8, 10, 14 and 59 VMWARE children, and 26 of 28 VMs had already
    lost their host parent. Presence is not completeness.
  * It excludes TEMPLATES. A VM with template=true is not running and
    legitimately has no HostSystem parent, proven against the lab with an
    ordinary-VM control. Counting all VMs reports a permanent deficit and
    sends someone hunting damage that is not there.
"""
import collections
import json
import os
import ssl
import sys
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
STATE = os.path.expanduser("~/.local/state/pack-issues/rel-seen.json")


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
    host = (e.get("OPS_HOST") or e.get("OPS_URL", "")
            ).removeprefix("https://").split("/")[0]
    body = json.dumps({"username": e.get("OPS_USER") or e.get("OPS_USERNAME"),
                       "password": e.get("OPS_PASS") or e.get("OPS_PASSWORD")})
    rq = urllib.request.Request(
        f"https://{host}/suite-api/api/auth/token/acquire", data=body.encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(rq, context=CTX, timeout=60) as r:
            tok = json.load(r)["token"]
    except Exception as exc:
        print(f"!! relationship check: cannot reach Operations "
              f"({type(exc).__name__})", flush=True)
        return 0

    def get(path):
        q = urllib.request.Request(
            f"https://{host}/suite-api/api/{path}",
            headers={"Authorization": f"vRealizeOpsToken {tok}",
                     "Accept": "application/json"})
        with urllib.request.urlopen(q, context=CTX, timeout=120) as r:
            return json.load(r)

    res = get("resources?pageSize=20000")["resourceList"]
    vms, hosts = {}, {}
    for r in res:
        k = r["resourceKey"]
        if k.get("adapterKindKey") != "VMWARE":
            continue
        if k.get("resourceKindKey") == "VirtualMachine":
            vms[r["identifier"]] = k["name"]
        elif k.get("resourceKindKey") == "HostSystem":
            hosts[r["identifier"]] = k["name"]

    claimed = set()
    for hid in hosts:
        for kid in get(f"resources/{hid}/relationships/children"
                       ).get("resourceList", []):
            kk = kid["resourceKey"]
            if (kk.get("adapterKindKey") == "VMWARE"
                    and kk.get("resourceKindKey") == "VirtualMachine"):
                claimed.add(kid["identifier"])

    orphans = []
    for vid, name in vms.items():
        if vid in claimed:
            continue
        props = get(f"resources/{vid}/properties").get("property", [])
        is_tmpl = any(str(p.get("value")).lower() == "true"
                      for p in props if "emplate" in (p.get("name") or ""))
        if not is_tmpl:
            orphans.append(name)

    if orphans:
        print(f"!! RELATIONSHIP DAMAGE: {len(orphans)} non-template VMs have "
              f"no HostSystem parent: {sorted(orphans)[:8]}", flush=True)
        print("   Set attach_to_vcenter=false on the VsanHostMetrics adapter "
              "instance to stop the writing; no reinstall needed.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
