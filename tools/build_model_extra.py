#!/usr/bin/env python3
"""Generate app/perfsvc_model_extra.py -- entity types absent from the live model.

    python3 tools/build_model_extra.py

perfsvc_model.py is generated from a LIVE Performance Service, so it contains
only entity types that actually returned data. On an ESA cluster that silently
excludes every OSA family -- disk groups, cache and capacity disks, disk
health. Install on an OSA cluster and the pack collects none of it, because it
never asks.

This fills the gap from the service's advertised schema
(`docs/assets/perfsvc_schema.json`), so the families are queried wherever they
exist. It is deliberately a SEPARATE file: regenerating the live model must not
clobber it, and it must be obvious that these entries are provisional.

**Metrics here are the advertised set, which understates reality.** The service
returns more than it advertises -- vsan-tcpip-stats advertises 16 and returns
32 -- so a real OSA cluster should be modelled properly by running
`tools/model_from_perfsvc.py` against it and folding the result into
perfsvc_model.py. These entries are a starting point, not an authority.

**Only entity types that accept a WILDCARD query are included.** Measured
against a live service: clom-disk, clom-host, cmmds-workload, ddh-disk,
heap-memory and slab-memory all reject `<entity>:*` with InvalidArgument, so
including them would log a collection problem every cycle forever and mask real
ones. They would need explicit entityRefIds, which means knowing the uuids in
advance.

**Identity is inferred**, from the entity name and from how the analogous ESA
families are keyed. `parse_ref` pads variable arity, so a wrong guess produces
oddly-named identifiers rather than lost objects, and any unmodelled shape is
reported as a collection problem rather than dropped silently.
"""
import json
import re

SCHEMA = "docs/assets/perfsvc_schema.json"
OUT = "app/perfsvc_model_extra.py"

# entity -> (identity components, human label). Identity is INFERRED; see the
# module docstring. Chosen to match how the equivalent ESA family is keyed.
WANTED = {
    # --- OSA storage stack. The reason this file exists. ---
    "disk-group":     (["disk_uuid"], "vSAN Disk Group (OSA)"),
    "cache-disk":     (["disk_uuid"], "vSAN Cache Disk (OSA)"),
    "capacity-disk":  (["disk_uuid"], "vSAN Capacity Disk (OSA)"),


    # --- cluster-wide families that return nothing on an idle ESA lab ---
    "cluster-resync": (["cluster_uuid"], "vSAN Cluster Resync"),

    "lsom-world-cpu": (["host_uuid", "world_name", "world_id"], "vSAN LSOM World CPU"),
}


def kind_for(entity):
    """Operations resource-kind key: VsanCamelCase, matching the live model."""
    parts = [p for p in re.split(r"[-_]", entity) if p]
    camel = "".join(p[:1].upper() + p[1:] for p in parts)
    return camel if camel.lower().startswith("vsan") else "Vsan" + camel


def main() -> None:
    schema = json.load(open(SCHEMA))
    entries = {}
    for entity, (identity, label) in sorted(WANTED.items()):
        metrics = sorted(schema.get(entity, {}))
        if not metrics:
            print(f"  SKIP {entity}: not in the advertised schema")
            continue
        entries[entity] = {
            "kind": kind_for(entity), "label": label,
            "identity": identity, "objects_observed": 0, "metrics": metrics,
        }

    with open(OUT, "w") as fh:
        fh.write('"""GENERATED -- do not edit by hand.\n\n')
        fh.write("Regenerate:\n    python3 tools/build_model_extra.py\n\n")
        fh.write("Entity types the LIVE model omits because they returned no data on the\n")
        fh.write("cluster it was generated against -- principally every OSA family, which is\n")
        fh.write("silent on ESA. Without these the pack never queries them, so an OSA cluster\n")
        fh.write("collects nothing for its disk groups or cache and capacity disks.\n\n")
        fh.write("PROVISIONAL. Metrics are the ADVERTISED set, which understates what the\n")
        fh.write("service returns; identity is INFERRED from the entity name and the\n")
        fh.write("equivalent ESA families. Model a real OSA cluster properly with\n")
        fh.write("tools/model_from_perfsvc.py and fold the result into perfsvc_model.py.\n")
        fh.write('"""\n\nfrom typing import Any, Dict\n\n')
        fh.write("ENTITIES: Dict[str, Dict[str, Any]] = {\n")
        for entity, spec in entries.items():
            fh.write(f"    {entity!r}: {{\n")
            for key in ("kind", "label", "identity", "objects_observed"):
                fh.write(f"        {key!r}: {spec[key]!r},\n")
            fh.write("        'metrics': [\n")
            for m in spec["metrics"]:
                fh.write(f"            {m!r},\n")
            fh.write("        ],\n    },\n")
        fh.write("}\n")

    total = sum(len(s["metrics"]) for s in entries.values())
    print(f"  wrote {OUT}: {len(entries)} entity types, {total} metrics")
    for e, s in entries.items():
        print(f"    {e:16} {s['kind']:24} {len(s['metrics']):3} metrics  id={s['identity']}")


if __name__ == "__main__":
    main()
