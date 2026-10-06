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
 # ---- physical NIC -------------------------------------------------------
 "rxMissErr": "The NIC's receive ring had no free descriptor, so the packet was dropped before the driver ever saw it. The clearest single sign that a NIC is being overrun. Distinct from a drop (discarded higher up) and an error (arrived damaged). <b>Scope: this table covers vSAN-tagged uplinks only</b> -- the Performance Service models the uplinks carrying vSAN traffic, so an uplink not carrying it, including a standby, does not appear here at all and cannot be judged from this screen.",
 "rxCrcErr": "The frame arrived damaged and failed its checksum. Almost always physical: cable, connector, optic or port. Not a capacity problem. <b>The 0.1% threshold on this column is the product's own</b>, not a figure invented here: vCenter's <code>alarm-261</code>, \"High pNic error rate detected\", fires at 1 per mille on this counter and seven of its siblings. So the yellow band here coincides with when vSAN itself raises an alarm.",
 "rxErr": "Receive errors not attributed to a more specific counter. Useful as a catch-all; look to the specific counters first.",
 "rxFifoErr": "The NIC's own on-chip buffer overflowed before it could move packets across PCIe into host memory. The NIC could not hand data over fast enough.",
 "rxOvErr": "Receive buffer overrun. Driver-dependent and often moves with FIFO errors; both mean the receive path could not keep up.",
 "txCarErr": "Carrier lost while transmitting -- a physical link problem. Check the port, cable and link negotiation.",
 "txErr": "Transmit errors not attributed to a more specific counter.",
 "portRxDrops": "The vSwitch discarded inbound packets for this port. A small, constant rate is usually normal: broadcast and multicast traffic the switch has nowhere to deliver. A rate that <i>changes</i> is the signal, not its presence.",
 "portTxDrops": "The vSwitch discarded outbound packets for this port.",
 "pauseCount": "802.3x pause frames. These are flow control -- the host and the switch asking each other to slow down. <b>No direction is available</b>, so a non-zero value cannot distinguish 'this host is drowning' from 'the fabric is congested'. <b>And a zero is often meaningless</b>: flow control has to be enabled on the uplink for the counter to move at all. Measured on the lab through <code>network.nic.pauseParams.list</code>: <b>nmlx5_core uplinks have PauseRX and PauseTX on, ixgben uplinks have both off</b>, so on every Intel uplink there a zero says nothing whatsoever. Check the uplink's pause configuration before reading this column either way.",
 "ioChainDrops": "Packets dropped inside the ESXi IO chain, above the NIC and below the vSwitch port.",
 "ioChainRxdrops": "Inbound packets dropped inside the ESXi IO chain.",
 "ioChainTxdrops": "Outbound packets dropped inside the ESXi IO chain.",
 "rxMissErrRaw": "Lifetime count of missed receive errors since the host booted. The rate columns answer <i>is it happening now</i>; this answers <i>has this NIC ever been bad</i>. A NIC reading 0% now with thousands here has a history worth knowing.",
 "rxCrcErrRaw": "Lifetime count of CRC errors since boot.",
 "pfcCountRaw": "Lifetime count of priority flow control frames since boot.",
 "portTxpkts": "Packets transmitted on this vSwitch port. Context, not a fault -- an error count means nothing without knowing the traffic it happened against.",
 # ---- host network -------------------------------------------------------
 "rxPacketsLossRate": "Proportion of inbound packets discarded at the host network layer, across all of this host's vSAN traffic rather than one uplink.",
 "txPacketsLossRate": "Proportion of outbound packets discarded at the host network layer.",
 "rxThroughput": "Inbound throughput for this host's vSAN traffic. Context for the error columns.",
 "txThroughput": "Outbound throughput for this host's vSAN traffic.",
 "rxPackets": "Inbound packets per second.",
 "txPackets": "Outbound packets per second.",
 # ---- TCP ----------------------------------------------------------------
 "tcpTxRexmitRate": "Segments this host had to send again because they were not acknowledged. The cost of loss somewhere on the path, paid in latency.",
 "tcpRxErrRate": "Inbound TCP segments rejected as erroneous.",
 "tcpRcvdupackRate": "Duplicate acknowledgements received. The peer is telling us, repeatedly, that it is still missing something -- an early sign of loss on our outbound path, visible before a retransmit timer fires.",
 "tcpRcvduppackRate": "Duplicate packets received: the same data arrived twice, usually because a peer retransmitted something that was not actually lost.",
 "tcpRcvoopackRate": "Packets arriving out of order. Broadcom treat 0.1% as a warning and 1% as critical. Reordering alone is not loss, but TCP responds to it as though it were.",
 "tcpSackRcvBlocksRate": "SACK blocks <b>received</b>. The peer is reporting holes in what <b>we sent it</b>, so this points at loss on our <b>outbound</b> path. Appears before retransmit timeouts do.",
 "tcpSackSendBlocksRate": "SACK blocks <b>sent</b>. We are reporting holes in what <b>the peer sent us</b> -- loss on our <b>inbound</b> path. The mirror image of the column above, and reading the pair tells you which direction is losing.",
 "tcpSackRexmitsRate": "Retransmissions we performed because SACK information told us precisely which segments were missing.",
 "tcpTimeoutDropRate": "Established connections torn down because the retransmission timer expired. The end state of sustained loss: the stack gave up rather than kept trying.",
 "tcpHalfopenDropRate": "Connections dropped mid-handshake, in SYN_RCVD -- a SYN arrived, the reply went out, the confirmation never came. <b>Reads 7-9% on a healthy cluster here and the denominator is undocumented</b>, so do not treat a non-zero value as a fault until that is understood.",
 "tcpSndZeroWin": "Times this host told a peer to stop sending because its receive buffer was full. <b>Not a network fault</b> -- the network delivered and the host could not consume. Look up the stack at CPU and at the vSAN layers, not at the wire.",
 "tcpErrs": "Total TCP errors recorded by this host's stack since boot.",
 # ---- RDT ----------------------------------------------------------------
 "avgLatency": "Average round-trip latency of vSAN's own transport between hosts. This sits above TCP, so it can be slow while every NIC counter is clean.",
 "maxLatency": "Worst round-trip latency observed. Spikes here matter more than the average -- one stalled transfer blocks whatever was waiting on it.",
 "minLatency": "Best round-trip latency observed. Useful only as a floor to compare the average against.",
 "txQLatAvg": "Average time a message waited in the outbound queue before being sent. Queueing, as opposed to time on the wire.",
 "txQLatMax": "Worst outbound queueing delay observed.",
 "txSbSpaceMin": "Lowest free space seen in the outbound socket buffer. <b>Low is bad</b> -- this measures headroom remaining, so it reads backwards from every other column. Zero means exhaustion and a stalled transport.",
 "rxSbSpaceMin": "Lowest free space seen in the inbound socket buffer. <b>Low is bad</b>, for the same reason.",
 "rxSbSpaceMax": "Highest free space seen inbound. Context for the minimum beside it.",
 "kaReset": "Lifetime count of keepalive resets: RDT gave up on a peer connection and re-established it. <b>Cumulative since boot</b>, so the number itself means little -- watch whether it is <i>increasing</i>.",
 "numReadyDelay": "Lifetime count of delays waiting for a connection to become ready. <b>Cumulative since boot</b>; the trend is the signal.",
 # ---- ESA disk, vSAN layer ----------------------------------------------
 "avgLatReadCapacity": "Read latency as vSAN sees it, above the device. Compare across disks rather than against a fixed number: the signal is one disk diverging from its peers.",
 "avgLatWriteCapacity": "Write latency as vSAN sees it.",
 "avgLatWritePerf": "Write latency at the performance tier.",
 "iopsReadCapacity": "Read operations per second at the vSAN layer. Context -- high latency at high IOPS is a busy disk, high latency at low IOPS is a sick one.",
 "iopsWriteCapacity": "Write operations per second at the vSAN layer.",
 # ---- ESA disk, physical layer ------------------------------------------
 "latencyDevRead": "Read latency at the physical and firmware layer, below vSAN. Compare with the vSAN layer column: if both are high the device is slow, if only the vSAN layer is high the delay is above the disk. <b>Product threshold 15 ms warning, 30 ms critical.</b>",
 "latencyDevWrite": "Write latency at the physical and firmware layer. <b>Product threshold 15 ms warning, 30 ms critical.</b>",
 "latencyDevDAvg": "<b>DAVG</b> -- time spent in the device itself. High DAVG is a slow or failing drive.",
 "latencyDevKAvg": "<b>KAVG</b> -- time spent queued in the VMkernel before reaching the device. High KAVG is contention, not a bad disk.",
 "latencyDevGAvg": "<b>GAVG</b> -- what the guest actually experiences, being DAVG plus KAVG. Read the three together: GAVG tells you it hurts, DAVG and KAVG tell you which to fix.",
 # ---- VM -----------------------------------------------------------------
 "latencyRead": "Read latency for this virtual disk, measured at the vSAN layer. <b>Product threshold 15 ms warning, 30 ms critical.</b>",
 "latencyWrite": "Write latency for this virtual disk, measured at the vSAN layer. <b>Product threshold 15 ms warning, 30 ms critical.</b>",
 "iopsRead": "Read operations per second. Always read beside latency: high latency at high IOPS is a busy VM, high latency at near-zero IOPS is a sick one.",
 "iopsWrite": "Write operations per second.",
}

# ---------------------------------------------------------------------------
# Added during the dashboard refinement. Every note below was written against
# the live three-host ESA cluster, and where a measured value is quoted it is
# from the collection of 2026-10-01.
# ---------------------------------------------------------------------------
NOTES.update({
 # ---- the cluster selector ----------------------------------------------
 "config|name": "The cluster name, from the vCenter adapter rather than this pack. Selecting a row here drives every other panel on the screen. This is a <b>property</b>, not a metric, which is why the column carries the isProperty flag.",
 # ---- capacity -----------------------------------------------------------
 "free": "Unused vSAN capacity. Read it next to <b>Total</b>, not alone: the same free figure means very different things on a 10 TB and a 1 PB cluster.",
 "used": "Consumed vSAN capacity, after deduplication and compression.",
 "total": "Usable vSAN capacity. Already excludes the overhead vSAN reserves for itself, so it is smaller than the sum of the disks.",
 "dedupRatio": "Space saving from deduplication and compression, expressed as a ratio scaled by 100 -- <b>134 means 1.34:1</b>, not 134:1. A ratio that falls sharply usually means new data that does not deduplicate, not a fault.",
 "savedByDedup": "Bytes not written because deduplication and compression removed them. The absolute saving behind the ratio beside it.",
 # ---- DOM, shared across client, owner and component manager -------------
 "latencyAvgRead": "Average read latency at this layer. <b>Broadcom's own threshold for this metric is 15 ms warning and 30 ms critical</b>, published in the Performance Service graph definition as yellow=15000 red=30000 microseconds, direction upper. That is a "something is badly wrong" line rather than a tuning line -- a healthy cluster here runs under 1.5 ms, so the product only flags at roughly ten times normal. Compare the same column across the client, owner and component manager views: the layer where the number first becomes large is the layer to investigate.",
 "latencyAvgWrite": "Average write latency at this layer. On ESA a write is acknowledged after it is logged, so this is usually far lower than the component manager's figure beneath it. <b>Product threshold 15 ms warning, 30 ms critical.</b>",
 "latencyMaxRead": "Worst read latency in the interval. Read beside the average: a large gap is a tail-latency problem, which guests feel as stalls even when the average looks fine.",
 "latencyMaxWrite": "Worst write latency in the interval. Measured here at <b>14.9 ms against a 957 microsecond average</b> -- a fifteenfold tail on an idle cluster, and the kind of thing an average hides completely.",
 "latencyStddevWrite": "Spread of write latency. High spread with a low average means the work is bimodal: most operations fast, some very slow.",
 "congestion": "vSAN's own backpressure signal, raised when a layer cannot absorb the offered load and asks the layer above to slow down. <b>Zero on a healthy cluster</b>, and it reads zero here. Any sustained non-zero value is the single most important number on the screen.",
 "readCongestion": "Backpressure attributed to reads.",
 "writeCongestion": "Backpressure attributed to writes.",
 "unmapCongestion": "Backpressure attributed to unmap and space-reclamation work.",
 "oio": "Outstanding IO: operations issued and not yet completed. Latency multiplied by nothing tells you why it is high -- this does. High latency with high outstanding IO is queueing, high latency with low outstanding IO is a slow device.",
 "oioWrite": "Outstanding write operations.",
 "iops": "Total operations per second at this layer, reads and writes together.",
 "throughputRead": "Bytes per second read at this layer.",
 "throughputWrite": "Bytes per second written at this layer.",
 "tputRead": "Bytes per second read. The owner layer names its throughput columns differently from the client layer; the quantity is the same.",
 "tputWrite": "Bytes per second written.",
 # ---- DOM owner ----------------------------------------------------------
 "highOIODurationPercentWrite": "Proportion of the interval the owner spent with its write queue above its high-watermark. <b>Measured at 3% here on an otherwise idle cluster.</b> This is the metric vCenter surfaces as a top-line vSAN indicator, and it moves well before average latency does.",
 "owner2PCCommitLatencyAvgUs": "Time to commit a write across its replicas using two-phase commit. This is the irreducible cost of making a write durable in more than one place, and it sets the floor under every write latency above it.",
 "writeLeafOwnerLatencyLocal": "Write latency for replicas that live on <b>this</b> host, so no network is involved.",
 "writeLeafOwnerLatencyRemote": "Write latency for replicas on <b>other</b> hosts, which includes the network round trip. Read as a pair with the local column: remote should be the slower of the two, and when it is not, the local disks are the problem.",
 "readLeafOwnerLatencyLocal": "Read latency served from this host's own disks. <b>Measured at 1392 microseconds here against 905 for remote reads</b> -- local slower than across the network, which inverts the expected order and points at a local device rather than the fabric.",
 "readLeafOwnerLatencyRemote": "Read latency served from another host's disks, network included.",
 "serverSwitchCount": "Lifetime count of ownership changes: how often coordination of an object moved from one host to another. <b>Cumulative since boot</b>, so the value means little; a rate that climbs means objects are being handed around, which costs latency.",
 # ---- DOM owner network scheduler ---------------------------------------
 "numNetSchedRollingAvgLatUs": "The rolling average latency vSAN's own scheduler is working from. This is the input to its throttling decisions, not an observation of guest latency.",
 "numNetSchedGuestLTLatUs": "Guest long-tail latency as the scheduler measures it. What it is trying to protect.",
 "numNetSchedLowBandThreshUs": "The latency threshold at which the scheduler moves a host into its low band. Context for the band counters -- without it they are unreadable.",
 "numNetSchedLowBand": "Times the scheduler placed this host in its <b>low</b> band, meaning it decided latency was bad enough to throttle rebuild and resync traffic hard to protect guest IO.",
 "numNetSchedMidBand": "Times the scheduler placed this host in its <b>middle</b> band: some throttling, latency elevated but not severe.",
 "numNetSchedLowBandSec": "Seconds spent in the low band. More useful than the count beside it -- one long episode and many brief ones are different problems.",
 "numNetSchedMidBandSec": "Seconds spent in the middle band.",
 "numNetSchedLowToMidBand": "Transitions from the low band up to the middle band, meaning conditions improved.",
 "numNetSchedMidToLowBand": "Transitions from the middle band down to the low band, meaning conditions worsened. A host oscillating between bands is unstable in a way neither band counter alone reveals.",
 "numNetSchedSeenTotalTpBps": "Total throughput the scheduler observed, guest and rebuild traffic together.",
 "numNetSchedSeenNonResyncTpBps": "Throughput excluding resync. Subtract it from the total to see what rebuild traffic is actually consuming -- the pair answers 'is the rebuild hurting the guests'.",
 "numNetSchedControllerIopsLimit": "The IOPS ceiling the scheduler is currently imposing. A limit far above actual load means it is not intervening.",
 # ---- component manager queueing ----------------------------------------
 "vmdiskQueueDepthWrite": "Queue depth for writes to virtual disk objects at the component manager. Depth is the cause; the latency columns are the effect.",
 "vmdiskDispatchedCostWrite": "Accumulated cost of dispatched virtual disk writes, in vSAN's internal scheduling units. Not comparable to a time or a byte count -- useful for comparing hosts against each other, not against a threshold.",
 "namespaceDispatchedCostWrite": "The same cost measure for namespace objects, which hold VM configuration rather than guest data. Large values here with small virtual disk values mean the work is metadata, not guest IO.",
 # ---- resync -------------------------------------------------------------
 "iopsResyncRead": "Read operations per second performed to rebuild redundancy. <b>Zero unless something is actually resyncing</b>, which is the normal and desirable reading.",
 "tputResyncRead": "Bytes per second read for rebuild.",
 "latAvgResyncRead": "Average latency of rebuild reads.",
 "iopsRecWrite": "Write operations per second performed to restore redundancy -- the other half of a rebuild.",
 "throughputRecWrite": "Bytes per second written to restore redundancy. Divide the outstanding work by this to estimate how long a rebuild has left.",
 "latencyAvgRecWrite": "Average latency of recovery writes.",
 "numPendingResyncJobs": "Rebuild jobs queued and not yet started. <b>The single best measure of outstanding risk</b>: until this reaches zero, some data is below its intended redundancy.",
 "numRunningResyncJobs": "Rebuild jobs currently executing. vSAN limits concurrency deliberately, so a large pending count with a small running count is normal pacing, not a stall.",
 "numSuspendedResyncJobs": "Rebuild jobs vSAN has paused, usually to protect guest IO. <b>Sustained non-zero here with a non-zero pending count means rebuilds are not progressing</b>, and the cluster is staying at reduced redundancy longer than it needs to.",
 "numInflightPriorityResyncJobs": "Rebuilds vSAN has prioritised, which it does when data is at genuine risk rather than merely non-compliant.",
 "numInflightSharedResyncJobs": "Rebuilds running at normal priority.",
 "numPendingDecomResyncJobs": "Rebuilds queued because a host or disk is being evacuated. Non-zero means a maintenance operation is waiting on data movement.",
 "numPendingFullResyncJobs": "Queued rebuilds that must copy a whole component rather than a delta. These are the expensive ones.",
 "numRunningFullResyncJobs": "Full-component rebuilds currently running.",
 "avgResyncParallelism": "How many rebuild operations vSAN is running at once on average. Low parallelism with a deep pending queue is the signature of throttling.",
 "numCompleteResyncOps": "Lifetime count of completed rebuild operations. <b>Cumulative since boot</b>; the trend tells you whether progress is being made.",
 "numCompleteFullResyncOps": "Lifetime count of completed full-component rebuilds.",
 # ---- segment cleaning ---------------------------------------------------
 "iopsSegCleanerUnmap": "Operations per second performed by the segment cleaner. ESA writes to a log and must later reclaim partially-used segments; this is that housekeeping, and it competes with guest IO for the same disks.",
 "latencyAvgSegCleanerUnmap": "Average latency of segment cleaning work.",
 "latencyMaxSegCleanerUnmap": "Worst segment cleaning latency in the interval. <b>Measured at 370 milliseconds here against a 1.3 millisecond average.</b> Housekeeping stalling for a third of a second is worth knowing about, and no other screen in this pack would show it.",
 "latencyStddevSegCleanerUnmap": "Spread of segment cleaning latency.",
 "throughputSegCleanerUnmap": "Bytes per second the segment cleaner is moving. This is write amplification made visible: capacity the disks are spending on vSAN's own bookkeeping rather than on guest data.",
 "segCleanerUnmapLeafOwnerMaxLatencyAvgUs": "Worst average latency any single replica contributed to segment cleaning. Isolates one bad disk inside an otherwise healthy cleaning cycle.",
 "iopsUnmap": "Space-reclamation operations per second, including those originated by guests trimming their filesystems.",
 "latencyAvgUnmap": "Average latency of unmap operations.",
 "latencyMaxUnmap": "Worst unmap latency in the interval.",
 "unmapCount": "Lifetime count of unmap operations. <b>Cumulative since boot.</b>",
 # ---- zDOM ---------------------------------------------------------------
 "readLatencyMaxUs": "Worst read latency recorded in the zDOM layer. <b>Reads 9.7 seconds here, which is not credible as an interval maximum</b> -- it is very likely a since-boot high-water mark that the Performance Service does not document as such. Treat a large value as unverified until the behaviour is confirmed, and use the average column for decisions.",
 "writeLatencyMaxUs": "Worst write latency recorded in the zDOM layer. Subject to the same caveat as the read column beside it.",
 "unmapLatencyMaxUs": "Worst unmap latency recorded in the zDOM layer.",
 "maxDiscUsedPct": "Highest proportion of the log structure in use. <b>Measured at 32% here.</b> As this climbs the segment cleaner has to work harder and write amplification rises, so it is a leading indicator for the latency columns on the segment cleaning view.",
 "latAvgTotalOpIO": "Average latency of all zDOM operations together.",
 "latAvgTxnBank": "Average latency of transaction bank operations -- the in-memory staging area a write passes through before it is logged.",
 "rateTotalCacheRef": "Rate of references to zDOM's metadata cache, all kinds together. Context for the breakdown columns beside it rather than a health signal.",
 "rateBankFlushTotalCacheRef": "Cache references caused by flushing the transaction bank to disk.",
 "rateSegCleaningCtxDataTotalCacheRef": "Cache references caused by segment cleaning. Rising here while guest IOPS is flat means housekeeping is taking a larger share of the metadata path.",
 "rateTxnPrefetchTotalCacheRef": "Cache references from prefetching metadata ahead of need. Effective prefetch is why read latency stays low; this is the work behind that.",
 "rateTxnLookupCacheRef": "Cache references from metadata lookups that could not be satisfied by prefetch.",
 "rateTxnReadWrite": "Ratio of read to write transactions in the zDOM layer. Characterises the workload rather than its health.",
 "checkpointWorkerWakeupMs": "Interval at which the checkpoint worker wakes to persist metadata. Steady by design; a change means configuration changed or the worker is falling behind.",
 # ---- vmknic -------------------------------------------------------------
 "portRxpkts": "Packets received on this kernel port. <b>Cumulative since boot</b>, and context for the loss rates rather than a fault in itself.",
 # ---- CMMDS --------------------------------------------------------------
 "rdtTx": "Cluster directory messages sent by this host. CMMDS is how hosts agree on cluster membership and object placement; if it cannot talk, the cluster partitions, and that happens before any IO metric moves.",
 "rdtRx": "Cluster directory messages received.",
 "rdtTxThroughput": "Bytes per second of outbound cluster directory traffic. Small and steady by nature -- a sudden rise usually means membership churn.",
 "rdtRxThroughput": "Bytes per second of inbound cluster directory traffic.",
 "groupTxUcast": "Unicast membership messages sent. Modern vSAN uses unicast for membership, so this is the column that should be moving.",
 "groupRx": "Membership messages received.",
 "groupTxUcastThroughput": "Bytes per second of outbound unicast membership traffic.",
 "groupRxThroughput": "Bytes per second of inbound membership traffic.",
 "groupTxMcast": "Multicast membership messages sent. <b>Zero is expected</b> on any cluster since vSAN 6.6, which moved membership to unicast. Non-zero means a legacy configuration.",
 "groupTxMcastThroughput": "Bytes per second of outbound multicast membership traffic. Expected to be zero.",
 # ---- host memory --------------------------------------------------------
 "kernelConsumedSize": "Memory the vSAN kernel modules are actually using. <b>Measured at 2.14 GB against 21.0 GB reserved</b>, so roughly a tenth of the reservation.",
 "kernelReservedSize": "Memory reserved for the vSAN kernel modules. Reserved is not consumed -- compare the two columns rather than reading either alone.",
 "uwConsumedSize": "Memory consumed by vSAN user-world processes in total.",
 "uwReservedSize": "Memory reserved for vSAN user-world processes.",
 "clomdConsumedSize": "Memory used by <b>clomd</b>, which decides where objects and their replicas are placed. Growth here tracks object count, not IO.",
 "clomdReservedSize": "Memory reserved for clomd.",
 "cmmdsdConsumedSize": "Memory used by <b>cmmdsd</b>, the cluster directory service that maintains membership and object metadata.",
 "cmmdsdReservedSize": "Memory reserved for cmmdsd.",
 "vsanmgmtdConsumedSize": "Memory used by the vSAN management daemon, which answers the API calls this pack itself makes.",
 "epdConsumedSize": "Memory used by <b>epd</b>, which handles object distribution.",
 "osfsdConsumedSize": "Memory used by <b>osfsd</b>, the object filesystem daemon that presents vSAN objects as namespaces.",
 "vsandevicemonitordConsumedSize": "Memory used by the device monitor, which watches disks for failure and degradation.",
 # ---- host CPU -----------------------------------------------------------
 "pcpuUsedPct": "Proportion of this physical CPU that was used. Listed per CPU rather than per host, so a single hot CPU is visible instead of averaged away.",
 "pcpuUtilPct": "Proportion of this physical CPU that was utilised. Differs from used where frequency scaling or hyperthreading is in play; read the two together.",
 "coreUtilPct": "Utilisation of the physical core this CPU belongs to. A core near saturation while its CPUs look moderate is hyperthread contention.",
 # ---- borrowed from the vCenter adapter ---------------------------------
 "net|errorsRx_summation": "Inbound errors summed across <b>every</b> uplink on the host, counted by vCenter rather than by this pack. This pack only measures uplinks that carry vSAN traffic, which on this cluster is two of four per host, so a standby uplink going bad is invisible to it. This column is here to close that gap.",
 "net|droppedRx_summation": "Inbound packets dropped across every uplink on the host.",
 "net|errorsTx_summation": "Outbound errors across every uplink on the host.",
 "net|droppedTx_summation": "Outbound packets dropped across every uplink on the host.",
 "net|usage_average": "Total host network throughput, all uplinks and all traffic types. Context for the error columns and a check on whether vSAN is a large or a small share of what this host is doing.",
 "cpu|usage_average": "Host CPU usage from vCenter. On the screen so that vSAN latency can be read against host load: a saturated host produces vSAN latency that is not a vSAN problem.",
 "cpu|capacity_contentionPct": "Proportion of time virtual machines waited for CPU. <b>This, not usage, is the contention signal</b> -- a host can be busy without anything waiting, and can make things wait while looking only moderately busy.",
 "mem|host_usagePct": "Proportion of host memory consumed.",
 "mem|swapinRate_average": "Rate at which the host is reading memory back from disk. <b>Any sustained non-zero value is serious</b>: it means memory was overcommitted far enough to page, and every latency figure on every other panel becomes unreliable while it continues.",
 "sys|uptime_latest": "Host uptime. Relevant here because many counters in this pack are cumulative since boot, so a recently rebooted host has small totals for reasons that have nothing to do with health.",
 # ---- vSAN service health, from vCenter ---------------------------------
 "Sensor|status": "Overall hardware sensor health, as the host's own sensors report it. This replaced a set of vSAN daemon liveness columns that could not be displayed: those carry a current value but <b>no retained history</b>, and a view queries a time range, so every cell came back blank.",
 "vcfHealth|connectivity|criticalCount": "Count of critical connectivity findings against this host. A tripwire rather than a diagnosis -- it tells you something is wrong and not what.",
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
