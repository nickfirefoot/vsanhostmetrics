#!/usr/bin/env python3
"""Generate dashboards by cloning a confirmed-working export.

    python3 tools/build_dash.py        # writes to ~/ops-content/out/

Clones `docs/assets/dashboard.rapid-network-v4.json` -- built by hand in the
UI, imported, and confirmed rendering -- and swaps only the identifiers, the
titles, which view each widget renders, and the layout. Everything else stays
as Operations itself wrote it, including fields nobody here has decoded.

Same reasoning as `build_view.py` and for the same reason: reconstructing
these formats from notes failed repeatedly; cloning a proven artefact works.

What was learned from that export and is preserved here:

  provider   View widget, selfProvider ON, rooted at VCF World, pointing at a
             view that lists clusters, selectFirstRow ON
  receiver   View widget, selfProvider OFF, `resource` null, traversalSpecId
             empty, viewType LIST, pointing at a view by GUID. The view's own
             descendant/self SubjectType does the traversal, so the widget
             needs no depth setting
  wiring     one widgetInteractions entry per receiver, type resourceId
  text       TextDisplay with viewModeHTML true and the markup in `editorData`
             -- NOT `description`, which stays empty
"""
import copy
import json
import os
import uuid

TEMPLATE = "docs/assets/dashboard.rapid-network-v4.json"
OUT = os.path.expanduser("~/ops-content/out")
HELP = os.path.expanduser("~/ops-content/out/help")

# view GUIDs, from tools/build_view.py
V = {
    "pnic":      "09f4cb2e-f52c-412a-826d-ee04a3d07d0f",
    "tcp":       "c10ec3f1-e693-5b3d-af81-d2d19de1c341",
    "rdt":       "c51f5531-ccea-543d-9a73-0e0d5e359d1a",
    "hostnet":   "d46f58a8-e3a4-519f-9124-ac8ff83871c5",
    "esa":       "74e1354d-757f-5ca7-a9e4-25e01718c627",
    "esaphys":   "4edb922b-10e6-5f18-b0d8-77cdba6df121",
    "vm":        "24773067-9b6e-536a-a39c-46353dfd5068",
    # the cluster selector, shipped with the pak so a dashboard does not
    # depend on a view the customer happens to have built themselves
    "clusters":  "057a006b-7ad1-5df7-af19-832b788b7b16",
}

# (title, view-key, gridster)  -- the cluster selector is added automatically
DASHBOARDS = [
    ("Rapid vSAN Network", "rapid-vsan-network-help", [
        ("RDT latencies",    "rdt",     {"w": 10, "x": 3, "h": 9, "y": 1}),
        ("TCP error types",  "tcp",     {"w": 12, "x": 1, "h": 8, "y": 10}),
        ("pNIC stats",       "pnic",    {"w": 12, "x": 1, "h": 9, "y": 18}),
        ("Host network",     "hostnet", {"w": 12, "x": 1, "h": 7, "y": 27}),
    ]),
    ("Rapid vSAN Storage", "rapid-vsan-storage-help", [
        ("ESA disks - vSAN layer",     "esa",     {"w": 10, "x": 3, "h": 9, "y": 1}),
        ("ESA disks - physical layer", "esaphys", {"w": 12, "x": 1, "h": 8, "y": 10}),
        ("VM storage",                 "vm",      {"w": 12, "x": 1, "h": 9, "y": 18}),
    ]),
]


def receiver(template_receiver, title, view_guid, coords, tab):
    w = copy.deepcopy(template_receiver)
    wid = str(uuid.uuid4())
    w["id"] = wid
    w["tabId"] = tab
    w["gridsterCoords"] = dict(coords)
    # the widget carries its title in TWO places; setting only config.title
    # leaves the template's name on the frame
    w["title"] = title
    c = w["config"]
    c["widgetId"] = wid
    c["title"] = title
    c["titleLocalized"] = title
    c["viewDefinitionId"] = view_guid
    return w


def build(template, name, help_file, panels):
    doc = copy.deepcopy(template)
    db = doc["dashboards"][0]
    tab = str(uuid.uuid4())
    db["id"] = tab
    db["name"] = name
    db["description"] = ""
    doc["uuid"] = str(uuid.uuid4())

    widgets = {w["type"] + ":" + (w["config"].get("title") or ""): w
               for w in db["widgets"]}
    provider = next(w for w in db["widgets"]
                    if w["type"] == "View"
                    and (w["config"].get("selfProvider") or {}).get("selfProvider"))
    recv_tpl = next(w for w in db["widgets"]
                    if w["type"] == "View"
                    and not (w["config"].get("selfProvider") or {}).get("selfProvider"))
    text_tpl = next((w for w in db["widgets"] if w["type"] == "TextDisplay"), None)

    prov = copy.deepcopy(provider)
    pid = str(uuid.uuid4())
    prov["id"] = pid
    prov["tabId"] = tab
    prov["config"]["widgetId"] = pid
    prov["title"] = prov["config"].get("title") or "Select cluster"
    prov["gridsterCoords"] = {"w": 2, "x": 1, "h": 9, "y": 1}
    prov["config"]["viewDefinitionId"] = V["clusters"]

    out = [prov]
    for title, key, coords in panels:
        out.append(receiver(recv_tpl, title, V[key], coords, tab))

    if text_tpl is not None:
        t = copy.deepcopy(text_tpl)
        tid = str(uuid.uuid4())
        t["id"] = tid
        t["tabId"] = tab
        t["config"]["widgetId"] = tid
        t["title"] = "How to read this"
        bottom = max(p[2]["y"] + p[2]["h"] for p in panels)
        t["gridsterCoords"] = {"w": 12, "x": 1, "h": 7, "y": bottom}
        path = os.path.join(HELP, f"{help_file}.EDITOR.html") if help_file else None
        if path and os.path.exists(path):
            t["config"]["editorData"] = open(path).read()
            t["config"]["description"] = ""
            t["config"]["viewModeHTML"] = True
            t["config"]["title"] = "How to read this"
        else:
            t["config"]["editorData"] = ""
            t["config"]["title"] = "How to read this"
        out.append(t)

    db["widgets"] = out
    db["widgetInteractions"] = [
        {"widgetIdProvider": pid, "type": "resourceId", "widgetIdReceiver": w["id"]}
        for w in out[1:] if w["type"] == "View"]
    return doc


def main() -> None:
    template = json.load(open(TEMPLATE))
    os.makedirs(OUT, exist_ok=True)
    import zipfile
    for name, help_file, panels in DASHBOARDS:
        doc = build(template, name, help_file, panels)
        fn = name.replace(" ", "_")
        with zipfile.ZipFile(os.path.join(OUT, f"{fn}.zip"), "w",
                             zipfile.ZIP_DEFLATED) as z:
            z.writestr("dashboard/dashboard.json", json.dumps(doc, indent=1))
        db = doc["dashboards"][0]
        print(f"  {fn}.zip")
        for w in db["widgets"]:
            c = w["config"]
            v = (c.get("viewDefinitionId") or "")[:8]
            print("     %-28s %-12s %s" % ((c.get("title") or "")[:28], w["type"], v))


if __name__ == "__main__":
    main()
