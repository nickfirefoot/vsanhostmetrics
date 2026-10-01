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
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
import sys

sys.path.insert(0, "app")
import perfsvc_model            # noqa: E402
import metric_labels            # noqa: E402

SCHEMA = json.load(open("docs/assets/perfsvc_schema.json"))
ENT_FOR = {sp["kind"]: e for e, sp in perfsvc_model.ENTITIES.items()}

TEMPLATE = "docs/assets/view.vsan-pnic-errors.xml"
# The hand-built pNIC view keeps its original GUID so a regenerated
# version UPDATES the one already imported rather than duplicating it.
PINNED = {
    # already imported and referenced by a dashboard -- regenerating must
    # UPDATE these, not create a second copy under a new identity
    "vSAN pNIC Errors": "09f4cb2e-f52c-412a-826d-ee04a3d07d0f",
    # referenced as c51f5531 by "RDT latencies" on Rapid vSAN Network v4.
    # The title gained "Per Host" after that dashboard was built, which would
    # otherwise have moved the GUID and orphaned the widget.
    "vSAN RDT Transport Per Host": "c51f5531-ccea-543d-9a73-0e0d5e359d1a",
}
OUTDIR = os.path.expanduser("~/ops-content/out")

# (metricKey, displayName, preferredUnitId, transformation)
# An empty unit lets Operations use the unit the adapter declares.
# Columns are (metricKey, preferredUnitId, transformation). The LABEL is
# derived, not hand-written: Broadcom's official name from the Performance
# Service schema verbatim where one exists, the pack's own derived label
# otherwise (17 of these metrics have no official name at all). Two suffixes
# are appended because the official names omit them and their absence misleads.
CUMULATIVE = {"rxMissErrRaw", "rxCrcErrRaw", "pfcCountRaw", "portTxpkts",
              "tcpSndZeroWin", "tcpErrs", "kaReset", "numReadyDelay"}
INVERTED = {"txSbSpaceMin", "rxSbSpaceMin"}

VIEWS = [
    # The cluster selector every dashboard is driven from. Its subject is a
    # vCenter object, not one of ours, so it carries its own adapter kind --
    # shipping it means the dashboards do not depend on a view the customer
    # happens to have built.
    ("vSAN Clusters", "ClusterComputeResource", [
        ("Configuration|Name", "", "CURRENT"),
    ], "VMWARE"),
    ("vSAN Cluster Capacity", "VsanClusterCapacity", [
        ("free", "", "CURRENT"), ("used", "", "CURRENT"), ("total", "", "CURRENT"),
        ("dedupRatio", "", "CURRENT"), ("savedByDedup", "", "CURRENT"),
    ]),
    ("vSAN Cluster DOM Client", "VsanClusterDomclient", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("congestion", "", "MAX"), ("readCongestion", "", "MAX"),
        ("writeCongestion", "", "MAX"), ("unmapCongestion", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"), ("oio", "", "MAX"),
        ("throughputRead", "", "MAX"), ("throughputWrite", "", "MAX"),
    ]),
    ("vSAN Cluster DOM Component Manager", "VsanClusterDomcompmgr", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("congestion", "", "MAX"), ("oio", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
    ]),
    ("vSAN Cluster Resync", "VsanClusterDomcompmgr", [
        ("iopsResyncRead", "", "MAX"), ("tputResyncRead", "", "MAX"),
        ("latAvgResyncRead", "", "MAX"), ("iopsRecWrite", "", "MAX"),
        ("throughputRecWrite", "", "MAX"), ("latencyAvgRecWrite", "", "MAX"),
    ]),
    ("vSAN Cluster RDT", "VsanClusterRdtLatency", [
        ("avgLatency", "", "MAX"), ("maxLatency", "", "MAX"), ("minLatency", "", "MIN"),
        ("txQLatAvg", "", "MAX"), ("txSbSpaceMin", "", "MIN"), ("rxSbSpaceMin", "", "MIN"),
        ("kaReset", "", "CURRENT"), ("numReadyDelay", "", "CURRENT"),
    ]),
    ("vSAN Host DOM", "VsanHostDomclient", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("congestion", "", "MAX"), ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("oio", "", "MAX"),
    ]),
    ("vSAN pNIC Errors", "VsanPnic", [
        ("rxMissErr",      "percent", "MAX"),
        ("rxCrcErr",       "percent", "MAX"),
        ("rxErr",          "percent", "MAX"),
        ("rxFifoErr",      "percent", "MAX"),
        ("rxOvErr",        "percent", "MAX"),
        ("txCarErr",       "percent", "MAX"),
        ("txErr",          "percent", "MAX"),
        ("portRxDrops",    "percent", "MAX"),
        ("portTxDrops",    "percent", "MAX"),
        ("pauseCount",     "percent", "MAX"),
        ("ioChainDrops",   "",        "MAX"),
        ("ioChainRxdrops", "",        "MAX"),
        ("ioChainTxdrops", "",        "MAX"),
        ("rxMissErrRaw",   "",        "CURRENT"),
        ("rxCrcErrRaw",    "",        "CURRENT"),
        ("pfcCountRaw",    "",        "CURRENT"),
        ("portTxpkts",     "",        "CURRENT"),
    ]),
    ("vSAN Host Network", "VsanHostNet", [
        ("rxPacketsLossRate", "percent", "MAX"),
        ("txPacketsLossRate", "percent", "MAX"),
        ("portRxDrops",       "percent", "MAX"),
        ("portTxDrops",       "percent", "MAX"),
        ("rxThroughput",      "",        "MAX"),
        ("txThroughput",      "",        "MAX"),
        ("rxPackets",         "",        "MAX"),
        ("txPackets",         "",        "MAX"),
    ]),
    ("vSAN Host TCP Health", "VsanTcpIp", [
        ("tcpTxRexmitRate",       "percent", "MAX"),
        ("tcpRxErrRate",          "percent", "MAX"),
        ("tcpRcvdupackRate",      "percent", "MAX"),
        ("tcpRcvduppackRate",     "percent", "MAX"),
        ("tcpRcvoopackRate",      "percent", "MAX"),
        ("tcpSackRcvBlocksRate",  "percent", "MAX"),
        ("tcpSackSendBlocksRate", "percent", "MAX"),
        ("tcpSackRexmitsRate",    "percent", "MAX"),
        ("tcpTimeoutDropRate",    "percent", "MAX"),
        ("tcpHalfopenDropRate",   "percent", "MAX"),
        ("tcpSndZeroWin",         "",        "CURRENT"),
        ("tcpErrs",               "",        "CURRENT"),
    ]),
    ("vSAN RDT Transport Per Host", "VsanRdtLatency", [
        ("avgLatency",    "", "MAX"),
        ("maxLatency",    "", "MAX"),
        ("minLatency",    "", "MIN"),
        ("txQLatAvg",     "", "MAX"),
        ("txQLatMax",     "", "MAX"),
        ("txSbSpaceMin",  "", "MIN"),
        ("rxSbSpaceMin",  "", "MIN"),
        ("rxSbSpaceMax",  "", "MAX"),
        ("kaReset",       "", "CURRENT"),
        ("numReadyDelay", "", "CURRENT"),
    ]),
    ("vSAN ESA Disks", "VsanEsaDiskLayer", [
        ("avgLatReadCapacity",  "", "MAX"),
        ("avgLatWriteCapacity", "", "MAX"),
        ("avgLatWritePerf",     "", "MAX"),
        ("iopsReadCapacity",    "", "MAX"),
        ("iopsWriteCapacity",   "", "MAX"),
    ]),
    ("vSAN ESA Disk Physical Layer", "VsanEsaDiskScsifw", [
        ("latencyDevRead",  "", "MAX"),
        ("latencyDevWrite", "", "MAX"),
        ("latencyDevDAvg",  "", "MAX"),
        ("latencyDevKAvg",  "", "MAX"),
        ("latencyDevGAvg",  "", "MAX"),
    ]),
    ("vSAN VM Storage", "VsanVscsi", [
        ("latencyRead",  "", "MAX"),
        ("latencyWrite", "", "MAX"),
        ("iopsRead",     "", "MAX"),
        ("iopsWrite",    "", "MAX"),
    ]),
    # ---- DOM owner: the coordination layer, previously unsurfaced ---------
    # 272 metrics come back live and 87 of them move. None were on a screen.
    # The owner is the host that coordinates each object's writes, so its
    # latency is the distributed-write cost that the client layer inherits.
    ("vSAN Cluster DOM Owner", "VsanClusterDomowner", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("tputRead", "", "MAX"), ("tputWrite", "", "MAX"),
        ("oio", "", "MAX"),
        ("congestion", "", "MAX"), ("readCongestion", "", "MAX"),
        ("writeCongestion", "", "MAX"),
    ]),
    # The resync JOB QUEUE, which no screen had. The existing resync view
    # shows rebuild IO rates; these show the work outstanding. On a healthy
    # cluster every one of them is zero, and that zero is the answer -- which
    # is why the IO columns sit alongside, to prove the view is collecting.
    ("vSAN Cluster Resync Jobs", "VsanClusterDomowner", [
        ("numPendingResyncJobs", "", "MAX"),
        ("numRunningResyncJobs", "", "MAX"),
        ("numSuspendedResyncJobs", "", "MAX"),
        ("numInflightPriorityResyncJobs", "", "MAX"),
        ("numInflightSharedResyncJobs", "", "MAX"),
        ("numPendingDecomResyncJobs", "", "MAX"),
        ("numPendingFullResyncJobs", "", "MAX"),
        ("numRunningFullResyncJobs", "", "MAX"),
        ("avgResyncParallelism", "", "MAX"),
        ("numCompleteResyncOps", "", "CURRENT"),
        ("numCompleteFullResyncOps", "", "CURRENT"),
        ("iopsResyncRead", "", "MAX"),
        ("iopsRecWrite", "", "MAX"),
        ("iopsWrite", "", "MAX"),
    ]),
    ("vSAN Host DOM Owner", "VsanHostDomowner", [
        ("latencyAvgWrite", "", "MAX"), ("latencyMaxWrite", "", "MAX"),
        ("latencyStddevWrite", "", "MAX"),
        ("latencyAvgRead", "", "MAX"), ("latencyMaxRead", "", "MAX"),
        ("highOIODurationPercentWrite", "percent", "MAX"),
        ("owner2PCCommitLatencyAvgUs", "", "MAX"),
        ("writeLeafOwnerLatencyLocal", "", "MAX"),
        ("writeLeafOwnerLatencyRemote", "", "MAX"),
        ("readLeafOwnerLatencyLocal", "", "MAX"),
        ("readLeafOwnerLatencyRemote", "", "MAX"),
        ("serverSwitchCount", "", "CURRENT"),
        ("iops", "", "MAX"), ("oio", "", "MAX"),
    ]),
    # vSAN's own congestion controller. It bands hosts by observed latency and
    # throttles to protect guest IO; the band counters say whether it is
    # intervening, which no other view here can show.
    ("vSAN Host DOM Owner Scheduler", "VsanHostDomowner", [
        ("numNetSchedRollingAvgLatUs", "", "MAX"),
        ("numNetSchedGuestLTLatUs", "", "MAX"),
        ("numNetSchedLowBandThreshUs", "", "MAX"),
        ("numNetSchedLowBand", "", "CURRENT"),
        ("numNetSchedMidBand", "", "CURRENT"),
        ("numNetSchedLowBandSec", "", "CURRENT"),
        ("numNetSchedMidBandSec", "", "CURRENT"),
        ("numNetSchedLowToMidBand", "", "CURRENT"),
        ("numNetSchedMidToLowBand", "", "CURRENT"),
        ("numNetSchedSeenTotalTpBps", "", "MAX"),
        ("numNetSchedSeenNonResyncTpBps", "", "MAX"),
        ("numNetSchedControllerIopsLimit", "", "MAX"),
    ]),
    # Per-host back end. Only the cluster aggregate was on a screen, which
    # cannot answer "which host's disks are slow".
    ("vSAN Host DOM Component Manager", "VsanHostDomcompmgr", [
        ("latencyAvgRead", "", "MAX"), ("latencyMaxRead", "", "MAX"),
        ("latencyAvgWrite", "", "MAX"), ("latencyMaxWrite", "", "MAX"),
        ("latencyStddevWrite", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("oio", "", "MAX"),
        ("throughputRead", "", "MAX"), ("throughputWrite", "", "MAX"),
        ("vmdiskQueueDepthWrite", "", "MAX"),
        ("vmdiskDispatchedCostWrite", "", "MAX"),
        ("namespaceDispatchedCostWrite", "", "MAX"),
    ]),
    # ESA housekeeping. The log-structured write path reclaims space by
    # cleaning segments, and that work competes with guest IO. Measured here
    # at 370 ms max unmap latency against a 1.3 ms average -- invisible on
    # every other screen.
    ("vSAN Segment Cleaning Per Host", "VsanHostDomowner", [
        ("iopsSegCleanerUnmap", "", "MAX"),
        ("latencyAvgSegCleanerUnmap", "", "MAX"),
        ("latencyMaxSegCleanerUnmap", "", "MAX"),
        ("latencyStddevSegCleanerUnmap", "", "MAX"),
        ("throughputSegCleanerUnmap", "", "MAX"),
        ("segCleanerUnmapLeafOwnerMaxLatencyAvgUs", "", "MAX"),
        ("iopsUnmap", "", "MAX"),
        ("latencyAvgUnmap", "", "MAX"),
        ("latencyMaxUnmap", "", "MAX"),
        ("unmapCount", "", "CURRENT"),
    ]),
    # ---- zDOM: the ESA write path, entirely unsurfaced --------------------
    ("vSAN zDOM Cluster", "VsanClusterZdomTopStats", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("throughputRead", "", "MAX"), ("throughputWrite", "", "MAX"),
        ("oio", "", "MAX"),
    ]),
    ("vSAN zDOM Per Host", "VsanHostZdomTopStats", [
        ("latencyAvgRead", "", "MAX"), ("latencyAvgWrite", "", "MAX"),
        ("readLatencyMaxUs", "", "MAX"), ("writeLatencyMaxUs", "", "MAX"),
        ("unmapLatencyMaxUs", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("throughputRead", "", "MAX"), ("throughputWrite", "", "MAX"),
        ("oio", "", "MAX"), ("oioWrite", "", "MAX"),
    ]),
    ("vSAN zDOM Write Path", "VsanZdomVtx", [
        ("maxDiscUsedPct", "percent", "MAX"),
        ("latAvgTotalOpIO", "", "MAX"),
        ("latAvgTxnBank", "", "MAX"),
        ("rateTotalCacheRef", "", "MAX"),
        ("rateBankFlushTotalCacheRef", "", "MAX"),
        ("rateSegCleaningCtxDataTotalCacheRef", "", "MAX"),
        ("rateTxnPrefetchTotalCacheRef", "", "MAX"),
        ("rateTxnLookupCacheRef", "", "MAX"),
        ("rateTxnReadWrite", "", "MAX"),
        ("checkpointWorkerWakeupMs", "", "MAX"),
    ]),
    # ---- the vmknic, not the physical NIC --------------------------------
    # vSAN traffic leaves through a vmknic. The pNIC view shows the wire; this
    # shows the kernel port, which is where loss attributable to the host
    # rather than the fabric appears first.
    ("vSAN vmknic", "VsanVnic", [
        ("txPacketsLossRate", "percent", "MAX"),
        ("rxPacketsLossRate", "percent", "MAX"),
        ("rxThroughput", "", "MAX"), ("txThroughput", "", "MAX"),
        ("rxPackets", "", "MAX"), ("txPackets", "", "MAX"),
        ("portRxpkts", "", "CURRENT"), ("portTxpkts", "", "CURRENT"),
        ("portRxDrops", "", "MAX"), ("portTxDrops", "", "MAX"),
    ]),
    ("vSAN vmknic RDT Latency", "VsanVnicRdtLatency", [
        ("avgLatency", "", "MAX"), ("maxLatency", "", "MAX"),
        ("minLatency", "", "MIN"),
        ("txQLatAvg", "", "MAX"), ("txQLatMax", "", "MAX"),
        ("txSbSpaceMin", "", "MIN"), ("rxSbSpaceMin", "", "MIN"),
        ("kaReset", "", "CURRENT"), ("numReadyDelay", "", "CURRENT"),
    ]),
    # Cluster membership traffic. If CMMDS cannot talk, the cluster partitions
    # -- and that happens before any IO metric moves.
    ("vSAN CMMDS Network", "VsanCmmdsNet", [
        ("rdtTx", "", "MAX"), ("rdtRx", "", "MAX"),
        ("rdtTxThroughput", "", "MAX"), ("rdtRxThroughput", "", "MAX"),
        ("groupTxUcast", "", "MAX"), ("groupRx", "", "MAX"),
        ("groupTxUcastThroughput", "", "MAX"), ("groupRxThroughput", "", "MAX"),
        ("groupTxMcast", "", "MAX"), ("groupTxMcastThroughput", "", "MAX"),
    ]),
    # ---- host resources: is vSAN slow, or is the host out of road? --------
    ("vSAN Host Memory", "VsanMemory", [
        ("kernelConsumedSize", "", "MAX"), ("kernelReservedSize", "", "CURRENT"),
        ("uwConsumedSize", "", "MAX"), ("uwReservedSize", "", "CURRENT"),
        ("clomdConsumedSize", "", "MAX"), ("clomdReservedSize", "", "CURRENT"),
        ("cmmdsdConsumedSize", "", "MAX"), ("cmmdsdReservedSize", "", "CURRENT"),
        ("vsanmgmtdConsumedSize", "", "MAX"), ("epdConsumedSize", "", "MAX"),
        ("osfsdConsumedSize", "", "MAX"),
        ("vsandevicemonitordConsumedSize", "", "MAX"),
    ]),
    ("vSAN Host CPU", "VsanHostCpu", [
        ("pcpuUsedPct", "percent", "MAX"),
        ("pcpuUtilPct", "percent", "MAX"),
        ("coreUtilPct", "percent", "MAX"),
    ]),
    # ---- the guest view -------------------------------------------------
    # vSAN VM Storage is per-vSCSI-controller. This is per-VM, which is the
    # unit a ticket is raised about.
    ("vSAN VM Latency", "VsanVirtualMachine", [
        ("latencyRead", "", "MAX"), ("latencyWrite", "", "MAX"),
        ("iopsRead", "", "MAX"), ("iopsWrite", "", "MAX"),
        ("throughputRead", "", "MAX"), ("throughputWrite", "", "MAX"),
    ]),
    # ---- borrowed from the vCenter adapter, collected by nothing here -----
    # Our VsanPnic only sees uplinks carrying vSAN traffic, which on this
    # cluster is two of four per host; a standby uplink dropping frames is
    # invisible to it. vCenter counts every uplink, so this closes that gap
    # without collecting anything new. It also carries host CPU and memory
    # pressure, which answers "is this vSAN or is the host saturated".
    ("vSphere Host Uplinks and Load", "HostSystem", [
        ("net|errorsRx_summation", "", "MAX"),
        ("net|droppedRx_summation", "", "MAX"),
        ("net|errorsTx_summation", "", "MAX"),
        ("net|droppedTx_summation", "", "MAX"),
        ("net|usage_average", "", "MAX"),
        ("cpu|usage_average", "", "MAX"),
        ("cpu|capacity_contentionPct", "", "MAX"),
        ("mem|host_usagePct", "", "MAX"),
        ("mem|swapinRate_average", "", "MAX"),
        ("sys|uptime_latest", "", "CURRENT"),
        ("Sensor|status", "", "MIN"),
        ("vcfHealth|connectivity|criticalCount", "", "MAX"),
        ("vcfHealth|utilization|criticalCount", "", "MAX"),
    ], "VMWARE"),
]


# Where no official name exists the derived fallback is sometimes wrong or
# useless. Each entry states why; keep the list short.
OVERRIDE = {
    # the derived name says "Cluster" -- but this view's subject is the
    # PER-HOST kind, so the label would assert the wrong scope
    ("VsanRdtLatency", "maxLatency"): "RDT Network Host Max Latency",
    ("VsanRdtLatency", "minLatency"): "RDT Network Host Min Latency",
    # derived names are placeholders ("Latency dev k (average)"); named to
    # match the DAVG and GAVG siblings that do have official names
    ("VsanEsaDiskScsifw", "latencyDevKAvg"):
        "vSAN ESA Disk Physical/Firmware Layer Kernel Average Latency",
    ("VsanEsaDiskLayer", "avgLatWritePerf"):
        "Perf Tier Average Write Latency of vSAN ESA Disk",
    # "(raw) (Total)" says the same thing twice
    ("VsanPnic", "rxMissErrRaw"): "pNIC RX Missed Error",
    ("VsanPnic", "rxCrcErrRaw"):  "pNIC RX CRC Error",
    ("VsanPnic", "pfcCountRaw"):  "pNIC PFC Count",
    # ---- borrowed vCenter columns: these kinds have no schema here -------
    ("HostSystem", "net|errorsRx_summation"): "Uplink RX Errors, All NICs",
    ("HostSystem", "net|droppedRx_summation"): "Uplink RX Dropped, All NICs",
    ("HostSystem", "net|errorsTx_summation"): "Uplink TX Errors, All NICs",
    ("HostSystem", "net|droppedTx_summation"): "Uplink TX Dropped, All NICs",
    ("HostSystem", "net|usage_average"): "Host Network Throughput",
    ("HostSystem", "cpu|usage_average"): "Host CPU Usage",
    ("HostSystem", "cpu|capacity_contentionPct"): "Host CPU Contention",
    ("HostSystem", "mem|host_usagePct"): "Host Memory Consumed",
    ("HostSystem", "mem|swapinRate_average"): "Host Memory Swap-In Rate",
    ("HostSystem", "sys|uptime_latest"): "Host Uptime",
    ("HostSystem", "Sensor|status"): "Hardware Sensor Status",
    ("HostSystem", "vcfHealth|connectivity|criticalCount"): "Connectivity Issues, Critical",
    ("HostSystem", "vcfHealth|utilization|criticalCount"): "Utilisation Issues, Critical",
}


def label_for(kind, key):
    """Broadcom's official name verbatim, else the pack's derived label."""
    ent = ENT_FOR.get(kind)
    if ent is None:
        # borrowed columns: the kind belongs to another adapter, so there is
        # no schema to consult. OVERRIDE is checked FIRST because the raw key
        # tail ("errorsRx_summation") is not a label anyone should read.
        return OVERRIDE.get((kind, key)) or key.split("|")[-1]
    official = ((SCHEMA.get(ent) or {}).get(key) or {}).get("name")
    label = (OVERRIDE.get((kind, key)) or official
             or metric_labels.LABELS.get(key) or key)
    if key in CUMULATIVE:
        label += " (Total)"
    if key in INVERTED:
        label += " (Low Is Bad)"
    return label


ADAPTER = "VsanHostMetrics"

# Fixed namespace so view GUIDs are reproducible across machines and runs.
NAMESPACE = uuid.UUID("6f3c9b1e-4a2d-5e8f-9c1b-2d7a4e6f8b03")


def guid_for(title):
    """The view's identity, derived from its title and nothing else.

    Single source of truth: build_dash imports this rather than keeping its
    own table of literals, which previously had to be updated by hand every
    time a view was added or renamed.
    """
    return PINNED.get(title) or str(uuid.uuid5(NAMESPACE, title))


def make_item(key, label, unit, transform, kind, adapter=None):
    """One column, built as elements so the result cannot be malformed."""
    item = ET.Element("Item")
    val = ET.SubElement(item, "Value")
    def prop(name, value):
        ET.SubElement(val, "Property", {"name": name, "value": value})
    prop("objectType", "RESOURCE")
    prop("attributeKey", key)
    prop("preferredUnitId", unit)
    prop("isStringAttribute", "false")
    prop("adapterKind", adapter or ADAPTER)
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


def build(template, title, kind, columns, seed, adapter=None):
    """Clone the working export, swapping only identity, subject and columns.

    Parsed and rewritten rather than string-substituted: an earlier regex
    version matched the `</List>` belonging to a column's `transformations`
    instead of the outer `attributeInfos` list, and produced malformed XML.
    """
    adapter = adapter or ADAPTER
    root = ET.fromstring(template)
    vd = root.find(".//ViewDef")
    # Deterministic: the same title always yields the same GUID, so
    # regenerating after a label fix UPDATES the view in place rather than
    # creating a duplicate, and any dashboard referencing it keeps resolving.
    # uuid4 here would mean every edit orphaned the previous import.
    vd.set("id", guid_for(title))
    vd.find("Title").text = title
    for st in vd.findall("SubjectType"):
        st.set("adapterKind", adapter)
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
            for key, unit, transform in columns:
                lst.append(make_item(key, label_for(kind, key), unit, transform,
                                     kind, adapter))
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
    for i, entry in enumerate(VIEWS):
        title, kind, columns = entry[0], entry[1], entry[2]
        adapter = entry[3] if len(entry) > 3 else ADAPTER
        xml = build(template, title, kind, columns, seed=700 + i * 20, adapter=adapter)
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
