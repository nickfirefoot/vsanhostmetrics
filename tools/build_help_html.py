#!/usr/bin/env python3
"""Generate the explanatory HTML that sits beneath each view on a dashboard.

    python3 tools/build_help_html.py      # writes ~/ops-content/out/help/

One file per view, plus one combined file. Generated from `build_view.py`'s
column lists so the text cannot drift out of sync with the tables: a metric
added to a view without a note here fails the build.

Two output forms, because Operations offers two:

  *.inline.html  paste into a Text Display widget's description box
  *.page.html    the shippable form -- a themed, localisable page served from
                 the pak at ContentPack/VsanHostMetrics/conf/pages/<name>/,
                 which is how Broadcom's own Read Me widgets work

Metric names are bold and match the view's column labels exactly.
"""
import html
import os
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                        # noqa: E402

OUT = os.path.expanduser("~/ops-content/out/help")

# What each column means, why it is on the screen, and what it does NOT tell
# you. Written against measurements from a live cluster where one exists.
NOTES = {
    # ---- drive hardware (properties, not metrics) ----------------------
    "model": "The drive's model string as the storage controller reports it.",
    "firmware": "The drive's firmware revision, read from the device through vCenter. The vSAN Performance Service does not report firmware.",
    "driver_version": "The version string of the controller's driver, taken from the HCL section of the cluster health summary. Blank when that summary is unavailable; the driver name is still reported.",
    "driver": "The ESXi driver module bound to the storage controller this drive sits behind. It belongs to the controller, so drives behind the same controller show the same driver. Blank when the host's storage topology could not be read; the drive's firmware is still reported.",

 # ---- vSAN CPU, per host (replaced the per-core VsanHostCpu) --------------
 "readyPct": "Percentage of ready CPU time for vSAN's threads: time they were ready to run but had not been given a physical CPU. Reported by the vSAN Performance Service.",
 "maxRunPct": "Highest running-CPU percentage for vSAN in the interval.",
 "usedPct": "Percentage of used CPU time for vSAN, as reported by the vSAN Performance Service.",
 "runPct": "Percentage of running CPU time for vSAN, as reported by the vSAN Performance Service.",
 "maxUsedPct": "Highest used-CPU percentage for vSAN in the interval.",
 # ---- backpressure, added for Rapid vSAN Backpressure ---------------------
 "txCtxQMax": "Maximum outbound RDT context bytes over the last 5 seconds.",
 "componentCongestion": "Congestion raised against a single component. Shown beside shared congestion on the same row.",
 "sharedCongestion": "Shared congestion, as distinct from congestion raised against a single component.",
 "resyncReadCongestion": "Congestion attributed to resync reads.",
 "recoveryWriteCongestion": "Congestion reported under the id recoveryWriteCongestion. The Performance Service publishes it under the name \"Resync Read Congestions\", and the column label is that Broadcom name.",
 "segCleanerUnmapCongestion": "Congestion attributed to segment cleaner unmap work.",
 # ---- physical NIC -------------------------------------------------------
 "rxMissErr": "The NIC's receive ring had no free descriptor, so the packet was dropped before the driver saw it. Distinct from a drop (discarded higher up) and an error (arrived damaged). This table covers the uplinks the vSAN Performance Service reports on, which are the uplinks carrying vSAN traffic.",
 "rxCrcErr": "The frame arrived damaged and failed its checksum. One of the eight counters behind vCenter's built-in alarm <i>High pNic error rate detected</i> (alarm-261), which is raised when the vSAN health test for any of them reports yellow or red.",
 "rxErr": "Receive errors not attributed to a more specific counter. Useful as a catch-all; look to the specific counters first.",
 "rxFifoErr": "The NIC's own on-chip buffer overflowed before it could move packets across PCIe into host memory. The NIC could not hand data over fast enough.",
 "rxOvErr": "Receive buffer overflow errors on the physical NIC.",
 "txCarErr": "Carrier lost while transmitting.",
 "txErr": "Transmit errors not attributed to a more specific counter.",
 "portRxDrops": "Inbound packets dropped by the vSwitch for this port.",
 "portTxDrops": "The vSwitch discarded outbound packets for this port.",
 "pauseCount": "802.3x pause frames, the flow control a host and a switch use to ask each other to slow down. The counter has no direction: it does not separate pause frames received from pause frames sent. Pause frames are exchanged only when flow control is enabled on the uplink; an uplink's settings can be listed with <code>esxcli network nic pauseParams list</code>.",
 "ioChainDrops": "Packets dropped in the ESXi IO chain.",
 "ioChainRxdrops": "Inbound packets dropped in the ESXi IO chain.",
 "ioChainTxdrops": "Outbound packets dropped in the ESXi IO chain.",
 "rxMissErrRaw": "Cumulative count of missed receive errors. The column of the same name without Raw is the per-interval rate.",
 "rxCrcErrRaw": "Cumulative count of CRC errors. The column of the same name without Raw is the per-interval rate.",
 "pfcCountRaw": "Cumulative count of priority flow control frames.",
 "portTxpkts": "Packets transmitted on this vSwitch port.",
 # ---- host network -------------------------------------------------------
 "rxPacketsLossRate": "Proportion of inbound packets discarded at the host network layer, across all of this host's vSAN traffic rather than one uplink.",
 "txPacketsLossRate": "Proportion of outbound packets discarded at the host network layer.",
 "rxThroughput": "Inbound throughput for this host's vSAN traffic. Context for the error columns.",
 "txThroughput": "Outbound throughput for this host's vSAN traffic.",
 "rxPackets": "Inbound packets per second.",
 "txPackets": "Outbound packets per second.",
 # ---- TCP ----------------------------------------------------------------
 "tcpTxRexmitRate": "Segments this host retransmitted because they were not acknowledged.",
 "tcpRxErrRate": "Inbound TCP segments rejected as erroneous.",
 "tcpRcvdupackRate": "Duplicate acknowledgements received by this host.",
 "tcpRcvduppackRate": "Duplicate packets received: data that arrived more than once.",
 "tcpRcvoopackRate": "Packets received out of order.",
 "tcpSackRcvBlocksRate": "SACK (selective acknowledgement) blocks received.",
 "tcpSackSendBlocksRate": "SACK (selective acknowledgement) blocks sent.",
 "tcpSackRexmitsRate": "Segments retransmitted on the basis of SACK information.",
 "tcpTimeoutDropRate": "Established connections dropped because the retransmission timer expired.",
 "tcpHalfopenDropRate": "Half-open drop rate for the VMkernel network adapter.",
 "tcpSndZeroWin": "Times this host advertised a zero receive window to a peer.",
 "tcpErrs": "Total TCP errors recorded by this host's stack since boot.",
 # ---- RDT ----------------------------------------------------------------
 "avgLatency": "Average round-trip latency of vSAN's own transport between hosts. This sits above TCP, so it can be slow while every NIC counter is clean.",
 "maxLatency": "Worst round-trip latency in the interval.",
 "minLatency": "Best round-trip latency in the interval.",
 "txQLatAvg": "Average time a message waited in the outbound queue before being sent. Queueing, as opposed to time on the wire.",
 "txQLatMax": "Worst outbound queueing delay in the interval.",
 "txSbSpaceMin": "Lowest free space in the outbound socket buffer in the interval.",
 "rxSbSpaceMin": "Lowest free space seen in the inbound socket buffer. <b>Low is bad</b>, for the same reason.",
 "rxSbSpaceMax": "Highest free space seen inbound. Context for the minimum beside it.",
 "kaReset": "Cumulative count of RDT keepalive resets.",
 "numReadyDelay": "Cumulative count of ready delays.",
 # ---- ESA disk, vSAN layer ----------------------------------------------
 "avgLatReadCapacity": "Read latency as vSAN sees it, above the device.",
 "avgLatWriteCapacity": "Write latency as vSAN sees it.",
 "avgLatWritePerf": "Write latency at the performance tier.",
 "iopsReadCapacity": "Read operations per second at the vSAN layer. Context -- high latency at high IOPS is a busy disk, high latency at low IOPS is a sick one.",
 "iopsWriteCapacity": "Write operations per second at the vSAN layer.",
 # ---- ESA disk, physical layer ------------------------------------------
 "latencyDevRead": "Read latency at the physical and firmware layer, below vSAN. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.",
 "latencyDevWrite": "Write latency at the physical and firmware layer, below vSAN. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.",
 "latencyDevDAvg": "<b>DAVG</b> -- time spent in the device itself. High DAVG is a slow or failing drive.",
 "latencyDevKAvg": "KAVG: average time a command spends in the VMkernel.",
 "latencyDevGAvg": "GAVG: average latency seen by the guest, equal to DAVG plus KAVG.",
 # ---- VM -----------------------------------------------------------------
 "latencyRead": "Read latency for this virtual disk, measured at the vSAN layer. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.",
 "latencyWrite": "Write latency for this virtual disk, measured at the vSAN layer. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.",
 "iopsRead": "Read operations per second.",
 "iopsWrite": "Write operations per second.",
}

# ---------------------------------------------------------------------------
# Added during the dashboard refinement. Every note below was written against
# the live three-host ESA cluster, and where a measured value is quoted it is
# from the collection of 2026-10-01.
# ---------------------------------------------------------------------------
NOTES.update({
 # ---- the cluster selector ----------------------------------------------
 "config|name": "The cluster name, from the vCenter adapter rather than this pack. Selecting a row here drives every other panel on the screen.",
 # ---- capacity -----------------------------------------------------------
 "free": "Unused vSAN capacity.",
 "used": "Consumed vSAN capacity, after deduplication and compression.",
 "total": "Usable vSAN capacity. Already excludes the overhead vSAN reserves for itself, so it is smaller than the sum of the disks.",
 "dedupRatio": "Space saving from deduplication and compression, expressed as a ratio scaled by 100: 134 means 1.34 to 1.",
 "savedByDedup": "Space saved by deduplication and compression, in bytes.",
 # ---- DOM, shared across client, owner and component manager -------------
 "latencyAvgRead": "Average read latency at this layer. For the client, component manager and zDOM layers the vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical; it defines no threshold for the owner layer.",
 "latencyAvgWrite": "Average write latency at this layer. For the client, component manager and zDOM layers the vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical; it defines no threshold for the owner layer.",
 "latencyMaxRead": "Worst read latency in the interval.",
 "latencyMaxWrite": "Worst write latency in the interval.",
 "latencyStddevWrite": "Standard deviation of write latency.",
 "congestion": "vSAN congestion raised at this layer.",
 "readCongestion": "Backpressure attributed to reads.",
 "writeCongestion": "Backpressure attributed to writes.",
 "unmapCongestion": "Congestion attributed to unmap operations.",
 "oio": "Outstanding IO: operations issued and not yet completed. Latency multiplied by nothing tells you why it is high -- this does. High latency with high outstanding IO is queueing, high latency with low outstanding IO is a slow device.",
 "oioWrite": "Outstanding write operations.",
 "iops": "Total operations per second at this layer, reads and writes together.",
 "throughputRead": "Bytes per second read at this layer.",
 "throughputWrite": "Bytes per second written at this layer.",
 "tputRead": "Bytes per second read. The owner layer names its throughput columns differently from the client layer; the quantity is the same.",
 "tputWrite": "Bytes per second written.",
 # ---- DOM owner ----------------------------------------------------------
 "highOIODurationPercentWrite": "High outstanding IO duration for writes, as a percentage of the interval.",
 "owner2PCCommitLatencyAvgUs": "Average latency, in microseconds, of the owner's 2PC (two-phase commit) of a write.",
 "writeLeafOwnerLatencyLocal": "Write latency for replicas on this host.",
 "writeLeafOwnerLatencyRemote": "Write latency for replicas on other hosts.",
 "readLeafOwnerLatencyLocal": "Read latency served from this host's own disks.",
 "readLeafOwnerLatencyRemote": "Read latency served from another host's disks.",
 "serverSwitchCount": "Cumulative count of server switches.",
 # ---- DOM owner network scheduler ---------------------------------------
 "numNetSchedRollingAvgLatUs": "Rolling average latency, in microseconds, reported by adaptive network shaping.",
 "numNetSchedGuestLTLatUs": "Guest long-tail latency, in microseconds, reported by adaptive network shaping.",
 "numNetSchedLowBandThreshUs": "Latency threshold, in microseconds, for the low band.",
 "numNetSchedLowBand": "Number of times this host was placed in the low band.",
 "numNetSchedMidBand": "Number of times this host was placed in the middle band.",
 "numNetSchedLowBandSec": "Seconds spent in the low band.",
 "numNetSchedMidBandSec": "Seconds spent in the middle band.",
 "numNetSchedLowToMidBand": "Transitions from the low band to the middle band.",
 "numNetSchedMidToLowBand": "Transitions from the middle band to the low band.",
 "numNetSchedSeenTotalTpBps": "Total throughput observed by adaptive network shaping.",
 "numNetSchedSeenNonResyncTpBps": "Throughput observed by adaptive network shaping, excluding resync traffic.",
 "numNetSchedControllerIopsLimit": "Controller IOPS limit reported by adaptive network shaping.",
 # ---- component manager queueing ----------------------------------------
 "vmdiskQueueDepthWrite": "Queue depth for virtual disk writes at the component manager.",
 "vmdiskDispatchedCostWrite": "Cost of dispatched virtual disk writes, as reported by the component manager.",
 "namespaceDispatchedCostWrite": "Cost of dispatched writes to namespace objects, which hold VM configuration files, as reported by the component manager.",
 # ---- resync -------------------------------------------------------------
 "iopsResyncRead": "Read operations per second performed to rebuild redundancy. <b>Zero unless something is actually resyncing</b>, which is the normal and desirable reading.",
 "tputResyncRead": "Bytes per second read for rebuild.",
 "latAvgResyncRead": "Average latency of rebuild reads.",
 "iopsRecWrite": "Write operations per second performed to restore redundancy -- the other half of a rebuild.",
 "throughputRecWrite": "Bytes per second written to restore redundancy. Divide the outstanding work by this to estimate how long a rebuild has left.",
 "latencyAvgRecWrite": "Average latency of recovery writes.",
 "numPendingResyncJobs": "Resync jobs queued and not yet started.",
 "numRunningResyncJobs": "Resync jobs currently running.",
 "numSuspendedResyncJobs": "Resync jobs currently suspended.",
 "numInflightPriorityResyncJobs": "Priority resync jobs in flight.",
 "numInflightSharedResyncJobs": "Shared resync jobs in flight.",
 "numPendingDecomResyncJobs": "Pending resync jobs created by decommissioning.",
 "numPendingFullResyncJobs": "Pending full resync jobs.",
 "numRunningFullResyncJobs": "Running full resync jobs.",
 "avgResyncParallelism": "Average number of resync operations running in parallel.",
 "numCompleteResyncOps": "Cumulative count of completed resync operations.",
 "numCompleteFullResyncOps": "Cumulative count of completed full resync operations.",
 # ---- segment cleaning ---------------------------------------------------
 "iopsSegCleanerUnmap": "Operations per second performed by the segment cleaner.",
 "latencyAvgSegCleanerUnmap": "Average segment cleaner unmap latency.",
 "latencyMaxSegCleanerUnmap": "Worst segment cleaner unmap latency in the interval.",
 "latencyStddevSegCleanerUnmap": "Standard deviation of segment cleaner unmap latency.",
 "throughputSegCleanerUnmap": "Bytes per second moved by the segment cleaner.",
 "segCleanerUnmapLeafOwnerMaxLatencyAvgUs": "Segment cleaner unmap leaf-owner latency: the maximum of the averages, in microseconds.",
 "iopsUnmap": "Space-reclamation operations per second, including those originated by guests trimming their filesystems.",
 "latencyAvgUnmap": "Average latency of unmap operations.",
 "latencyMaxUnmap": "Worst unmap latency in the interval.",
 "unmapCount": "Cumulative count of unmap operations.",
 # ---- zDOM ---------------------------------------------------------------
 "readLatencyMaxUs": "Worst read latency recorded in the zDOM layer, in microseconds.",
 "writeLatencyMaxUs": "Worst write latency recorded in the zDOM layer, in microseconds.",
 "unmapLatencyMaxUs": "Worst unmap latency recorded in the zDOM layer, in microseconds.",
 "maxDiscUsedPct": "Highest disc used percentage in the interval.",
 "latAvgTotalOpIO": "Average latency of all zDOM operations.",
 "latAvgTxnBank": "Average latency of transaction bank operations.",
 "rateTotalCacheRef": "Rate of zDOM cache references, all kinds together.",
 "rateBankFlushTotalCacheRef": "Cache references from flushing the transaction bank.",
 "rateSegCleaningCtxDataTotalCacheRef": "Cache references from segment cleaning.",
 "rateTxnPrefetchTotalCacheRef": "Cache references from transaction prefetch.",
 "rateTxnLookupCacheRef": "Cache references from transaction lookups.",
 "rateTxnReadWrite": "Read-write transaction rate in the zDOM layer.",
 "checkpointWorkerWakeupMs": "Interval, in milliseconds, at which the checkpoint worker wakes.",
 # ---- vmknic -------------------------------------------------------------
 "portRxpkts": "Packets received on this kernel port.",
 # ---- CMMDS --------------------------------------------------------------
 "rdtTx": "Cluster directory messages sent by this host. CMMDS is how hosts agree on cluster membership and object placement; if it cannot talk, the cluster partitions, and that happens before any IO metric moves.",
 "rdtRx": "Cluster directory messages received.",
 "rdtTxThroughput": "CMMDS network read outbound throughput, in bytes per second.",
 "rdtRxThroughput": "Bytes per second of inbound cluster directory traffic.",
 "groupTxUcast": "Unicast membership messages sent.",
 "groupRx": "Membership messages received.",
 "groupTxUcastThroughput": "Bytes per second of outbound unicast membership traffic.",
 "groupRxThroughput": "Bytes per second of inbound membership traffic.",
 "groupTxMcast": "Multicast membership messages sent.",
 "groupTxMcastThroughput": "Bytes per second of outbound multicast membership traffic. Expected to be zero.",
 # ---- host memory --------------------------------------------------------
 "kernelConsumedSize": "Memory in use by the vSAN kernel modules.",
 "kernelReservedSize": "Memory reserved for the vSAN kernel modules.",
 "uwConsumedSize": "Memory consumed by vSAN user-world processes in total.",
 "uwReservedSize": "Memory reserved for vSAN user-world processes.",
 "clomdConsumedSize": "Memory used by clomd, the cluster level object manager daemon.",
 "clomdReservedSize": "Memory reserved for clomd.",
 "cmmdsdConsumedSize": "Memory used by <b>cmmdsd</b>, the cluster directory service that maintains membership and object metadata.",
 "cmmdsdReservedSize": "Memory reserved for cmmdsd.",
 "vsanmgmtdConsumedSize": "Memory used by vsanmgmtd, the vSAN management daemon.",
 "epdConsumedSize": "Memory used by epd, a vSAN daemon.",
 "osfsdConsumedSize": "Memory used by osfsd, the object filesystem daemon.",
 "vsandevicemonitordConsumedSize": "Memory used by vsandevicemonitord, the vSAN device monitor daemon.",
 # ---- host CPU -----------------------------------------------------------
 # ---- borrowed from the vCenter adapter ---------------------------------
 "net|errorsRx_summation": "Inbound errors summed across every uplink on the host, counted by vCenter rather than by this pack.",
 "net|droppedRx_summation": "Inbound packets dropped across every uplink on the host.",
 "net|errorsTx_summation": "Outbound errors across every uplink on the host.",
 "net|droppedTx_summation": "Outbound packets dropped across every uplink on the host.",
 "net|usage_average": "Network throughput of the host, all uplinks and all traffic types, as reported by vCenter.",
 "cpu|usage_average": "CPU usage of the host, as reported by vCenter.",
 "cpu|capacity_contentionPct": "CPU contention for the host: the proportion of time virtual machines waited for CPU, as reported by vCenter.",
 "mem|host_usagePct": "Proportion of host memory consumed.",
 "mem|swapinRate_average": "Rate at which the host reads swapped memory back from disk, as reported by vCenter.",
 "sys|uptime_latest": "Time since the host last booted.",
 # ---- vSAN service health, from vCenter ---------------------------------
 "Sensor|status": "Overall hardware sensor health, as the host's own sensors report it.",
 "vcfHealth|connectivity|criticalCount": "Count of critical connectivity findings against this host.",
 "vcfHealth|utilization|criticalCount": "Count of critical utilisation findings against this host.",
})

PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="X-UA-Compatible" content="IE=edge;chrome=1;" />
    <link rel="stylesheet" type="text/css" href="css/main.css">
    <script>
        var cssId = 'themeCss';
        if (!document.getElementById(cssId)) {{
            var head = document.getElementsByTagName('head')[0];
            var link = document.createElement('link');
            link.id = cssId; link.rel = 'stylesheet'; link.type = 'text/css';
            link.href = 'css/' + parent.colorScheme + '.css'; link.media = 'all';
            head.appendChild(link);
        }}
    </script>
</head>
<body>
    <div class="main-div">
{body}
    </div>
</body>
</html>
"""


def body_for(title, kind, columns):
    out = [f"        <h3>{html.escape(title)}</h3>"]
    for key, _unit, _tr in columns:
        label = build_view.label_for(kind, key)
        note = NOTES.get(key)
        if not note:
            raise SystemExit(f"no explanation written for {kind}/{key}")
        out.append(f'        <p><b>{html.escape(label)}</b> &mdash; {note}</p>')
    return "\n".join(out)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    combined = []
    for entry in build_view.VIEWS:
        title, kind, columns = entry[0], entry[1], entry[2]
        body = body_for(title, kind, columns)
        combined.append(body)
        name = title.replace(" ", "_")
        open(os.path.join(OUT, f"{name}.inline.html"), "w").write(body + "\n")
        open(os.path.join(OUT, f"{name}.page.html"), "w").write(PAGE.format(body=body))
        print(f"  {name}: {len(columns)} metrics")
    allbody = "\n".join(combined)
    open(os.path.join(OUT, "ALL.inline.html"), "w").write(allbody + "\n")
    open(os.path.join(OUT, "ALL.page.html"), "w").write(PAGE.format(body=allbody))
    print(f"\n  wrote {OUT}")


if __name__ == "__main__":
    main()
