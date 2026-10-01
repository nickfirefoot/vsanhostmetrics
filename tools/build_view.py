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
    # Labels follow three rules learned from reviewing the first draft:
    #   1. a CUMULATIVE counter says "(Total)", so nobody thresholds a number
    #      that only ever rises
    #   2. an INVERTED metric says "Low Is Bad", because free-space metrics
    #      read backwards against every other column on the screen
    #   3. where two LAYERS measure the same thing, each says which layer --
    #      "Read Latency" is ambiguous once a physical-layer table sits below
    #      a vSAN-layer one
    ("vSAN Host TCP Health", "VsanTcpIp", [
        ("tcpTxRexmitRate",      "TCP Retransmit",        "percent", "MAX"),
        ("tcpRxErrRate",         "TCP RX Error",          "percent", "MAX"),
        ("tcpRcvdupackRate",     "Duplicate ACK",         "percent", "MAX"),
        ("tcpRcvoopackRate",     "Out Of Order",          "percent", "MAX"),
        # direction is the whole point: receiving SACK blocks means the PEER
        # is missing data we sent, i.e. loss on our outbound path
        ("tcpSackRcvBlocksRate", "SACK Rcvd (Peer Lost)", "percent", "MAX"),
        ("tcpTimeoutDropRate",   "Timeout Drop",          "percent", "MAX"),
        ("tcpSndZeroWin",        "Zero Window (Total)",   "",        "CURRENT"),
        ("tcpErrs",              "TCP Error Count (Total)", "",      "CURRENT"),
    ]),
    ("vSAN RDT Transport", "VsanRdtLatency", [
        ("avgLatency",    "RDT Latency Avg",              "", "MAX"),
        ("maxLatency",    "RDT Latency Max",              "", "MAX"),
        ("txQLatAvg",     "TX Queue Latency Avg",         "", "MAX"),
        ("txQLatMax",     "TX Queue Latency Max",         "", "MAX"),
        # free space remaining: the only inverted columns in the pack
        ("txSbSpaceMin",  "TX Buffer Free (Low Is Bad)",  "", "MIN"),
        ("rxSbSpaceMin",  "RX Buffer Free (Low Is Bad)",  "", "MIN"),
        ("kaReset",       "Keepalive Reset (Total)",      "", "CURRENT"),
        ("numReadyDelay", "Ready Delay (Total)",          "", "CURRENT"),
    ]),
    ("vSAN ESA Disks", "VsanEsaDiskLayer", [
        ("avgLatReadCapacity",  "vSAN Read Latency",       "", "MAX"),
        ("avgLatWriteCapacity", "vSAN Write Latency",      "", "MAX"),
        ("avgLatWritePerf",     "Perf Tier Write Latency", "", "MAX"),
        ("iopsReadCapacity",    "Read IOPS",               "", "MAX"),
        ("iopsWriteCapacity",   "Write IOPS",              "", "MAX"),
    ]),
    # The layer that says WHY a disk is slow. DAVG is the device, KAVG the
    # VMkernel queue, GAVG what the guest sees (DAVG + KAVG). High DAVG with
    # flat KAVG is a slow device; high KAVG is contention. Lives on a separate
    # resource kind, so it cannot be a column on the view above.
    ("vSAN ESA Disk Physical Layer", "VsanEsaDiskScsifw", [
        ("latencyDevRead",  "Physical Read Latency",   "", "MAX"),
        ("latencyDevWrite", "Physical Write Latency",  "", "MAX"),
        ("latencyDevDAvg",  "Device (DAVG)",           "", "MAX"),
        ("latencyDevKAvg",  "Kernel Queue (KAVG)",     "", "MAX"),
        ("latencyDevGAvg",  "Guest Total (GAVG)",      "", "MAX"),
    ]),
    ("vSAN VM Storage", "VsanVscsi", [
        ("latencyRead",  "vSAN Read Latency",  "", "MAX"),
        ("latencyWrite", "vSAN Write Latency", "", "MAX"),
        ("iopsRead",     "Read IOPS",          "", "MAX"),
        ("iopsWrite",    "Write IOPS",         "", "MAX"),
    ]),
]

ADAPTER = "VsanHostMetrics"

# Fixed namespace so view GUIDs are reproducible across machines and runs.
NAMESPACE = uuid.UUID("6f3c9b1e-4a2d-5e8f-9c1b-2d7a4e6f8b03")


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
    # Deterministic: the same title always yields the same GUID, so
    # regenerating after a label fix UPDATES the view in place rather than
    # creating a duplicate, and any dashboard referencing it keeps resolving.
    # uuid4 here would mean every edit orphaned the previous import.
    vd.set("id", str(uuid.uuid5(NAMESPACE, title)))
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
