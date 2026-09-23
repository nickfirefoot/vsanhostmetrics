#!/usr/bin/env python3
"""Generate the rapid dashboards as UI-importable zips.

    python3 tools/build_dashboard.py

Writes dist/dashboards/<name>.zip, each importable through
Dashboards -> Import in the VCF Operations UI. The content import API rejects
this format (INVALID_FILE_FORMAT, tested with an untouched UI export), so the
UI is the only route; see docs/DASHBOARD-FORMAT.md.

Every metric key emitted here is validated against app/perfsvc_model.py before
the file is written. A typo'd key does not error in Operations -- it renders an
empty panel -- so it has to be caught at build time.
"""
import json
import os
import sys
import uuid
import zipfile

sys.path.insert(0, "app")
import metric_labels  # noqa: E402
import perfsvc_model  # noqa: E402

ADAPTER = "VsanHostMetrics"
GREEN, AMBER, RED = "#67CA16", "#FFDB24", "#FF4D2E"


def kind_id(resource_kind, adapter=ADAPTER):
    """002 + 3-digit len(adapterKind) + adapterKind + resourceKind.

    Decoded from observed samples: 002006VMWAREHostSystem is VMWARE(6) plus
    HostSystem. See docs/DASHBOARD-FORMAT.md.
    """
    return f"002{len(adapter):03d}{adapter}{resource_kind}"


def validate(resource_kind, metric):
    for spec in perfsvc_model.ENTITIES.values():
        if spec["kind"] == resource_kind:
            if metric not in spec["metrics"]:
                raise SystemExit(f"FATAL: {metric!r} is not a metric of {resource_kind}")
            return
    raise SystemExit(f"FATAL: unknown resource kind {resource_kind!r}")


def heatmap(dash_id, title, resource_kind, metric, x, y, w=4, h=5,
            thresholds=(0, 1, 5), group_adapter="VMWARE",
            group_kind="HostSystem"):
    validate(resource_kind, metric)
    wid = str(uuid.uuid4())
    return {
        "tabId": dash_id, "id": wid, "type": "Heatmap", "title": title,
        "collapsed": False, "state": "", "height": 0,
        "gridsterCoords": {"x": x, "y": y, "w": w, "h": h},
        "config": {
            "configs": [{
                "colorBy": {"value": metric},
                "sizeBy": {"value": ""},
                "attributeKind": {"value": kind_id(resource_kind)},
                "groupBy": {
                    "resourceKind": group_kind, "adapterKind": group_adapter,
                    "typeId": "resourceKind:id:0_::_",
                    "id": f"004null{kind_id(group_kind, group_adapter)}",
                    "text": group_kind, "type": "resourceKind",
                    "parentText": "vCenter", "parentId": group_adapter,
                },
                "color": {"thresholds": {"values": list(thresholds),
                                         "colors": [GREEN, AMBER, RED]}},
                "focusOnGroups": True, "relationalGrouping": False,
                "solidColoring": False, "filterMode": "tagPicker",
                "nameLocalized": "name", "name": "name", "nameOrig": "name",
                "thenBy": None, "mode": {"mode": False}, "resourceKind": None,
                "id": f"extModel-{wid[:8]}",
            }],
            "refreshInterval": 300, "widgetId": wid, "title": title,
            "description": "", "mode": "resource", "depth": 10,
            "refreshContent": {"refreshContent": True},
            "relationshipMode": {"relationshipMode": [1, -1, 0]},
            "selfProvider": {"selfProvider": True}, "viewDetails": "", "value": 0,
        },
    }


def text(dash_id, title, body_html, x, y, w=12, h=4, url=""):
    wid = str(uuid.uuid4())
    return {
        "tabId": dash_id, "id": wid, "type": "TextDisplay", "title": title,
        "collapsed": False, "state": "", "height": 0,
        "gridsterCoords": {"x": x, "y": y, "w": w, "h": h},
        "config": {
            "description": body_html, "locationUrl": url, "locationFile": "",
            "viewModeHTML": True, "refreshInterval": 300, "widgetId": wid,
            "title": title, "refreshContent": {"refreshContent": False},
            "viewDetails": "",
        },
    }


def dashboard(name, description, widgets_fn):
    did = str(uuid.uuid4())
    return {
        "entries": {},
        "dashboards": [{
            "id": did, "name": name, "description": description,
            "shared": True, "hidden": False, "creationTime": 0,
            "autoswitchEnabled": False, "importAttempts": 0,
            "columnProportion": "1", "importComplete": True, "columnCount": 0,
            "gridsterMaxColumns": 12, "rank": 0, "disabled": False,
            "locked": False, "homeTab": False, "editAllowed": True,
            "states": [], "dashboardNavigations": {},
            "widgets": widgets_fn(did),
        }],
        "uuid": str(uuid.uuid4()),
    }


NETWORK_HELP = """
<h3>Network rapid &mdash; is a NIC or link bad right now?</h3>
<p>This screen catches <b>grey-state failure</b>: partial degradation that
leaves everything nominally up. A NIC dropping 0.1% of frames still moves
traffic at line rate, so throughput and latency look green through the exact
fault this exists to find. <b>Non-zero is the catch.</b> It is not a
root-cause tool.</p>
<p><b>Drop and pause metrics are per-mille, not percent.</b> A value of
<code>1</code> means 0.1%, which is already Broadcom's warning threshold for
out-of-order packets; <code>10</code> is critical. Do not read them as packet
counts.</p>
<p><b>RX missed errors</b> means the NIC ring buffer had no free descriptor and
the packet was dropped before the driver saw it &mdash; distinct from
<i>RX dropped</i> (discarded higher up) and <i>RX errors</i> (arrived damaged).
It is the clearest signal that a NIC is being overrun.</p>
<p><b>Pause / PFC</b> separate a congested fabric from a failing NIC: the host
asking the switch to slow down is a different problem from the host losing
frames.</p>
<p><b>Blind spot:</b> there are no disk media-error counters anywhere in the
vSAN Performance Service, and no NIC ring-buffer <i>utilisation</i> &mdash;
only overflow after the fact. A green screen here does not mean the hardware is
healthy.</p>
<p><a href="https://github.com/nickfirefoot/vsanhostmetrics">Documentation and
full metric reference</a></p>
"""


def network_rapid():
    def widgets(did):
        w = [text(did, "How to read this", NETWORK_HELP, 1, 1, w=12, h=5)]
        panels = [
            ("pNIC RX missed errors (ring full)", "VsanPnic", "rxMissErr", (0, 1, 10)),
            ("pNIC RX CRC errors",                "VsanPnic", "rxCrcErr",  (0, 1, 10)),
            ("pNIC TX carrier errors",            "VsanPnic", "txCarErr",  (0, 1, 10)),
            ("pNIC RX errors",                    "VsanPnic", "rxErr",     (0, 1, 10)),
            ("vSwitch port RX drops (per-mille)", "VsanPnic", "portRxDrops", (0, 1, 10)),
            ("vSwitch port TX drops (per-mille)", "VsanPnic", "portTxDrops", (0, 1, 10)),
            ("802.3x pause rate",                 "VsanPnic", "pauseCount", (0, 1, 10)),
            ("PFC count",                         "VsanPnic", "pfcCount",   (0, 1, 10)),
            ("TCP retransmit rate",               "VsanHostNet", "tcpTxRexmitRate", (0, 5, 10)),
            ("TCP RX error rate",                 "VsanHostNet", "tcpRxErrRate",    (0, 1, 10)),
            ("RX packet loss rate",               "VsanPnic", "rxPacketsLossRate", (0, 1, 10)),
            ("TX packet loss rate",               "VsanPnic", "txPacketsLossRate", (0, 1, 10)),
        ]
        y = 6
        for i, (title, kind, metric, thr) in enumerate(panels):
            x = 1 + (i % 3) * 4
            if i and i % 3 == 0:
                y += 5
            w.append(heatmap(did, title, kind, metric, x, y, thresholds=thr))
        return w
    return dashboard("vSAN Network Rapid",
                     "Grey-state detection for vSAN networking. Non-zero is the catch.",
                     widgets)


def write(doc, name):
    os.makedirs("dist/dashboards", exist_ok=True)
    out = f"dist/dashboards/{name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dashboard/dashboard.json", json.dumps(doc, indent=1))
    db = doc["dashboards"][0]
    print(f"  {out}")
    print(f"    {len(db['widgets'])} widgets "
          f"({sum(1 for w in db['widgets'] if w['type']=='Scoreboard')} scoreboards, "
          f"{sum(1 for w in db['widgets'] if w['type']=='TextDisplay')} text)")
    for w in db["widgets"]:
        if w["type"] == "Scoreboard":
            for e in w["config"]["metric"]["resourceKindMetrics"]:
                print(f"      {e['metricKey']:20} {e['resourceKindName'][:36]}")


# ---------------------------------------------------------------------------
# Scoreboard — the widget Broadcom's own vSAN dashboards use for this job.
# Pattern taken from docs/assets/dashboard.broadcom-vsan-esa.json.
#
# Note resourceKindId is the literal placeholder "resourceKind:id:0_::_", NOT
# the 002<len><adapterKind><resourceKind> encoding used by MetricChart and
# Heatmap groupBy. The kind is identified by resourceKindName instead.


def scoreboard(dash_id, title, resource_kind_name, metrics, x, y, w=4, h=5,
               self_provider=True):
    """metrics: list of (metricKey, label, yellow, orange, red)."""
    wid = str(uuid.uuid4())
    entries = []
    for i, (key, label, yb, ob, rb) in enumerate(metrics):
        entries.append({
            "metricKey": key, "metricName": label, "label": label,
            "resourceKindName": resource_kind_name,
            "resourceKindId": "resourceKind:id:0_::_",
            "yellowBound": yb, "orangeBound": ob, "redBound": rb,
            "colorMethod": 0, "handleOldColoring": False,
            "isStringMetric": False, "link": "", "unit": "",
            "metricUnitId": None, "id": f"extModel-{wid[:6]}-{i}",
        })
    return {
        "tabId": dash_id, "id": wid, "type": "Scoreboard", "title": title,
        "collapsed": False, "state": "", "height": 0,
        "gridsterCoords": {"x": x, "y": y, "w": w, "h": h},
        "config": {
            "title": title, "widgetId": wid, "refreshInterval": 300,
            "metric": {"mode": "resourceKind", "resourceMetrics": [],
                       "resourceKindMetrics": entries},
            "selfProvider": {"selfProvider": self_provider},
            "mode": {"layoutMode": "fixedView"},
            "maxCellCount": 100, "oldMetricValues": False,
            "relationshipMode": {"relationshipMode": 0},
            "valueSize": 24, "labelSize": 16, "roundDecimals": 0,
            "boxHeight": None, "visualTheme": 8, "depth": 1,
            "showResourceName": {"showResourceName": True},
            "showMetricName": {"showMetricName": True},
            "showMetricUnit": {"showMetricUnit": True},
            "showDT": {"showDT": False},
            "refreshContent": {"refreshContent": False},
            "customFilter": {"filter": [], "excludedResources": None,
                             "includedResources": None},
            "resource": [], "resInteractionMode": None,
        },
    }


def kind_label(resource_kind):
    """Human name Operations shows for one of our resource kinds."""
    for spec in perfsvc_model.ENTITIES.values():
        if spec["kind"] == resource_kind:
            return spec["label"]
    raise SystemExit(f"unknown kind {resource_kind}")


def probe():
    """Three widgets only. Cheap to import, proves or disproves the bindings."""
    def widgets(did):
        for m in ("rxMissErr", "rxCrcErr", "portRxDrops"):
            validate("VsanPnic", m)
        return [
            text(did, "Probe", "<p>If the panel below shows values per vmnic, "
                               "the Scoreboard binding is correct.</p>", 1, 1, w=12, h=3),
            scoreboard(did, "pNIC errors (probe)", kind_label("VsanPnic"), [
                ("rxMissErr",   "RX missed errors (ring full)", 1, 5, 10),
                ("rxCrcErr",    "RX CRC errors",                1, 5, 10),
                ("portRxDrops", "vSwitch RX drops (per-mille)", 1, 5, 10),
            ], 1, 4, w=6, h=6),
            scoreboard(did, "Host network (probe)", kind_label("VsanHostNet"), [
                ("tcpTxRexmitRate", "TCP retransmit rate", 1, 5, 10),
                ("tcpRxErrRate",    "TCP RX error rate",   1, 5, 10),
            ], 7, 4, w=6, h=6),
        ]
    return dashboard("vSAN Rapid — binding probe",
                     "Three widgets to verify Scoreboard bindings. Safe to delete.",
                     widgets)


if __name__ == "__main__":
    write(probe(), "vsan-rapid-probe")
