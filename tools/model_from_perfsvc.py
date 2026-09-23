#!/usr/bin/env python3
"""Generate app/perfsvc_model.py from a live vSAN Performance Service.

Mirrors tools/model_from_exposition.py, but the source is
VsanPerfQueryPerf via vCenter rather than the host endpoint.

Two reasons this must query live data rather than read the schema:

  * VsanPerfGetSupportedEntityTypes UNDERSTATES what is returned. vsan-tcpip-stats
    advertises 16 metrics and returns 32 - every *Rate has an *Actual twin, plus
    several metrics absent from the schema entirely.
  * 39 of 70 entity types return nothing on a given cluster because the features
    are not in use. Generating from the schema would define hundreds of metrics
    that never populate.

Usage:
    python3 tools/model_from_perfsvc.py [--out app/perfsvc_model.py]
Credentials come from ~/vcenter.env (VC_HOST / VC_USER / VC_PASS).
"""
from __future__ import annotations
import ssl, sys, json, datetime, argparse

from pyVmomi import VmomiSupport
class _Noop:                      # pyVmomi dropped these; the 2021 vSAN
    def Add(self, *a, **k): pass  # bindings still import them.
for _n in ("stableVersions", "publicVersions"):
    if not hasattr(VmomiSupport, _n):
        setattr(VmomiSupport, _n, _Noop())
sys.path.insert(0, "/tmp")
import vsanmgmtObjects            # noqa: F401  (registers the vSAN types)
import vsanapiutils
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

# entityRefId is "<type>:<uuid>[|<part>[|<part>]]".  Names for those parts,
# per entity type; anything unlisted falls back to part1/part2.
IDENTITY = {
    "vsan-tcpip-stats":         ["host_uuid", "stack"],
    "vsan-vnic-net":            ["host_uuid", "stack", "vmknic"],
    "vsan-pnic-net":            ["host_uuid", "vmnic"],
    "vnic-rdt-network-latency": ["host_uuid", "vmknic"],
    "host-cpu":                 ["host_uuid", "cpu"],
    "dom-world-cpu":            ["host_uuid", "world_name", "world_id"],
    "vscsi":                    ["vm_uuid", "device"],
}
# First-part name when the entity carries only a uuid.
# Entity types that are cluster-scoped despite not being named cluster-*.
# vsan-dp-historical-stats returns the cluster UUID, which was originally
# mislabeled host_uuid -- caught because host_uuid then had 5 distinct values
# across 4 hosts.
_CLUSTER_SCOPED = {"vsan-dp-historical-stats", "vsan-cluster-capacity"}


def _root_name(ent: str) -> str:
    if ent in _CLUSTER_SCOPED:
        return "cluster_uuid"
    if ent.startswith("cluster-") or ent.startswith("vsan-cluster"):
        return "cluster_uuid"
    if ent.startswith("virtual-machine"):
        return "vm_uuid"
    if ent.startswith("virtual-disk"):
        return "vdisk_uuid"
    if ent.startswith("vsan-esa-disk"):
        return "disk_uuid"
    return "host_uuid"

LABELS = {
    "vsan-tcpip-stats": ("VsanTcpIp", "vSAN TCP/IP"),
    "vsan-pnic-net":    ("VsanPnic", "vSAN Physical NIC"),
    "vsan-vnic-net":    ("VsanVnic", "vSAN VMkernel NIC"),
    "vsan-host-net":    ("VsanHostNet", "vSAN Host Network"),
    "rdt-net":          ("VsanRdtNet", "vSAN RDT Network"),
    "rdt-network-latency":         ("VsanRdtLatency", "vSAN RDT Latency"),
    "cluster-rdt-network-latency": ("VsanClusterRdtLatency", "vSAN Cluster RDT Latency"),
    "vnic-rdt-network-latency":    ("VsanVnicRdtLatency", "vSAN VMkernel RDT Latency"),
    "host-cpu":         ("VsanHostCpu", "vSAN Host CPU"),
    "dom-world-cpu":    ("VsanDomWorld", "vSAN DOM World"),
    "vsan-cpu":         ("VsanCpu", "vSAN CPU"),
    "vsan-memory":      ("VsanMemory", "vSAN Memory"),
    "system-mem":       ("VsanSystemMemory", "vSAN System Memory"),
    "vscsi":            ("VsanVscsi", "vSAN vSCSI"),
    "virtual-disk":     ("VsanVirtualDisk", "vSAN Virtual Disk"),
    "virtual-machine":  ("VsanVirtualMachine", "vSAN Virtual Machine"),
}

def kind_and_label(ent: str):
    if ent in LABELS:
        return LABELS[ent]
    parts = [p for p in ent.replace("-", "_").split("_") if p]
    # Entity types that already begin with "vsan" must not become VsanVsan*.
    if parts and parts[0].lower() == "vsan":
        parts = parts[1:]
    return "Vsan" + "".join(p.capitalize() for p in parts), ent.replace("-", " ").title()


def connect(env):
    ctx = ssl._create_unverified_context()
    si = SmartConnect(host=env["VC_HOST"], user=env["VC_USER"],
                      pwd=env["VC_PASS"], sslContext=ctx)
    content = si.RetrieveContent()
    clusters = []
    def walk(f):
        for x in getattr(f, "childEntity", []):
            if isinstance(x, vim.ClusterComputeResource):
                clusters.append(x)
            elif hasattr(x, "childEntity"):
                walk(x)
    for dc in content.rootFolder.childEntity:
        if isinstance(dc, vim.Datacenter):
            walk(dc.hostFolder)
    mos = vsanapiutils.GetVsanVcMos(
        si._stub, context=ctx,
        version=vsanapiutils.GetLatestVmodlVersion(env["VC_HOST"]))
    return si, clusters, mos


def harvest(perf, cluster, minutes=45):
    """entity type -> (identity field names, [metric labels], object count)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    t0 = now - datetime.timedelta(minutes=minutes)
    ents = [e.name for e in perf.VsanPerfGetSupportedEntityTypes()
            if getattr(e, "name", None)]
    model = {}
    for ent in sorted(ents):
        spec = vim.cluster.VsanPerfQuerySpec(
            entityRefId=f"{ent}:*", startTime=t0, endTime=now)
        try:
            out = perf.VsanPerfQueryPerf([spec], cluster) or []
        except Exception:
            continue
        mets, nobj = [], 0
        for e in out:
            vals = [v for v in (getattr(e, "value", []) or [])
                    if (getattr(v, "values", "") or "").strip()]
            if not vals:
                continue
            nobj += 1
            if not mets:
                mets = [v.metricId.label for v in vals if getattr(v, "metricId", None)]
        if not nobj:
            continue                      # defined but no data on this cluster
        ref = out[0].entityRefId
        tail = ref.split(":", 1)[1] if ":" in ref else ""
        arity = len(tail.split("|"))
        ids = IDENTITY.get(ent) or ([_root_name(ent)] +
                                    [f"part{i}" for i in range(1, arity)])
        model[ent] = {"identity": ids[:arity], "metrics": mets, "objects": nobj}
    return model


def emit(model, path):
    with open(path, "w") as fh:
        fh.write('"""GENERATED -- do not edit by hand.\n\n')
        fh.write("Regenerate with:\n    python3 tools/model_from_perfsvc.py\n\n")
        fh.write("Derived from a LIVE vSAN Performance Service, not its schema:\n")
        fh.write("VsanPerfGetSupportedEntityTypes understates what is returned\n")
        fh.write("(vsan-tcpip-stats advertises 16 metrics and returns 32), and 39\n")
        fh.write("of 70 entity types return nothing when the feature is unused.\n")
        fh.write('"""\n\nfrom typing import Dict\n\n')
        fh.write("ENTITIES: Dict[str, dict] = {\n")
        for ent in sorted(model):
            d = model[ent]
            kind, label = kind_and_label(ent)
            fh.write(f"    {ent!r}: {{\n")
            fh.write(f"        'kind': {kind!r},\n")
            fh.write(f"        'label': {label!r},\n")
            fh.write(f"        'identity': {d['identity']!r},\n")
            fh.write(f"        'objects_observed': {d['objects']},\n")
            fh.write("        'metrics': [\n")
            for m in d["metrics"]:
                fh.write(f"            {m!r},\n")
            fh.write("        ],\n    },\n")
        fh.write("}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="app/perfsvc_model.py")
    ap.add_argument("--minutes", type=int, default=45)
    a = ap.parse_args()
    env = {}
    for line in open("/home/vsanmp/vcenter.env"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            env[k] = v.strip().strip("'")
    si, clusters, mos = connect(env)
    model = harvest(mos["vsan-performance-manager"], clusters[0], a.minutes)
    emit(model, a.out)
    tot_m = sum(len(d["metrics"]) for d in model.values())
    tot_o = sum(d["objects"] for d in model.values())
    print(f"  {len(model)} entity types with data")
    print(f"  {tot_m} metric definitions, {tot_o} objects observed")
    print(f"  wrote {a.out}")
    Disconnect(si)


if __name__ == "__main__":
    main()
