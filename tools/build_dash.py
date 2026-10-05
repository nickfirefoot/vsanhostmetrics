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

# View GUIDs are DERIVED from build_view, not copied. They were previously
# a hand-maintained table here, which is a drift waiting to happen: rename a
# view and its uuid5 moves, and a stale literal points a widget at a GUID
# that no longer exists. Importing the generator makes that impossible.
import sys
sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                        # noqa: E402

V = {entry[0].replace(" ", "_"): build_view.guid_for(entry[0])
     for entry in build_view.VIEWS}

# (panel title, view key, gridster coords). The cluster selector is added
# automatically as the provider, and the help panel is appended at the bottom.
#
# Refined 2026-10-01 against a live collection. Three problems were being
# fixed, all of them visible only once the collected data was compared with
# what the screens actually showed:
#
#   1. Resync had NO content of its own -- all three of its views also
#      appeared on Overview, so it was a duplicate screen. It now leads with
#      the resync JOB QUEUE, which nothing had surfaced.
#   2. The DOM owner layer was entirely absent. It returns 272 metrics live,
#      87 of which move, and it is the layer where distributed-write cost
#      actually appears. Three new views cover it.
#   3. zDOM, the ESA write path, was absent. Segment cleaning was measured at
#      370 ms worst-case latency against a 1.3 ms average and no screen in
#      the pack could have shown it.
DASHBOARDS = [
    ("Rapid vSAN Overview", "rapid-vsan-overview-help", [
        ("Capacity",                      "vSAN_Cluster_Capacity",              {"w":10,"x":3,"h":5,"y":1}),
        ("Front end - what VMs feel",     "vSAN_Cluster_DOM_Client",            {"w":12,"x":1,"h":6,"y":6}),
        ("Coordination - the owner",      "vSAN_Cluster_DOM_Owner",             {"w":12,"x":1,"h":6,"y":12}),
        ("Back end - the disks",          "vSAN_Cluster_DOM_Component_Manager", {"w":12,"x":1,"h":6,"y":18}),
        ("Transport - RDT",               "vSAN_Cluster_RDT",                   {"w":12,"x":1,"h":6,"y":24}),
        ("Host health and load",          "vSphere_Host_Uplinks_and_Load",      {"w":12,"x":1,"h":6,"y":30}),
    ]),
    # TCP sits BELOW the NIC panels, moved on review. The screen now reads
    # strictly top down through the layers that carry vSAN traffic: vSAN's own
    # transport first, then the kernel port, then the wire, and only then the
    # TCP stack underneath all of it. TCP was previously third, which put the
    # most abstract layer above the two physical ones feeding it.
    ("Rapid vSAN Network", "rapid-vsan-network-help", [
        ("RDT latencies - per host",      "vSAN_RDT_Transport_Per_Host", {"w":10,"x":3,"h":9,"y":1}),
        ("RDT latencies - per vmknic",    "vSAN_vmknic_RDT_Latency",     {"w":12,"x":1,"h":7,"y":10}),
        ("pNIC stats - vSAN uplinks",     "vSAN_pNIC_Errors",            {"w":12,"x":1,"h":9,"y":17}),
        ("vmknic - the kernel port",      "vSAN_vmknic",                 {"w":12,"x":1,"h":7,"y":26}),
        ("Host network - all vSAN",       "vSAN_Host_Network",           {"w":12,"x":1,"h":7,"y":33}),
        ("TCP error types",               "vSAN_Host_TCP_Health",        {"w":12,"x":1,"h":8,"y":40}),
        ("Every uplink - from vCenter",   "vSphere_Host_Uplinks_and_Load", {"w":12,"x":1,"h":7,"y":48}),
        ("CMMDS - cluster membership",    "vSAN_CMMDS_Network",          {"w":12,"x":1,"h":7,"y":55}),
    ]),
    ("Rapid vSAN Storage", "rapid-vsan-storage-help", [
        ("ESA disks - vSAN layer",        "vSAN_ESA_Disks",                  {"w":10,"x":3,"h":9,"y":1}),
        ("ESA disks - physical layer",    "vSAN_ESA_Disk_Physical_Layer",    {"w":12,"x":1,"h":8,"y":10}),
        ("Back end - per host",           "vSAN_Host_DOM_Component_Manager", {"w":12,"x":1,"h":8,"y":18}),
        ("Capacity",                      "vSAN_Cluster_Capacity",           {"w":12,"x":1,"h":5,"y":26}),
        ("VM storage - per controller",   "vSAN_VM_Storage",                 {"w":12,"x":1,"h":9,"y":31}),
        ("VM latency - per VM",           "vSAN_VM_Latency",                 {"w":12,"x":1,"h":8,"y":40}),
    ]),
    ("Rapid vSAN DOM", "rapid-vsan-dom-help", [
        ("Cluster - client",              "vSAN_Cluster_DOM_Client",            {"w":10,"x":3,"h":7,"y":1}),
        ("Cluster - owner",               "vSAN_Cluster_DOM_Owner",             {"w":12,"x":1,"h":6,"y":8}),
        ("Cluster - component manager",   "vSAN_Cluster_DOM_Component_Manager", {"w":12,"x":1,"h":6,"y":14}),
        ("Per host - client",             "vSAN_Host_DOM",                      {"w":12,"x":1,"h":7,"y":20}),
        ("Per host - owner",              "vSAN_Host_DOM_Owner",                {"w":12,"x":1,"h":8,"y":27}),
        ("Per host - component manager",  "vSAN_Host_DOM_Component_Manager",    {"w":12,"x":1,"h":8,"y":35}),
        ("Owner network scheduler",       "vSAN_Host_DOM_Owner_Scheduler",      {"w":12,"x":1,"h":8,"y":43}),
    ]),
    ("Rapid vSAN Resync", "rapid-vsan-resync-help", [
        ("Jobs outstanding - the risk",   "vSAN_Cluster_Resync_Jobs",           {"w":10,"x":3,"h":8,"y":1}),
        ("Rebuild IO rates",              "vSAN_Cluster_Resync",                {"w":12,"x":1,"h":6,"y":9}),
        ("Guest impact - front end",      "vSAN_Cluster_DOM_Client",            {"w":12,"x":1,"h":6,"y":15}),
        ("Back end during rebuild",       "vSAN_Cluster_DOM_Component_Manager", {"w":12,"x":1,"h":6,"y":21}),
        ("Is vSAN throttling itself?",    "vSAN_Host_DOM_Owner_Scheduler",      {"w":12,"x":1,"h":8,"y":27}),
        ("Segment cleaning",              "vSAN_Segment_Cleaning_Per_Host",     {"w":12,"x":1,"h":8,"y":35}),
    ]),
    ("Rapid vSAN ESA Write Path", "rapid-vsan-esa-write-path-help", [
        ("zDOM - cluster",                "vSAN_zDOM_Cluster",               {"w":10,"x":3,"h":6,"y":1}),
        ("zDOM - per host",               "vSAN_zDOM_Per_Host",              {"w":12,"x":1,"h":8,"y":7}),
        ("Write path internals",          "vSAN_zDOM_Write_Path",            {"w":12,"x":1,"h":8,"y":15}),
        ("Segment cleaning",              "vSAN_Segment_Cleaning_Per_Host",  {"w":12,"x":1,"h":8,"y":23}),
        ("Back end - per host",           "vSAN_Host_DOM_Component_Manager", {"w":12,"x":1,"h":8,"y":31}),
    ]),
    # The "vSAN service health" panel is gone. It rendered its rows and left
    # every cell blank, because the daemon liveness metrics behind it carry a
    # current value and no retained history, and a view queries a time range.
    # What survived of it folded into the vCenter host view below.
    ("Rapid vSAN Host Resources", "rapid-vsan-host-resources-help", [
        ("Host health and load",          "vSphere_Host_Uplinks_and_Load", {"w":10,"x":3,"h":7,"y":1}),
        ("vSAN daemon memory",            "vSAN_Host_Memory",              {"w":12,"x":1,"h":8,"y":8}),
        ("Physical CPU - per pCPU",       "vSAN_Host_CPU",                 {"w":12,"x":1,"h":8,"y":16}),
    ]),
]


# The template's widgets carry a `states` blob holding per-widget column
# visibility, keyed `permTableView_widget_<tabId>_<widgetId>`. It is STRIPPED,
# not repaired, and the history is worth keeping because the repair was worse
# than the bug.
#
# 1.4.0 cloned the blob verbatim, so its key named a widget that did not exist.
#    Operations found no state for the widget it was drawing and fell back to
#    showing every column. That worked.
# 1.4.1 "fixed" it by rewriting the ids to the generated ones. The state then
#    APPLIED -- and it had been written against a different view. It says
#    `column-0 hidden=1` and `column-config|name1 hidden=0`. Our cluster
#    selector renders a view whose only column is `Configuration|Name`, so the
#    state hid the object-name column and un-hid a column that does not exist.
#    The selector drew one blank row reading "-", still selected a cluster and
#    still drove every panel, which is why it looked like a rendering failure
#    rather than a column-visibility one.
#
# A states blob is one person's UI preference, captured in one browser session,
# against one view. It has no business being cloned onto generated content at
# all. Dropping it restores the 1.4.0 behaviour by intent rather than by
# accident: Operations has no saved state and shows the columns the view
# defines, which is what we want.


def destate(widget):
    """Drop saved per-widget UI state. See the note above."""
    widget.pop("states", None)
    widget.pop("state", None)


def receiver(template_receiver, title, view_guid, coords, tab):
    w = copy.deepcopy(template_receiver)
    wid = str(uuid.uuid4())
    destate(w)
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
    # Taken from a dashboard corrected in the UI and re-exported, diffed
    # against the generated one. Both of these were wrong in the template.
    #
    # `shared` false means the dashboard is visible to its owner alone. Since
    # the file also carries a hard-coded userId, on anybody else's instance
    # that is an owner who does not exist and nobody can see it.
    #
    # `adapterName` must be the pak's internal name from manifest.txt, not the
    # display name. Operations rewrote 'vSAN Host Metrics' to this on save.
    db["shared"] = True
    db["adapterName"] = "iSDK_VsanHostMetrics"

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
    destate(prov)
    prov["id"] = pid
    prov["tabId"] = tab
    prov["config"]["widgetId"] = pid
    prov["title"] = prov["config"].get("title") or "Select cluster"
    # The selector's height must MATCH THE FIRST PANEL'S, not be a fixed 9.
    # The first panel sits beside it at x=3; every panel after that spans the
    # full width from x=1. So if the selector is taller than the first panel,
    # the second panel starts inside the selector's columns and gridster
    # resolves the collision by shoving the selector to the bottom of the
    # screen. That is what happened on five of the seven dashboards, and the
    # two that were fine -- Network and Storage -- were fine only because
    # their first panel happened to be 9 rows high already.
    prov["gridsterCoords"] = {"w": 2, "x": 1, "h": panels[0][2]["h"], "y": 1}
    prov["config"]["viewDefinitionId"] = V["vSAN_Clusters"]
    # The template's provider carries a pinned root that came out of the
    # browser session the dashboard was exported from:
    #
    #   {"resourceId": "resource:id:0_::_", "resourceName": "VCF World",
    #    "resourceKindId": "002010VcfAdapterVCFWorld",
    #    "id": "Ext.vcops.chrome.model.Resource-592"}
    #
    # `id` is an ExtJS client-side model instance reference. It identifies a
    # JavaScript object in one page load, nothing more, and it is meaningless
    # on any other instance or even on a later visit to the same one. Shipping
    # it asks Operations to resolve a reference that cannot resolve, and the
    # observed symptom was a cluster selector scoped to the wrong thing.
    #
    # The rest of the blob is kept: resourceKindId is a kind key rather than
    # an instance id, and every VCF Operations instance has exactly one VCF
    # World at the root of its hierarchy, so pinning there is portable in a
    # way the ExtJS handle is not.
    # Re-root the selector on vSPHERE World, not VCF World.
    #
    # The template was exported from a VCF deployment and pinned the selector
    # to "VCF World", an object owned by VcfAdapter. On an Operations instance
    # that is not VCF, or where the VCF adapter is installed but unconfigured,
    # that object does not exist, the selector's root fails to resolve, and
    # every panel reports it cannot render for the specified object. It worked
    # on the build instance for the one reason that does not generalise: that
    # instance is VCF.
    #
    # vSphere World belongs to the VMWARE adapter, so it exists on every
    # instance collecting from a vCenter, which this pack already requires.
    #
    # The id encoding is "002" + the adapter kind's length as three digits +
    # the adapter kind + the resource kind, confirmed against three real
    # exports including one whose resource kind contains a space:
    #   002006VMWAREHostSystem
    #   002010VcfAdapterVCFWorld
    #   002028VirtualAndPhysicalSANAdaptervSAN World
    ROOT_ADAPTER, ROOT_KIND = "VMWARE", "vSphere World"
    root_kind_id = f"002{len(ROOT_ADAPTER):03d}{ROOT_ADAPTER}{ROOT_KIND}"
    res = prov["config"].get("resource")
    if isinstance(res, dict):
        # `id` was an ExtJS client-side model handle from the exporting
        # browser session and means nothing anywhere else.
        res.pop("id", None)
        res["resourceKindId"] = root_kind_id
        res["resourceName"] = ROOT_KIND
        prov["config"]["resource"] = res
    # The document-level entries table is what resolves the resourceId
    # sentinel, by kind and name rather than by instance id, so it has to name
    # the same object.
    for entry in (doc.get("entries") or {}).get("resource") or []:
        if entry.get("resourceKindKey") == "VCFWorld":
            entry["adapterKindKey"] = ROOT_ADAPTER
            entry["resourceKindKey"] = ROOT_KIND
            entry["name"] = ROOT_KIND

    out = [prov]
    for title, key, coords in panels:
        out.append(receiver(recv_tpl, title, V[key], coords, tab))

    if text_tpl is not None:
        t = copy.deepcopy(text_tpl)
        destate(t)
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

    # Geometry guard. The collision above was invisible in the generated JSON
    # and only showed up as a misplaced widget on screen, which is exactly the
    # kind of defect that comes back. Fail the build instead.
    boxes = [(w["config"].get("title") or w["type"], w["gridsterCoords"])
             for w in out if w.get("gridsterCoords")]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ta, a), (tb, b) = boxes[i], boxes[j]
            if (a["x"] <= b["x"] + b["w"] - 1 and b["x"] <= a["x"] + a["w"] - 1
                    and a["y"] <= b["y"] + b["h"] - 1
                    and b["y"] <= a["y"] + a["h"] - 1):
                raise SystemExit(
                    f"{name}: {ta!r} overlaps {tb!r} -- {a} vs {b}")

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
