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
    "vSAN_Cluster_Capacity": '80f0f637-d7a6-5252-aaba-6c9d04772960',
    "vSAN_Cluster_DOM_Client": '961aa3db-a230-5c2d-8ce5-00b666bdcdbd',
    "vSAN_Cluster_DOM_Component_Manager": 'b597d3fd-2fbb-546e-88f8-3f6d42537dcf',
    "vSAN_Cluster_RDT": 'c972e782-317e-55b8-b5db-400c703ccfa7',
    "vSAN_Cluster_Resync": 'e12fcf23-eb55-5555-9bf9-b7c4c91d1135',
    "vSAN_Clusters": '057a006b-7ad1-5df7-af19-832b788b7b16',
    "vSAN_ESA_Disk_Physical_Layer": '4edb922b-10e6-5f18-b0d8-77cdba6df121',
    "vSAN_ESA_Disks": '74e1354d-757f-5ca7-a9e4-25e01718c627',
    "vSAN_Host_DOM": 'bf403bc1-f535-5b44-b5d2-219cec8e662d',
    "vSAN_Host_Network": 'd46f58a8-e3a4-519f-9124-ac8ff83871c5',
    "vSAN_Host_TCP_Health": 'c10ec3f1-e693-5b3d-af81-d2d19de1c341',
    "vSAN_RDT_Transport_Per_Host": 'c51f5531-ccea-543d-9a73-0e0d5e359d1a',
    "vSAN_VM_Storage": '24773067-9b6e-536a-a39c-46353dfd5068',
    "vSAN_pNIC_Errors": '09f4cb2e-f52c-412a-826d-ee04a3d07d0f',
}

# (title, view-key, gridster)  -- the cluster selector is added automatically
DASHBOARDS = [
    ("Rapid vSAN Overview", "rapid-vsan-overview-help", [
        ("Capacity",                  "vSAN_Cluster_Capacity",             {"w":10,"x":3,"h":5,"y":1}),
        ("Front end - what VMs feel", "vSAN_Cluster_DOM_Client",           {"w":12,"x":1,"h":6,"y":6}),
        ("Back end - the disks",      "vSAN_Cluster_DOM_Component_Manager",{"w":12,"x":1,"h":6,"y":12}),
        ("Transport - RDT",           "vSAN_Cluster_RDT",                  {"w":12,"x":1,"h":6,"y":18}),
        ("Rebuild activity",          "vSAN_Cluster_Resync",               {"w":12,"x":1,"h":6,"y":24}),
    ]),
    ("Rapid vSAN Network", "rapid-vsan-network-help", [
        ("RDT latencies",   "vSAN_RDT_Transport_Per_Host", {"w":10,"x":3,"h":9,"y":1}),
        ("TCP error types", "vSAN_Host_TCP_Health",        {"w":12,"x":1,"h":8,"y":10}),
        ("pNIC stats",      "vSAN_pNIC_Errors",            {"w":12,"x":1,"h":9,"y":18}),
        ("Host network",    "vSAN_Host_Network",           {"w":12,"x":1,"h":7,"y":27}),
    ]),
    ("Rapid vSAN Storage", "rapid-vsan-storage-help", [
        ("ESA disks - vSAN layer",     "vSAN_ESA_Disks",               {"w":10,"x":3,"h":9,"y":1}),
        ("ESA disks - physical layer", "vSAN_ESA_Disk_Physical_Layer", {"w":12,"x":1,"h":8,"y":10}),
        ("VM storage",                 "vSAN_VM_Storage",              {"w":12,"x":1,"h":9,"y":18}),
    ]),
    ("Rapid vSAN DOM", "rapid-vsan-dom-help", [
        ("Cluster - client",         "vSAN_Cluster_DOM_Client",           {"w":10,"x":3,"h":7,"y":1}),
        ("Cluster - comp manager",   "vSAN_Cluster_DOM_Component_Manager",{"w":12,"x":1,"h":6,"y":8}),
        ("Per host - DOM client",    "vSAN_Host_DOM",                     {"w":12,"x":1,"h":8,"y":14}),
    ]),
    ("Rapid vSAN Resync", "rapid-vsan-resync-help", [
        ("Rebuild activity",      "vSAN_Cluster_Resync",     {"w":10,"x":3,"h":7,"y":1}),
        ("Guest impact",          "vSAN_Cluster_DOM_Client", {"w":12,"x":1,"h":7,"y":8}),
        ("Back end",              "vSAN_Cluster_DOM_Component_Manager", {"w":12,"x":1,"h":6,"y":15}),
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
    prov["config"]["viewDefinitionId"] = V["vSAN_Clusters"]

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
