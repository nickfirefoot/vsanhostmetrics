#!/usr/bin/env python3
"""SUPERSEDED -- see content/DASHBOARD-STORYBOARD.md.

Cloning a working export was judged more complex than the problem
warranted: what is wanted is importable files, and those come from
building in the UI. Kept because the clone approach is the right one IF
generation is ever revisited -- it mutates a proven artifact rather than
reconstructing the format from notes.
"""

# Original module docstring follows.
"""Build dashboards by CLONING a known-good export, not by reconstructing one.

    python3 tools/clone_dashboard.py

Every dashboard this project generated from first principles failed on import:
Operations showed a generic object badge, or "this dashboard is not done
configuring", or nothing. Diffing a generated file against a dashboard the
user built by hand in the UI and exported
(`docs/assets/dashboard.interaction-working.json`, proven to render
`avgLatency` off a cluster selection) found eight dashboard-level differences,
including `userId` / `lastUpdateUserId` set to `""` -- a dashboard with no
owner -- and three keys that do not exist in a real export at all.

So the format is not reliably reconstructable from notes. It IS reliably
clonable: take the working file verbatim and mutate only the fields that have
to change (ids, name, which metrics a Scoreboard points at). Every other byte
stays as Operations itself wrote it, including fields nobody has decoded.

New Scoreboards are made by deep-copying the working Scoreboard and editing
it, so they cannot acquire an extra key or lose one.
"""
import copy
import json
import os
import sys
import uuid
import zipfile

sys.path.insert(0, "app")
sys.path.insert(0, "tools")
import perfsvc_model                                        # noqa: E402
import perfsvc_model_extra                                  # noqa: E402

WORKING = "docs/assets/dashboard.interaction-working.json"
ADAPTER = "VsanHostMetrics"


def kind_label(resource_kind):
    """The human name Operations shows for one of our resource kinds."""
    for src in (perfsvc_model.ENTITIES, perfsvc_model_extra.ENTITIES):
        for spec in src.values():
            if spec["kind"] == resource_kind:
                return spec["label"]
    raise SystemExit(f"unknown resource kind {resource_kind}")


def validate(resource_kind, metric):
    """Fail loudly rather than shipping a panel that silently renders nothing."""
    for src in (perfsvc_model.ENTITIES, perfsvc_model_extra.ENTITIES):
        for spec in src.values():
            if spec["kind"] == resource_kind and metric in spec["metrics"]:
                return
    raise SystemExit(f"{resource_kind} has no metric {metric}")


def load():
    doc = json.load(open(WORKING))
    db = doc["dashboards"][0]
    provider = next(w for w in db["widgets"] if w["type"] == "ResourceList")
    template = next(w for w in db["widgets"] if w["type"] == "Scoreboard")
    return doc, db, provider, template


def scoreboard_from(template, title, resource_kind, metrics, coords,
                    kind_ref, columns=4, value_size=10, label_size=9):
    """Deep-copy the proven Scoreboard, then change only what must change.

    metrics: [(metricKey, label, yellow, orange, red)]. Bounds of None leave
    the entry's colouring exactly as the working example had it.
    """
    w = copy.deepcopy(template)
    wid = str(uuid.uuid4())
    w["id"] = wid
    w["config"]["widgetId"] = wid
    w["title"] = title
    w["config"]["title"] = title
    w["gridsterCoords"] = dict(coords)
    w["config"]["boxColumns"] = columns
    w["config"]["valueSize"] = value_size
    w["config"]["labelSize"] = label_size

    entry_template = template["config"]["metric"]["resourceKindMetrics"][0]
    name = kind_label(resource_kind)
    entries = []
    for i, (key, label, yb, ob, rb) in enumerate(metrics):
        validate(resource_kind, key)
        e = copy.deepcopy(entry_template)
        e["metricKey"] = key
        e["metricName"] = label
        e["resourceKindName"] = name
        e["resourceKindId"] = kind_ref
        # Numeric after the prefix, matching every real export seen.
        e["id"] = f"extModel{25291 + i}-{i + 1}"
        if any(b is not None for b in (yb, ob, rb)):
            e["yellowBound"], e["orangeBound"], e["redBound"] = yb, ob, rb
            e["colorMethod"] = 0
        return_keys = set(e) ^ set(entry_template)
        assert not return_keys, f"key drift in metric entry: {return_keys}"
        entries.append(e)
    w["config"]["metric"]["resourceKindMetrics"] = entries
    return w


def clone(name, panels):
    """panels: [(title, resource_kind, metrics, coords, columns)]."""
    doc, db, provider, template = load()
    doc = copy.deepcopy(doc)
    db = doc["dashboards"][0]
    provider = next(w for w in db["widgets"] if w["type"] == "ResourceList")
    template = next(w for w in db["widgets"] if w["type"] == "Scoreboard")

    did = str(uuid.uuid4())
    db["id"] = did
    db["name"] = name
    doc["uuid"] = str(uuid.uuid4())

    # One entries.resourceKind slot per distinct kind, numbered as Operations
    # numbers them. The working file already has slot 0.
    kinds, refs = [], {}
    for _, resource_kind, _, _, _ in panels:
        if resource_kind not in refs:
            refs[resource_kind] = f"resourceKind:id:{len(kinds)}_::_"
            kinds.append({"resourceKindKey": resource_kind,
                          "internalId": refs[resource_kind],
                          "adapterKindKey": ADAPTER})
    doc["entries"]["resourceKind"] = kinds

    # Provider keeps its own id fresh but every other byte as exported.
    pid = str(uuid.uuid4())
    provider["id"] = pid
    provider["config"]["widgetId"] = pid
    provider["tabId"] = did

    widgets = [provider]
    for title, resource_kind, metrics, coords, columns in panels:
        w = scoreboard_from(template, title, resource_kind, metrics, coords,
                            refs[resource_kind], columns=columns)
        w["tabId"] = did
        widgets.append(w)

    db["widgets"] = widgets
    db["widgetInteractions"] = [
        {"widgetIdProvider": pid, "type": "resourceId", "widgetIdReceiver": w["id"]}
        for w in widgets[1:]]
    return doc


def write(doc, name):
    os.makedirs("dist/dashboards", exist_ok=True)
    out = f"dist/dashboards/{name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dashboard/dashboard.json", json.dumps(doc, indent=1))
    db = doc["dashboards"][0]
    print(f"  {out}  ({db['name']})")
    for w in db["widgets"]:
        if w["type"] != "Scoreboard":
            continue
        keys = [e["metricKey"] for e in w["config"]["metric"]["resourceKindMetrics"]]
        print(f"    {w['title'][:44]:46} {','.join(keys)}")
    return out


def bisect_probe():
    """Three panels that isolate WHY a generated dashboard fails.

    1. control  -- byte-identical to the panel that works. If this is blank,
                   the clone itself is wrong and nothing below means anything.
    2. one metric on a host-level kind -- tests whether depth 4 really reaches
                   two hops down (cluster -> host -> pNIC).
    3. two metrics on that same kind    -- tests whether more than one metric
                   per Scoreboard survives.
    """
    return clone("Rapid vSAN Clone Test", [
        ("1 CONTROL: RDT latency (proven panel)", "VsanClusterRdtLatency",
         [("avgLatency", "RDT Network VNIC Average Latency", None, None, None)],
         {"w": 4, "x": 1, "h": 6, "y": 5}, 2),
        ("2 DEPTH 2: one pNIC metric", "VsanPnic",
         [("rxMissErr", "RX missed errors (ring full)", None, None, None)],
         {"w": 4, "x": 5, "h": 6, "y": 5}, 4),
        ("3 DEPTH 2: two pNIC metrics", "VsanPnic",
         [("rxMissErr", "RX missed errors (ring full)", None, None, None),
          ("rxCrcErr", "RX CRC errors", None, None, None)],
         {"w": 4, "x": 9, "h": 6, "y": 5}, 4),
    ])


if __name__ == "__main__":
    write(bisect_probe(), "rapid-clone-test")
