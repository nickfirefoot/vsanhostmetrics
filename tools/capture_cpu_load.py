#!/usr/bin/env python3
"""READ-ONLY: record vSAN CPU and load figures straight from the Performance
Service while a benchmark runs.

    python3 tools/capture_cpu_load.py capture OUT.csv [--minutes 90]
    python3 tools/capture_cpu_load.py report  OUT.csv

Why this exists: the vsan-cpu percentages are documented only as "Percentage of
used CPU time", with no denominator, and five of the seven returned 0.0 in
every sample on an idle cluster. Whether they move under load, and whether
they can exceed 10 or 100, is settled by driving the cluster and reading the
service directly, which also avoids the 5-minute collection cadence of the
adapter. One row per (entity, metric, 5-minute bucket), de-duplicated across
polls, so the file is a clean time series however often it polls.

Reads only. Needs ~/vcenter.env.
"""
import csv, datetime, os, ssl, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "vendor"))
from pyVmomi import VmomiSupport                                   # noqa: E402


class _N:
    def Add(self, *a, **k): pass


for _n in ("stableVersions", "publicVersions"):
    if not hasattr(VmomiSupport, _n):
        setattr(VmomiSupport, _n, _N())
import vsanmgmtObjects, vsanapiutils                                # noqa: E402,F401
from pyVim.connect import SmartConnect                              # noqa: E402
from pyVmomi import vim                                             # noqa: E402

# entity type -> the metrics worth recording from it
WANT = {
    "vsan-cpu": None,                       # all seven
    "host-cpu": None,                       # per-core utilisation, for scale
    "dom-world-cpu": None,                  # vSAN thread groups, if present
    "lsom-world-cpu": None,
    "cluster-domclient": ("iopsRead", "iopsWrite", "throughputRead", "throughputWrite",
                          "latencyAvgRead", "latencyAvgWrite"),
}


def env():
    out = {}
    for line in open(os.path.expanduser("~/vcenter.env")):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            out[k] = v.strip().strip("'\"")
    return out


def connect():
    e = env()
    ctx = ssl._create_unverified_context()
    si = SmartConnect(host=e["VC_HOST"], user=e["VC_USER"], pwd=e["VC_PASS"], sslContext=ctx)
    view = si.RetrieveContent().viewManager.CreateContainerView(
        si.RetrieveContent().rootFolder, [vim.ClusterComputeResource], True)
    cluster = list(view.view)[0]
    view.Destroy()
    perf = vsanapiutils.GetVsanVcMos(si._stub, context=ctx)["vsan-performance-manager"]
    return si, cluster, perf


def poll(perf, cluster, window_min=20):
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for ent, only in WANT.items():
        try:
            res = perf.VsanPerfQueryPerf(querySpecs=[vim.cluster.VsanPerfQuerySpec(
                entityRefId=f"{ent}:*",
                startTime=now - datetime.timedelta(minutes=window_min), endTime=now)],
                cluster=cluster)
        except Exception as exc:                                    # noqa: BLE001
            print(f"  {ent}: {type(exc).__name__}", file=sys.stderr)
            continue
        for e in res:
            stamps = (e.sampleInfo or "").split(",")
            for v in e.value:
                name = v.metricId.label
                if only and name not in only:
                    continue
                vals = (v.values or "").split(",")
                for t, x in zip(stamps, vals):
                    if x in ("", None):
                        continue
                    try:
                        rows.append((ent, e.entityRefId.split(":", 1)[1][:36], name, t.strip(), float(x)))
                    except ValueError:
                        pass
    return rows


def capture(path, minutes):
    si, cluster, perf = connect()
    seen = set()
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["entity", "object", "metric", "bucket", "value"])
        end = time.time() + minutes * 60
        while time.time() < end:
            fresh = 0
            for r in poll(perf, cluster):
                if r[:4] not in seen:
                    seen.add(r[:4]); w.writerow(r); fresh += 1
            f.flush()
            print(f"{datetime.datetime.now():%H:%M:%S} +{fresh} rows ({len(seen)} total)", flush=True)
            time.sleep(60)


def report(path):
    import collections
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        by[(r["entity"], r["metric"])].append(float(r["value"]))
    print(f"  {'entity':<20} {'metric':<18} {'n':>5} {'min':>9} {'max':>11} {'nonzero':>8}")
    for (ent, met), xs in sorted(by.items()):
        print(f"  {ent:<20} {met:<18} {len(xs):>5} {min(xs):>9.1f} {max(xs):>11.1f} "
              f"{sum(1 for x in xs if x):>8}")
    peak = max((max(xs) for (e, m), xs in by.items() if e == "vsan-cpu"), default=None)
    print(f"\n  highest vsan-cpu value seen across all seven metrics: {peak}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "capture":
        mins = int(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 90
        capture(sys.argv[2], mins)
    elif mode == "report":
        report(sys.argv[2])
    else:
        sys.exit(__doc__)
