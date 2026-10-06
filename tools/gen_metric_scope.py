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
