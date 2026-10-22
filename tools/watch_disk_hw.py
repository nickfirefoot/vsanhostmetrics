#!/usr/bin/env python3
"""READ-ONLY: report when drive firmware/driver properties populate.

Silent until the state changes. Properties behave differently from metrics in
Operations -- they carry a current value and no time series -- and this is the
first real use of isProperty=true in this pack (the cluster-name column was
the only prior one), so it is worth watching rather than assuming.
"""
import collections, json, os, ssl, sys, urllib.request

CTX = ssl.create_default_context(); CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
STATE = os.path.expanduser("~/.local/state/pack-issues/diskhw-seen.json")
WANT = ("firmware", "driver", "model", "vendor")


def env():
    out = {}
    for line in open(os.path.expanduser("~/ops.env")):
        line = line.strip().removeprefix("export ").strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("="); out[k.strip()] = v.strip().strip("'\"")
    return out


def main():
    e = env()
    host = (e.get("OPS_HOST") or e.get("OPS_URL", "")).removeprefix("https://").split("/")[0]
    body = json.dumps({"username": e.get("OPS_USER") or e.get("OPS_USERNAME"),
                       "password": e.get("OPS_PASS") or e.get("OPS_PASSWORD")}).encode()
    rq = urllib.request.Request(f"https://{host}/suite-api/api/auth/token/acquire",
        data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(rq, context=CTX, timeout=60) as r:
            tok = json.load(r)["token"]
    except Exception as exc:
        print(f"!! disk-hw watch: Operations unreachable ({type(exc).__name__})", flush=True)
        return 0

    def get(p):
        q = urllib.request.Request(f"https://{host}/suite-api/api/{p}",
            headers={"Authorization": f"vRealizeOpsToken {tok}", "Accept": "application/json"})
        with urllib.request.urlopen(q, context=CTX, timeout=120) as r:
            return json.load(r)

    res = get("resources?pageSize=20000")["resourceList"]
    disks = [r["identifier"] for r in res
             if r["resourceKey"].get("adapterKindKey") == "VsanHostMetrics"
             and r["resourceKey"].get("resourceKindKey") == "VsanEsaDiskScsifw"]

    filled = collections.Counter()
    sample = {}
    for rid in disks:
        try:
            props = get(f"resources/{rid}/properties").get("property", [])
        except Exception:
            continue
        got = {p["name"]: p.get("value") for p in props
               if p["name"] in WANT and p.get("value")}
        for k in got:
            filled[k] += 1
        if got and not sample:
            sample = got

    now = {"disks": len(disks), **{k: filled.get(k, 0) for k in WANT}}
    try:
        was = json.load(open(STATE))
    except Exception:
        was = None

    if was != now:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(now, open(STATE, "w"))
        if was is None:
            print(f"disk-hw watch armed: {now}", flush=True)
        else:
            print(f"DISK HARDWARE: {now['disks']} disks | "
                  + " ".join(f"{k}={now[k]}" for k in WANT)
                  + (f" | e.g. {sample}" if sample else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
