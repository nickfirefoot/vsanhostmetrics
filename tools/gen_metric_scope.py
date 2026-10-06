#!/usr/bin/env python3
"""Generate app/metric_scope.py: which metrics any shipped view actually uses.

The adapter cannot import tools/, and hand-maintaining the list guarantees it
drifts from the views the moment anyone edits one. So it is GENERATED from the
same VIEWS table build_view.py renders from, and committed. Re-run this after
changing views; tools/verify_pak.py fails if the committed file is stale.

The vSAN perf API returns every metric for an entity type in one query, so
skipping a metric inside a kind we still collect saves storage, not round
trips. Skipping a kind entirely is what saves the query.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import perfsvc_model            # noqa: E402
import perfsvc_model_extra      # noqa: E402


# Kinds collected by default even though no shipped view references them yet.
# A product decision, not a derived fact, so it lives here in the open with a
# reason per entry rather than being quietly folded into the generated set.
DEFAULT_EXTRA = {
    # Asked for explicitly: per-VM IO profiling.
    "VsanIoinsight": "per-VM IO profiling",

    # Dedup/compression basics. The SAME 24 metric names appear at domclient,
    # domcompmgr and domowner for both cluster and host -- three layers of one
    # IO path. Keep the domclient layer, which is what the guest sees. The two
    # Store services (122 metrics: currentGenNum, latencyReadLockWait,
    # latencyReserveMba) are dedup engine lock and generation counters and are
    # not interpretable outside Broadcom engineering.
    "VsanClusterEsaDedupDomclientIo": "dedup basics, cluster",
    "VsanHostEsaDedupDomclientIo": "dedup basics, host",

    # OSA basics: per-device iops, latency and throughput. DiskGroup (38) is
    # excluded deliberately -- it is scheduler internals
    # (componentCongestionReadSched, iopsDelayPctSched), not a basic. DdhDisk
    # (10) is destaging detail.
    "VsanCacheDisk": "OSA cache tier basics",
    "VsanCapacityDisk": "OSA capacity tier basics",

    # Container / PVC storage. First-class virtual disks back block PVCs,
    # vSAN Direct is the cloud-native local-disk path, and file shares back
    # ReadWriteMany PVCs. iSCSI is NOT here: the target service serves
    # physical and legacy initiators, not Kubernetes.
    "VsanVirtualDisk": "FCDs back block PVCs",
    "VsanDirectCluster": "cloud-native local disk, cluster",
    "VsanDirectHost": "cloud-native local disk, host",
    "VsanFileService": "file shares back RWX PVCs",
    # Already queried for 4 of its 8 metrics by a view; completing it adds no
    # round trip, and a half-populated vSCSI object reads as broken.
    "VsanVscsi": "guest vSCSI, completing a kind already collected",
}

# Kinds identified by an ESXi THREAD -- one Operations object per world. These
# are not merely unused, they inflate object count, which is the unit
# Operations is sized and licensed by. VsanDomWorld was measured at 243
# objects carrying 3 metrics each, every one of them zero. Never collect by
# default; "all" still reaches them.
THREAD_SCOPED = ("VsanDomWorld", "VsanLsomWorldCpu")


def load_views():
    spec = importlib.util.spec_from_file_location(
        "build_view", ROOT / "tools" / "build_view.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod.VIEWS


def main():
    ents = dict(perfsvc_model.ENTITIES)
    ents.update(perfsvc_model_extra.ENTITIES)
    by_kind = {s["kind"]: list(s.get("metrics", [])) for s in ents.values()}

    used = {}
    for title, kind, columns, *_ in load_views():
        for col in columns:
            key = col[0]
            used.setdefault(kind, set()).add(
                key.split("|")[-1] if "|" in key else key)

    covered = {}
    for kind, metrics in by_kind.items():
        if kind in THREAD_SCOPED:
            continue
        if kind in DEFAULT_EXTRA:
            covered[kind] = sorted(metrics)       # whole kind; it is queried anyway
            continue
        hit = sorted(m for m in metrics if m in used.get(kind, set()))
        if hit:
            covered[kind] = hit

    total = sum(len(v) for v in by_kind.values())
    n_cov = sum(len(v) for v in covered.values())

    out = ROOT / "app" / "metric_scope.py"
    with out.open("w", encoding="utf-8") as f:
        f.write('"""Metrics any shipped view references. GENERATED -- do not '
                'edit.\n\nRegenerate with tools/gen_metric_scope.py after '
                'changing tools/build_view.py.\n\n'
                f'{len(by_kind)} kinds, {total} metrics defined; '
                f'{n_cov} referenced by views; {total - n_cov} not.\n'
                f'{len(by_kind) - len(covered)} kinds are referenced by no '
                'view at all and can be skipped\nentirely, which is the only '
                'thing that saves a round trip -- the vSAN perf API\n'
                'returns every metric of an entity type in one query.\n"""\n\n')
        f.write("COVERED = {\n")
        for kind in sorted(covered):
            f.write(f'    "{kind}": (\n')
            for m in covered[kind]:
                f.write(f'        "{m}",\n')
            f.write("    ),\n")
        f.write("}\n\n")
        f.write("# Kinds no view references. Skipping these skips their query.\n")
        f.write("UNCOVERED_KINDS = (\n")
        for kind in sorted(k for k in by_kind if k not in covered):
            f.write(f'    "{kind}",\n')
        f.write(")\n")

    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  {len(covered)} covered kinds, {n_cov} metrics")
    print(f"  {len(by_kind) - len(covered)} uncovered kinds, "
          f"{total - n_cov} metrics not referenced by any view")


if __name__ == "__main__":
    main()
