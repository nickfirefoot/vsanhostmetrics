#!/usr/bin/env python3
"""Propose a resource-kind model from a captured /vsanmetrics exposition.

Hand-writing 155 metric definitions does not scale and will not survive the
endpoint changing between ESXi builds.  This derives the model from a real
scrape instead, so the adapter definition can be generated rather than typed.

The classification rule is the one that `stack` already follows and `io_type`
does not:

  * a label that distinguishes **different entities**      -> object IDENTITY
  * a label that distinguishes **measurements of one thing** -> METRIC KEY
  * a label that describes an entity without splitting it  -> PROPERTY

Run:  python3 tools/model_from_exposition.py <scrape.txt> [--json out.json]
"""
from __future__ import annotations
import re, sys, json, collections

# Labels every family carries; they describe the host, never split it.
HOST_LABELS = {"host_uuid", "hostname", "vsan_cluster_uuid"}

# Labels that name a *variant of a measurement* rather than a distinct entity.
# These become part of the metric key: foo{io_type=rx} -> fooRx
MEASUREMENT_LABELS = {
    "io_type", "sink_type", "source", "role", "type", "disk_role",
    "memory_type", "subsystem",
}

# Labels that identify a distinct entity worth its own object.
ENTITY_LABELS = {
    "stack", "vmnic", "cpu", "heap_name", "heap_id", "slab", "name",
    "world_id", "disk_uuid", "objuuid", "objpath", "vm_name",
    "vm_instance_uuid", "vscsi_name", "splinter_uuid", "splinter_db_name",
}

# Entity labels that are really just a display name for another identifier.
ALIAS = {"heap_name": "heap_id", "vm_name": "vm_instance_uuid", "name": "world_id"}

SAMPLE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{?([^}]*)\}?\s+([^\s]+)\s*$')
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def family_of(name: str) -> str:
    p = name.split("_")
    return "_".join(p[:3]) if len(p) > 2 else name


def load(path):
    helps, rows = {}, []
    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("# HELP "):
            k, _, v = line[7:].partition(" ")
            helps[k] = v
            continue
        if not line or line[0] == "#":
            continue
        m = SAMPLE_RE.match(line)
        if not m:
            continue
        rows.append((m.group(1), dict(LABEL_RE.findall(m.group(2) or ""))))
    return helps, rows


def build(rows):  # noqa: C901
    fams = collections.defaultdict(lambda: {
        "names": set(), "labels": collections.defaultdict(set), "series": 0})
    for name, labels in rows:
        f = fams[family_of(name)]
        f["names"].add(name)
        f["series"] += 1
        for k, v in labels.items():
            f["labels"][k].add(v)

    model = {}
    for fam, d in fams.items():
        ident, metric_parts, props, unknown = [], [], [], []
        for k, vals in sorted(d["labels"].items()):
            if k in HOST_LABELS:
                props.append(k) if k != "host_uuid" else ident.append(k)
            elif k in ENTITY_LABELS and k not in ALIAS:
                # Entity labels stay identity even when this scrape shows only
                # one value.  `stack` is the case that matters: an ENS/EDP
                # stack appears only on hosts configured for it, and if a
                # single-stack sample demoted it to a property, those hosts
                # would collapse both stacks into one object.  A classifier
                # cannot see variation that is not in its sample.
                ident.append(k)
            elif len(vals) == 1:
                props.append(k)                       # constant: descriptive
            elif k in ALIAS:
                props.append(k)                       # display name for its id
            elif k in ENTITY_LABELS:
                ident.append(k)
            elif k in MEASUREMENT_LABELS:
                metric_parts.append(k)
            else:
                unknown.append(k)

        # Refine: a label is only a measurement variant if it actually VARIES
        # within a fixed identity.  subsystem takes 8 values across 31 heaps,
        # but each heap has exactly one -- so it describes the heap rather than
        # splitting its measurements, and belongs in properties.  io_type does
        # vary within one (host_uuid, stack), so it stays.
        if metric_parts:
            id_keys = [k for k in ident if k not in HOST_LABELS]
            per_ident = collections.defaultdict(lambda: collections.defaultdict(set))
            for name, labels in rows:
                if family_of(name) != fam:
                    continue
                tup = tuple(labels.get(x, "") for x in id_keys)
                for k in metric_parts:
                    per_ident[tup][k].add(labels.get(k, ""))
            still, demoted = [], []
            for k in metric_parts:
                varies = any(len(per_ident[t][k]) > 1 for t in per_ident)
                (still if varies else demoted).append(k)
            metric_parts, props = still, props + demoted

        model[fam] = {
            "series": d["series"],
            "metric_names": sorted(d["names"]),
            "identity": ident,
            "metric_key_labels": metric_parts,
            "properties": props,
            "unclassified": unknown,
            "label_cardinality": {k: len(v) for k, v in sorted(d["labels"].items())},
        }

    # Counts must come from OBSERVED combinations, not the cross product of
    # label cardinalities.  The data is sparse: multiplying cardinalities
    # overstates this exposition by roughly 1000x.
    seen_idents = collections.defaultdict(set)
    seen_metrics = collections.defaultdict(set)
    for name, labels in rows:
        fam = family_of(name)
        m = model[fam]
        seen_idents[fam].add(
            tuple(labels.get(k, "") for k in m["identity"] if k not in HOST_LABELS))
        seen_metrics[fam].add((name,) + tuple(labels.get(k, "") for k in m["metric_key_labels"]))
    for fam, m in model.items():
        objs = max(1, len(seen_idents[fam]))
        mets = len(seen_metrics[fam])
        m["objects_per_host"] = objs
        m["metric_definitions"] = mets
        m["metrics_per_object"] = -(-mets // objs)
    return model


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    helps, rows = load(sys.argv[1])
    model = build(rows)

    tot_obj = sum(m["objects_per_host"] for m in model.values())
    tot_met = sum(m["metric_definitions"] for m in model.values())
    print(f"{len(rows)} series -> {len(model)} resource kinds\n")
    print(f"{'resource kind':26} {'obj/host':>8} {'met/obj':>8} {'met/host':>9}  identity")
    for fam in sorted(model, key=lambda f: -model[f]["objects_per_host"]):
        m = model[fam]
        ident = ",".join(k for k in m["identity"] if k not in HOST_LABELS) or "(host only)"
        print(f"  {fam:24} {m['objects_per_host']:>8} {m['metrics_per_object']:>8} "
              f"{m['metric_definitions']:>9}  {ident}")
    print(f"\n  TOTAL per host: {tot_obj} objects, {tot_met} metrics")
    print(f"  at 4 hosts    : {tot_obj*4} objects, {tot_met*4} metrics")
    print(f"  at 100 hosts  : {tot_obj*100:,} objects, {tot_met*100:,} metrics")
    print(f"  at 500 hosts  : {tot_obj*500:,} objects, {tot_met*500:,} metrics")
    print(f"\n  (sanity: series in scrape = {len(rows)})")

    unc = {f: m["unclassified"] for f, m in model.items() if m["unclassified"]}
    if unc:
        print("\n  UNCLASSIFIED labels (need a rule before generating):")
        for f, ks in sorted(unc.items()):
            print(f"    {f}: {ks}")

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump({"model": model, "helps": helps}, open(out, "w"), indent=2, default=list)
        print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
# Python emission
# --------------------------------------------------------------------------

def metric_key(family: str, name: str, meas_values) -> str:
    """Metric key for Operations.

    Operations builds a metric tree from '|' separators, which is the
    difference between a navigable dashboard and 457 flat entries.  The
    resource kind already carries the family, so the key drops that prefix:

        vmware_esx_tcppkt_total{io_type=rx}  ->  total|rx
        vmware_vsan_dom_iops{io_type=read,role=client,sink_type=hot}
                                             ->  iops|read|client|hot
    """
    short = name[len(family) + 1:] if name.startswith(family + "_") else name
    parts = [short] + [v for v in meas_values if v]
    return "|".join(parts)


def emit_python(model, helps, rows, path):
    """Write app/model.py -- the generated schema the adapter consumes."""
    import collections as _c
    seen = _c.defaultdict(set)
    for name, labels in rows:
        fam = family_of(name)
        m = model[fam]
        seen[fam].add((name,) + tuple(labels.get(k, "") for k in m["metric_key_labels"]))

    with open(path, "w") as fh:
        fh.write('"""GENERATED -- do not edit by hand.\n\n')
        fh.write("Regenerate with:\n")
        fh.write("    python3 tools/model_from_exposition.py \\\n")
        fh.write("        docs/sample-exposition-esxi01.txt --python app/model.py\n\n")
        fh.write("Derived from a real /vsanmetrics exposition.  Each family becomes one\n")
        fh.write("resource kind; identity labels split objects, measurement labels become\n")
        fh.write('part of the metric key.\n"""\n\n')
        fh.write("from typing import Dict, List, Tuple\n\n")
        fh.write("HOST_LABELS = %r\n\n" % sorted(HOST_LABELS))
        fh.write("# family -> resource kind definition\n")
        fh.write("FAMILIES: Dict[str, dict] = {\n")
        for fam in sorted(model):
            m = model[fam]
            ident = [k for k in m["identity"] if k not in HOST_LABELS]
            mets = sorted(seen[fam])
            fh.write(f"    {fam!r}: {{\n")
            fh.write(f"        'identity': {ident!r},\n")
            fh.write(f"        'metric_key_labels': {m['metric_key_labels']!r},\n")
            fh.write(f"        'properties': {[p for p in m['properties'] if p not in HOST_LABELS]!r},\n")
            fh.write(f"        'objects_per_host': {m['objects_per_host']},\n")
            fh.write("        'metrics': [\n")
            for row in mets:
                nm, vals = row[0], row[1:]
                key = metric_key(fam, nm, vals)
                h = helps.get(nm, "").strip()
                h = h.split("[from")[0].strip() if "[from" in h else h
                if vals:
                    h = f"{h} ({', '.join(v for v in vals if v)})" if h else "/".join(vals)
                fh.write(f"            ({key!r}, {nm!r}, {list(vals)!r}, {h[:180]!r}),\n")
            fh.write("        ],\n    },\n")
        fh.write("}\n\n")
        fh.write("# All source metric names we consume, for the parser's keep-filter.\n")
        fh.write("KEEP: Dict[str, str] = {\n")
        for fam in sorted(model):
            for nm in model[fam]["metric_names"]:
                fh.write(f"    {nm!r}: {fam!r},\n")
        fh.write("}\n")
    return sum(len(seen[f]) for f in model)
