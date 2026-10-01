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
# The hand-built pNIC view keeps its original GUID so a regenerated
# version UPDATES the one already imported rather than duplicating it.
PINNED = {"vSAN pNIC Errors": "09f4cb2e-f52c-412a-826d-ee04a3d07d0f"}
OUTDIR = os.path.expanduser("~/ops-content/out")

# (metricKey, displayName, preferredUnitId, transformation)
# An empty unit lets Operations use the unit the adapter declares.
VIEWS = [
    # Every metric from the hand-built dashboard is carried here. Earlier
    # drafts dropped twenty of them on my judgement without saying so; the
    # only grouping constraint a view actually imposes is that it has ONE
    # subject kind, so a panel mixing kinds becomes two views, nothing is lost.
    #
    # Labels are Broadcom's official names, trimmed where they repeat the
    # view's subject. Two markers are added where the official name omits
    # something load-bearing:
    #   (Total)       cumulative since boot -- do not threshold it
    #   (Low Is Bad)  free space remaining -- reads backwards from every
    #                 other column
    ("vSAN pNIC Errors", "VsanPnic", [
        # rates: is it happening now
        ("rxMissErr",   "pNIC RX Missed Error",            "percent", "MAX"),
        ("rxCrcErr",    "pNIC RX CRC Error",               "percent", "MAX"),
        ("rxErr",       "pNIC RX Generic Error",           "percent", "MAX"),
        ("rxFifoErr",   "pNIC RX FIFO Error",              "percent", "MAX"),
        ("rxOvErr",     "pNIC RX Buffer Overflow Error",   "percent", "MAX"),
        ("txCarErr",    "pNIC TX Carrier Error",           "percent", "MAX"),
        ("txErr",       "pNIC TX Generic Error",           "percent", "MAX"),
        ("portRxDrops", "vSwitch Port Inbound Drop Rate",  "percent", "MAX"),
        ("portTxDrops", "vSwitch Port Outbound Drop Rate", "percent", "MAX"),
        ("pauseCount",  "pNIC 802.3x Pause Rate",          "percent", "MAX"),
        # IO chain drops: kept from the original dashboard
        ("ioChainDrops",   "IO Chain Drops",               "", "MAX"),
        ("ioChainRxdrops", "IO Chain RX Drops",            "", "MAX"),
        ("ioChainTxdrops", "IO Chain TX Drops",            "", "MAX"),
        # lifetime counters: has this NIC ever been bad
        ("rxMissErrRaw", "RX Missed Count (Total)",        "", "CURRENT"),
        ("rxCrcErrRaw",  "RX CRC Count (Total)",           "", "CURRENT"),
        ("pfcCountRaw",  "PFC Count (Total)",              "", "CURRENT"),
        ("portTxpkts",   "Port TX Packets",                "", "CURRENT"),
    ]),
    ("vSAN Host Network", "VsanHostNet", [
        ("rxPacketsLossRate", "Network Inbound Packet Discard Rate",  "percent", "MAX"),
        ("txPacketsLossRate", "Network Outbound Packet Discard Rate", "percent", "MAX"),
        ("portRxDrops",       "Inbound Drop Rate of vSAN Host Port",  "percent", "MAX"),
        ("portTxDrops",       "Outbound Drop Rate of vSAN Host Port", "percent", "MAX"),
        ("rxThroughput",      "Network Inbound Throughput",           "", "MAX"),
        ("txThroughput",      "Network Outbound Throughput",          "", "MAX"),
        ("rxPackets",         "Network Inbound Packets Per Second",   "", "MAX"),
        ("txPackets",         "Network Outbound Packets Per Second",  "", "MAX"),
    ]),
    ("vSAN Host TCP Health", "VsanTcpIp", [
        ("tcpTxRexmitRate",       "TCP TX Retransmit Rate",             "percent", "MAX"),
        ("tcpRxErrRate",          "TCP RX Error Rate",                  "percent", "MAX"),
        ("tcpRcvdupackRate",      "Received Duplicate Acknowledge Rate", "percent", "MAX"),
        ("tcpRcvduppackRate",     "Received Duplicate Packets Rate",    "percent", "MAX"),
        ("tcpRcvoopackRate",      "Received Out-of-order Packets Rate", "percent", "MAX"),
        ("tcpSackRcvBlocksRate",  "SACK Received Blocks Rate",          "percent", "MAX"),
        ("tcpSackSendBlocksRate", "SACK Send Blocks Rate",              "percent", "MAX"),
        ("tcpSackRexmitsRate",    "SACK Rexmits Rate",                  "percent", "MAX"),
        ("tcpTimeoutDropRate",    "Timeout Drop Rate",                  "percent", "MAX"),
        # reads 7-9% on a healthy cluster -- restored because it was on the
        # original dashboard, but do not colour it until that is understood
        ("tcpHalfopenDropRate",   "Half Open Drop Rate",                "percent", "MAX"),
        ("tcpSndZeroWin",         "TCP Send Zero Window (Total)",       "",        "CURRENT"),
        ("tcpErrs",               "TCP Errors (Total)",                 "",        "CURRENT"),
    ]),
    ("vSAN RDT Transport Per Host", "VsanRdtLatency", [
        ("avgLatency",    "RDT Network Host Average Latency",           "", "MAX"),
        ("maxLatency",    "RDT Network Max Latency",                    "", "MAX"),
        ("minLatency",    "RDT Network Min Latency",                    "", "MIN"),
        ("txQLatAvg",     "RDT Average Outbound Queueing Latency",      "", "MAX"),
        ("txQLatMax",     "RDT Max Outbound Queueing Latency",          "", "MAX"),
        ("txSbSpaceMin",  "RDT Socket Min Outbound Bytes (Low Is Bad)", "", "MIN"),
        ("rxSbSpaceMin",  "RDT Socket Min Inbound Bytes (Low Is Bad)",  "", "MIN"),
        ("rxSbSpaceMax",  "RDT Socket Max Inbound Bytes",               "", "MAX"),
        ("kaReset",       "Keepalive Reset (Total)",                    "", "CURRENT"),
        ("numReadyDelay", "Num Ready Delay (Total)",                    "", "CURRENT"),
    ]),
    ("vSAN ESA Disks", "VsanEsaDiskLayer", [
        ("avgLatReadCapacity",  "vSAN Layer Average Read Latency",   "", "MAX"),
        ("avgLatWriteCapacity", "vSAN Layer Average Write Latency",  "", "MAX"),
        ("avgLatWritePerf",     "Perf Tier Average Write Latency",   "", "MAX"),
        ("iopsReadCapacity",    "vSAN Layer Read IOPS",              "", "MAX"),
        ("iopsWriteCapacity",   "vSAN Layer Write IOPS",             "", "MAX"),
    ]),
    ("vSAN ESA Disk Physical Layer", "VsanEsaDiskScsifw", [
        ("latencyDevRead",  "Physical/Firmware Layer Read Latency",     "", "MAX"),
        ("latencyDevWrite", "Physical/Firmware Layer Write Latency",    "", "MAX"),
        ("latencyDevDAvg",  "Physical/Firmware Device Average (DAVG)",  "", "MAX"),
        ("latencyDevKAvg",  "Physical/Firmware Kernel Average (KAVG)",  "", "MAX"),
        ("latencyDevGAvg",  "Physical/Firmware Guest Average (GAVG)",   "", "MAX"),
    ]),
    ("vSAN VM Storage", "VsanVscsi", [
        ("latencyRead",  "vSAN Layer Read Latency",  "", "MAX"),
        ("latencyWrite", "vSAN Layer Write Latency", "", "MAX"),
        ("iopsRead",     "Read IOPS",                "", "MAX"),
        ("iopsWrite",    "Write IOPS",               "", "MAX"),
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
    vd.set("id", PINNED.get(title) or str(uuid.uuid5(NAMESPACE, title)))
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
