#!/usr/bin/env python3
"""Generate Operations View definitions by cloning a confirmed-working export.

    python3 tools/build_view.py            # writes to ~/ops-content/out/

Views are referenced by GUID and there is no API to create them
(`/suite-api/api/views` 404s), so they are authored in the UI and exported as
XML. This clones `docs/assets/view.vsan-pnic-errors.xml` -- built by hand,
imported, and confirmed rendering -- and swaps only the subject kind, the
columns and the identifiers. Everything else stays byte-identical to what
Operations itself wrote, including the fields nobody here has decoded.

The same reasoning as `clone_dashboard.py`: this format is not reliably
reconstructable from notes, but it is reliably clonable.

Transformations observed in the working export: `MAX` on rate/percentage
columns, `CURRENT` on cumulative counters. `MIN` is used here for the two
socket-buffer minimums, where low is bad and the worst case is the lowest
value -- **that enum value is unverified**, see the note in the output.
"""
import os
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile

TEMPLATE = "docs/assets/view.vsan-pnic-errors.xml"
OUTDIR = os.path.expanduser("~/ops-content/out")

# (metricKey, displayName, preferredUnitId, transformation)
# An empty unit lets Operations use the unit the adapter declares.
VIEWS = [
    ("vSAN Host TCP Health", "VsanTcpIp", [
        ("tcpTxRexmitRate",      "TCP Retransmit",   "percent", "MAX"),
        ("tcpRxErrRate",         "TCP RX Error",     "percent", "MAX"),
        ("tcpRcvdupackRate",     "Duplicate ACK",    "percent", "MAX"),
        ("tcpRcvoopackRate",     "Out Of Order",     "percent", "MAX"),
        ("tcpSackRcvBlocksRate", "SACK Received",    "percent", "MAX"),
        ("tcpTimeoutDropRate",   "Timeout Drop",     "percent", "MAX"),
        ("tcpSndZeroWin",        "Zero Window",      "",        "CURRENT"),
        ("tcpErrs",              "TCP Errors",       "",        "CURRENT"),
    ]),
    ("vSAN RDT Transport", "VsanRdtLatency", [
        ("avgLatency",    "RDT Average Latency",   "", "MAX"),
        ("maxLatency",    "RDT Max Latency",       "", "MAX"),
        ("txQLatAvg",     "Queue Latency Average", "", "MAX"),
        ("txQLatMax",     "Queue Latency Max",     "", "MAX"),
        ("txSbSpaceMin",  "TX Buffer Free",        "", "MIN"),
        ("rxSbSpaceMin",  "RX Buffer Free",        "", "MIN"),
        ("kaReset",       "Keepalive Reset",       "", "CURRENT"),
        ("numReadyDelay", "Ready Delay",           "", "CURRENT"),
    ]),
    ("vSAN ESA Disks", "VsanEsaDiskLayer", [
        ("avgLatReadCapacity",  "Read Latency",           "", "MAX"),
        ("avgLatWriteCapacity", "Write Latency",          "", "MAX"),
        ("avgLatWritePerf",     "Perf Tier Write Latency", "", "MAX"),
        ("iopsReadCapacity",    "Read IOPS",              "", "MAX"),
        ("iopsWriteCapacity",   "Write IOPS",             "", "MAX"),
    ]),
    ("vSAN VM Storage", "VsanVscsi", [
        ("latencyRead",  "Read Latency",  "", "MAX"),
        ("latencyWrite", "Write Latency", "", "MAX"),
        ("iopsRead",     "Read IOPS",     "", "MAX"),
        ("iopsWrite",    "Write IOPS",    "", "MAX"),
    ]),
]

ADAPTER = "VsanHostMetrics"


def make_item(key, label, unit, transform, kind):
    """One column, built as elements so the result cannot be malformed."""
    item = ET.Element("Item")
    val = ET.SubElement(item, "Value")
    def prop(name, value):
        ET.SubElement(val, "Property", {"name": name, "value": value})
    prop("objectType", "RESOURCE")
    prop("attributeKey", key)
    prop("preferredUnitId", unit)
    prop("isStringAttribute", "false")
    prop("adapterKind", ADAPTER)
    prop("resourceKind", kind)
    prop("rollUpType", "NONE")
    prop("rollUpCount", "0")
    tp = ET.SubElement(val, "Property", {"name": "transformations"})
    lst = ET.SubElement(tp, "List")
    ET.SubElement(lst, "Item", {"value": transform})
    prop("sortCriteria", "false")
    prop("isProperty", "false")
    prop("displayName", label)
    prop("addTimestampAsColumn", "false")
    prop("isShowRelativeTimestamp", "false")
    return item


def build(template, title, kind, columns, seed):
    """Clone the working export, swapping only identity, subject and columns.

    Parsed and rewritten rather than string-substituted: an earlier regex
    version matched the `</List>` belonging to a column's `transformations`
    instead of the outer `attributeInfos` list, and produced malformed XML.
    """
    root = ET.fromstring(template)
    vd = root.find(".//ViewDef")
    vd.set("id", str(uuid.uuid4()))
    vd.find("Title").text = title
    for st in vd.findall("SubjectType"):
        st.set("adapterKind", ADAPTER)
        st.set("resourceKind", kind)
    # control ids must not collide between views
    for el in root.iter():
        cid = el.get("id")
        if cid and "_id_" in cid:
            el.set("id", re.sub(r"_id_\d+", f"_id_{seed}", cid))
            seed += 1
    # swap the column list, leaving every other control untouched
    replaced = False
    for ctrl in root.iter("Control"):
        if ctrl.get("type") != "attributes-selector":
            continue
        for prop in ctrl.findall("Property"):
            if prop.get("name") != "attributeInfos":
                continue
            lst = prop.find("List")
            for child in list(lst):
                lst.remove(child)
            for col in columns:
                lst.append(make_item(*col, kind))
            replaced = True
    if not replaced:
        raise SystemExit(f"{title}: could not find attributeInfos to replace")
    ET.indent(root, space="    ")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            + ET.tostring(root, encoding="unicode"))


def main():
    template = open(TEMPLATE).read()
    # the archived template is sanitised; views carry no hostnames, but assert
    assert "example.com" not in template and "denick" not in template, \
        "template carries a hostname -- check before shipping"
    os.makedirs(OUTDIR, exist_ok=True)
    for i, (title, kind, columns) in enumerate(VIEWS):
        xml = build(template, title, kind, columns, seed=700 + i * 20)
        name = title.replace(" ", "_")
        path = os.path.join(OUTDIR, f"{name}.xml")
        open(path, "w").write(xml)
        with zipfile.ZipFile(os.path.join(OUTDIR, f"{name}.zip"), "w",
                             zipfile.ZIP_DEFLATED) as z:
            z.writestr("content.xml", xml)
        print(f"  {path}")
        print(f"    subject {kind}, {len(columns)} columns: "
              + ", ".join(c[0] for c in columns))


if __name__ == "__main__":
    main()
