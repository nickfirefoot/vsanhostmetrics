#!/usr/bin/env python3
"""READ-ONLY: report when the new adapter image takes over after an install.

Prints one line per state CHANGE, nothing while unchanged, so it is safe
behind a monitor. The signals, which fail independently:

  * VsanCpu appears      -> the rc.2+ image is collecting (1.4.6 never emits it)
  * VsanHostCpu ages out -> the 1.4.6 image has stopped (nothing else collects it)
  * sample age falls     -> collection has resumed at all

A pak install restarts the adapter and the Cloud Proxy pulls the image by
digest on first collection, so a gap with no samples is normal for a few
minutes. Only a gap that persists means the pull is stuck.
"""
import collections, datetime, json, os, ssl, sys, urllib.request

CTX = ssl.create_default_context(); CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
STATE = os.path.expanduser("~/.local/state/pack-issues/install-seen.json")


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
        print(f"!! install watch: Operations unreachable ({type(exc).__name__})", flush=True)
        return 0

    def get(p):
        q = urllib.request.Request(f"https://{host}/suite-api/api/{p}",
            headers={"Authorization": f"vRealizeOpsToken {tok}", "Accept": "application/json"})
        with urllib.request.urlopen(q, context=CTX, timeout=120) as r:
            return json.load(r)

    res = get("resources?pageSize=20000")["resourceList"]
    c = collections.Counter(r["resourceKey"]["resourceKindKey"] for r in res
                            if r["resourceKey"].get("adapterKindKey") == "VsanHostMetrics")
    cpu, hostcpu = c.get("VsanCpu", 0), c.get("VsanHostCpu", 0)

    age = None
    probe = [r for r in res if r["resourceKey"].get("resourceKindKey") == "VsanMemory"]
    if probe:
        d = get(f"resources/{probe[0]['identifier']}/stats/latest")
        stamps = [t[-1] for t in (v.get("time-stamps") for v in d.get("values", [])) if t]
        if stamps:
            age = round((datetime.datetime.now(datetime.timezone.utc)
                         - datetime.datetime.fromtimestamp(max(stamps)/1000,
                           datetime.timezone.utc)).total_seconds()/60, 1)

    now = {"cpu": cpu, "hostcpu": hostcpu, "collecting": age is not None and age < 20}
    try:
        was = json.load(open(STATE))
    except Exception:
        was = None

    if was != now:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(now, open(STATE, "w"))
        if was is None:
            print(f"install watch armed: VsanCpu={cpu} VsanHostCpu={hostcpu} "
                  f"sample_age={age}", flush=True)
        else:
            if cpu and not was.get("cpu"):
                print(f"NEW IMAGE LIVE: VsanCpu now {cpu} objects "
                      f"(1.4.6 never emits these). CPU panel should populate.", flush=True)
            if was.get("hostcpu") and not hostcpu:
                print(f"VsanHostCpu aged out ({was['hostcpu']} -> 0): the 1.4.6 "
                      f"image has stopped collecting.", flush=True)
            if now["collecting"] and not was.get("collecting"):
                print(f"collection resumed (newest sample {age} min old)", flush=True)
            if was.get("collecting") and not now["collecting"]:
                print(f"collection STOPPED (newest sample {age} min old)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
