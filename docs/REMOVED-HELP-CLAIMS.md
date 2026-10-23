# Help-text claims removed from the shipped pack, awaiting a source

Written 2026-10-23. Everything below used to be customer-facing text in the
dashboard help panels. It was taken out because it was a reading from one
environment, the history of the pack, advice, or interpretation that has no
source. **None of it is known to be wrong. None of it is known to be right.**

To reinstate a claim, find a source (Broadcom documentation, the Performance
Service schema, a reproducible measurement recorded in this repository) and
put the source next to it. `test_shipped_help_text_carries_no_notes_or_unsourced_claims`
will fail on wording of this kind, so a claim cannot return by accident.

Generated from the before and after text; the headings are the metric keys.

## Per-metric notes

### `model`

**Was:** The drive's model string as the controller reports it. Two drives that look identical in a slot list can be different parts; this is what distinguishes them.

**Now:** The drive's model string as the storage controller reports it.

### `firmware`

**Was:** The drive's firmware level, read from the device rather than from any inventory. This is the first question asked about one slow NVMe drive among identical peers, and the vSAN Performance Service cannot answer it &mdash; none of its counters carry a firmware level, so this comes from vCenter's view of the device. A single drive at a different level from its peers is worth knowing before you start reading latency columns.

**Now:** The drive's firmware revision, read from the device through vCenter. The vSAN Performance Service does not report firmware.

### `driver_version`

**Was:** The controller driver's version string, e.g. 1.4.0.8-2vmw.911.0.25714478. This is the field a support case asks for, and the one a known-bad driver is identified by -- the module name alone cannot distinguish a working build from a broken one. It comes from the HCL section of the cluster health summary rather than from the device, so it is blank if that summary is unavailable while the driver name is still reported.

**Now:** The version string of the controller's driver, taken from the HCL section of the cluster health summary. Blank when that summary is unavailable; the driver name is still reported.

### `driver`

**Was:** The ESXi driver bound to the controller this drive sits behind, not to the drive itself. Several drives usually share one driver, so a driver difference points at a controller or a host, not at a disk. Blank means the storage topology could not be walked on that host; the drive's own firmware is still reported.

**Now:** The ESXi driver module bound to the storage controller this drive sits behind. It belongs to the controller, so drives behind the same controller show the same driver. Blank when the host's storage topology could not be read; the drive's firmware is still reported.

### `readyPct`

**Was:** Time vSAN's own threads spent RUNNABLE but waiting for a physical CPU. Not shown on the CPU screen, because vSAN returns 0.0 for it in every sample -- measured over 37 consecutive 5-minute buckets straight from the API, alongside usedPct, runPct, avgUsedPct and avgRunPct, all of which are likewise always zero on this vSAN build. It is still collected, so it will appear if a later build starts populating it.

**Now:** Percentage of ready CPU time for vSAN's threads: time they were ready to run but had not been given a physical CPU. Reported by the vSAN Performance Service.

### `maxRunPct`

**Was:** The highest run percentage observed in the interval, across vSAN's threads. One of only two CPU figures vSAN populates. Read it beside Max Used: a gap between them points at scheduling overhead rather than work.

**Now:** Highest running-CPU percentage for vSAN in the interval.

### `usedPct`

**Was:** Physical CPU consumed by vSAN's threads. Always 0.0 on this vSAN build and therefore not on the screen -- use Max Used instead.

**Now:** Percentage of used CPU time for vSAN, as reported by the vSAN Performance Service.

### `runPct`

**Was:** Time vSAN's threads spent executing. Always 0.0 on this vSAN build and therefore not on the screen -- use Max Run instead.

**Now:** Percentage of running CPU time for vSAN, as reported by the vSAN Performance Service.

### `maxUsedPct`

**Was:** Peak physical CPU consumed by vSAN's threads in the interval. This and Max Run are the only two CPU figures vSAN actually populates; the plain and average variants return zero in every sample. On an otherwise light cluster it sits at 3 and peaks at 7, which fits a share of the WHOLE HOST under vSAN's thread cap rather than a share of vSAN's own slice -- but that denominator is inferred, not confirmed. A load test driving it past 100 would settle it.

**Now:** Highest used-CPU percentage for vSAN in the interval.

### `txCtxQMax`

**Was:** The high-water mark of bytes queued for transmit on an RDT context. A rising maximum alongside a healthy average means the transport is bursting into its headroom rather than sitting in it -- the early signal, before queue latency moves. Read it next to txSbSpaceMin: a high maximum with a low buffer minimum is a transport running out of room, and no amount of disk tuning will help.

**Now:** Maximum outbound RDT context bytes over the last 5 seconds.

### `componentCongestion`

**Was:** Congestion raised against a single component -- one object's share of one device. Isolated to one component on one host it points at that DEVICE. Compare it with shared congestion on the same row: component high and shared low means the device, both high means the host.

**Now:** Congestion raised against a single component. Shown beside shared congestion on the same row.

### `sharedCongestion`

**Was:** Congestion on capacity shared across the host rather than attributable to one component. High here with component congestion low means the HOST is the constraint, not any individual disk. Replacing a device on this reading changes nothing.

**Now:** Shared congestion, as distinct from congestion raised against a single component.

### `resyncReadCongestion`

**Was:** Congestion caused specifically by rebuild reads. Usually correct behaviour rather than a fault: the cluster is choosing to restore redundancy and accepting latency to do it. Self-clearing when the rebuild finishes. Act on it only if the rebuild itself is not progressing -- check the Resync screen before touching anything here.

**Now:** Congestion attributed to resync reads.

### `segCleanerUnmapCongestion`

**Was:** Congestion from the segment cleaner reclaiming space. On ESA this competes with guest IO and with rebuild traffic for the same devices, so it rises when the cluster is both busy and reclaiming. Sustained high values with free capacity falling is the combination worth acting on; briefly high on its own is routine housekeeping.

**Now:** Congestion attributed to segment cleaner unmap work.

### `rxMissErr`

**Was:** The NIC's receive ring had no free descriptor, so the packet was dropped before the driver ever saw it. The clearest single sign that a NIC is being overrun. Distinct from a drop (discarded higher up) and an error (arrived damaged). Scope: this table covers vSAN-tagged uplinks only -- the Performance Service models the uplinks carrying vSAN traffic, so an uplink not carrying it, including a standby, does not appear here at all and cannot be judged from this screen.

**Now:** The NIC's receive ring had no free descriptor, so the packet was dropped before the driver saw it. Distinct from a drop (discarded higher up) and an error (arrived damaged). This table covers the uplinks the vSAN Performance Service reports on, which are the uplinks carrying vSAN traffic.

### `rxCrcErr`

**Was:** The frame arrived damaged and failed its checksum. Almost always physical: cable, connector, optic or port. Not a capacity problem. The 0.1% threshold on this column is the product's own, not a figure invented here: vCenter's alarm-261, "High pNic error rate detected", fires at 1 per mille on this counter and seven of its siblings. So the yellow band here coincides with when vSAN itself raises an alarm.

**Now:** The frame arrived damaged and failed its checksum. One of the eight counters behind vCenter's built-in alarm High pNic error rate detected (alarm-261), which is raised when the vSAN health test for any of them reports yellow or red.

### `rxOvErr`

**Was:** Receive buffer overrun. Driver-dependent and often moves with FIFO errors; both mean the receive path could not keep up.

**Now:** Receive buffer overflow errors on the physical NIC.

### `txCarErr`

**Was:** Carrier lost while transmitting -- a physical link problem. Check the port, cable and link negotiation.

**Now:** Carrier lost while transmitting.

### `portRxDrops`

**Was:** The vSwitch discarded inbound packets for this port. A small, constant rate is usually normal: broadcast and multicast traffic the switch has nowhere to deliver. A rate that changes is the signal, not its presence.

**Now:** Inbound packets dropped by the vSwitch for this port.

### `pauseCount`

**Was:** 802.3x pause frames. These are flow control -- the host and the switch asking each other to slow down. No direction is available, so a non-zero value cannot distinguish 'this host is drowning' from 'the fabric is congested'. And a zero is often meaningless: flow control has to be enabled on the uplink for the counter to move at all. Measured on the lab through network.nic.pauseParams.list: nmlx5_core uplinks have PauseRX and PauseTX on, ixgben uplinks have both off, so on every Intel uplink there a zero says nothing whatsoever. Check the uplink's pause configuration before reading this column either way.

**Now:** 802.3x pause frames, the flow control a host and a switch use to ask each other to slow down. The counter has no direction: it does not separate pause frames received from pause frames sent. Pause frames are exchanged only when flow control is enabled on the uplink; an uplink's settings can be listed with esxcli network nic pauseParams list.

### `ioChainDrops`

**Was:** Packets dropped inside the ESXi IO chain, above the NIC and below the vSwitch port.

**Now:** Packets dropped in the ESXi IO chain.

### `ioChainRxdrops`

**Was:** Inbound packets dropped inside the ESXi IO chain.

**Now:** Inbound packets dropped in the ESXi IO chain.

### `ioChainTxdrops`

**Was:** Outbound packets dropped inside the ESXi IO chain.

**Now:** Outbound packets dropped in the ESXi IO chain.

### `rxMissErrRaw`

**Was:** Lifetime count of missed receive errors since the host booted. The rate columns answer is it happening now; this answers has this NIC ever been bad. A NIC reading 0% now with thousands here has a history worth knowing.

**Now:** Cumulative count of missed receive errors. The column of the same name without Raw is the per-interval rate.

### `rxCrcErrRaw`

**Was:** Lifetime count of CRC errors since boot.

**Now:** Cumulative count of CRC errors. The column of the same name without Raw is the per-interval rate.

### `pfcCountRaw`

**Was:** Lifetime count of priority flow control frames since boot.

**Now:** Cumulative count of priority flow control frames.

### `portTxpkts`

**Was:** Packets transmitted on this vSwitch port. Context, not a fault -- an error count means nothing without knowing the traffic it happened against.

**Now:** Packets transmitted on this vSwitch port.

### `tcpTxRexmitRate`

**Was:** Segments this host had to send again because they were not acknowledged. The cost of loss somewhere on the path, paid in latency.

**Now:** Segments this host retransmitted because they were not acknowledged.

### `tcpRcvdupackRate`

**Was:** Duplicate acknowledgements received. The peer is telling us, repeatedly, that it is still missing something -- an early sign of loss on our outbound path, visible before a retransmit timer fires.

**Now:** Duplicate acknowledgements received by this host.

### `tcpRcvduppackRate`

**Was:** Duplicate packets received: the same data arrived twice, usually because a peer retransmitted something that was not actually lost.

**Now:** Duplicate packets received: data that arrived more than once.

### `tcpRcvoopackRate`

**Was:** Packets arriving out of order. Broadcom treat 0.1% as a warning and 1% as critical. Reordering alone is not loss, but TCP responds to it as though it were.

**Now:** Packets received out of order.

### `tcpSackRcvBlocksRate`

**Was:** SACK blocks received. The peer is reporting holes in what we sent it, so this points at loss on our outbound path. Appears before retransmit timeouts do.

**Now:** SACK (selective acknowledgement) blocks received.

### `tcpSackSendBlocksRate`

**Was:** SACK blocks sent. We are reporting holes in what the peer sent us -- loss on our inbound path. The mirror image of the column above, and reading the pair tells you which direction is losing.

**Now:** SACK (selective acknowledgement) blocks sent.

### `tcpSackRexmitsRate`

**Was:** Retransmissions we performed because SACK information told us precisely which segments were missing.

**Now:** Segments retransmitted on the basis of SACK information.

### `tcpTimeoutDropRate`

**Was:** Established connections torn down because the retransmission timer expired. The end state of sustained loss: the stack gave up rather than kept trying.

**Now:** Established connections dropped because the retransmission timer expired.

### `tcpHalfopenDropRate`

**Was:** Connections dropped mid-handshake, in SYN_RCVD -- a SYN arrived, the reply went out, the confirmation never came. Reads 7-9% on a healthy cluster here and the denominator is undocumented, so do not treat a non-zero value as a fault until that is understood.

**Now:** Half-open drop rate for the VMkernel network adapter.

### `tcpSndZeroWin`

**Was:** Times this host told a peer to stop sending because its receive buffer was full. Not a network fault -- the network delivered and the host could not consume. Look up the stack at CPU and at the vSAN layers, not at the wire.

**Now:** Times this host advertised a zero receive window to a peer.

### `maxLatency`

**Was:** Worst round-trip latency observed. Spikes here matter more than the average -- one stalled transfer blocks whatever was waiting on it.

**Now:** Worst round-trip latency in the interval.

### `minLatency`

**Was:** Best round-trip latency observed. Useful only as a floor to compare the average against.

**Now:** Best round-trip latency in the interval.

### `txQLatMax`

**Was:** Worst outbound queueing delay observed.

**Now:** Worst outbound queueing delay in the interval.

### `txSbSpaceMin`

**Was:** Lowest free space seen in the outbound socket buffer. Low is bad -- this measures headroom remaining, so it reads backwards from every other column. Zero means exhaustion and a stalled transport.

**Now:** Lowest free space in the outbound socket buffer in the interval.

### `kaReset`

**Was:** Lifetime count of keepalive resets: RDT gave up on a peer connection and re-established it. Cumulative since boot, so the number itself means little -- watch whether it is increasing.

**Now:** Cumulative count of RDT keepalive resets.

### `numReadyDelay`

**Was:** Lifetime count of delays waiting for a connection to become ready. Cumulative since boot; the trend is the signal.

**Now:** Cumulative count of ready delays.

### `avgLatReadCapacity`

**Was:** Read latency as vSAN sees it, above the device. Compare across disks rather than against a fixed number: the signal is one disk diverging from its peers.

**Now:** Read latency as vSAN sees it, above the device.

### `latencyDevRead`

**Was:** Read latency at the physical and firmware layer, below vSAN. Compare with the vSAN layer column: if both are high the device is slow, if only the vSAN layer is high the delay is above the disk. Product threshold 15 ms warning, 30 ms critical.

**Now:** Read latency at the physical and firmware layer, below vSAN. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.

### `latencyDevWrite`

**Was:** Write latency at the physical and firmware layer. Product threshold 15 ms warning, 30 ms critical.

**Now:** Write latency at the physical and firmware layer, below vSAN. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.

### `latencyDevKAvg`

**Was:** KAVG -- time spent queued in the VMkernel before reaching the device. High KAVG is contention, not a bad disk.

**Now:** KAVG: average time a command spends in the VMkernel.

### `latencyDevGAvg`

**Was:** GAVG -- what the guest actually experiences, being DAVG plus KAVG. Read the three together: GAVG tells you it hurts, DAVG and KAVG tell you which to fix.

**Now:** GAVG: average latency seen by the guest, equal to DAVG plus KAVG.

### `latencyRead`

**Was:** Read latency for this virtual disk, measured at the vSAN layer. Product threshold 15 ms warning, 30 ms critical.

**Now:** Read latency for this virtual disk, measured at the vSAN layer. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.

### `latencyWrite`

**Was:** Write latency for this virtual disk, measured at the vSAN layer. Product threshold 15 ms warning, 30 ms critical.

**Now:** Write latency for this virtual disk, measured at the vSAN layer. The vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical.

### `iopsRead`

**Was:** Read operations per second. Always read beside latency: high latency at high IOPS is a busy VM, high latency at near-zero IOPS is a sick one.

**Now:** Read operations per second.

### `config|name`

**Was:** The cluster name, from the vCenter adapter rather than this pack. Selecting a row here drives every other panel on the screen. This is a property, not a metric, which is why the column carries the isProperty flag.

**Now:** The cluster name, from the vCenter adapter rather than this pack. Selecting a row here drives every other panel on the screen.

### `free`

**Was:** Unused vSAN capacity. Read it next to Total, not alone: the same free figure means very different things on a 10 TB and a 1 PB cluster.

**Now:** Unused vSAN capacity.

### `dedupRatio`

**Was:** Space saving from deduplication and compression, expressed as a ratio scaled by 100 -- 134 means 1.34:1, not 134:1. A ratio that falls sharply usually means new data that does not deduplicate, not a fault.

**Now:** Space saving from deduplication and compression, expressed as a ratio scaled by 100: 134 means 1.34 to 1.

### `savedByDedup`

**Was:** Bytes not written because deduplication and compression removed them. The absolute saving behind the ratio beside it.

**Now:** Space saved by deduplication and compression, in bytes.

### `latencyAvgRead`

**Was:** Average read latency at this layer. Broadcom's own threshold for this metric is 15 ms warning and 30 ms critical, published in the Performance Service graph definition as yellow=15000 red=30000 microseconds, direction upper. That is a badly-wrong line rather than a tuning line -- a healthy cluster here runs under 1.5 ms, so the product only flags at roughly ten times normal. Compare the same column across the client, owner and component manager views: the layer where the number first becomes large is the layer to investigate.

**Now:** Average read latency at this layer. For the client, component manager and zDOM layers the vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical; it defines no threshold for the owner layer.

### `latencyAvgWrite`

**Was:** Average write latency at this layer. On ESA a write is acknowledged after it is logged, so this is usually far lower than the component manager's figure beneath it. Product threshold 15 ms warning, 30 ms critical.

**Now:** Average write latency at this layer. For the client, component manager and zDOM layers the vSAN Performance Service graph definition marks 15 ms as warning and 30 ms as critical; it defines no threshold for the owner layer.

### `latencyMaxRead`

**Was:** Worst read latency in the interval. Read beside the average: a large gap is a tail-latency problem, which guests feel as stalls even when the average looks fine.

**Now:** Worst read latency in the interval.

### `latencyMaxWrite`

**Was:** Worst write latency in the interval. Measured here at 14.9 ms against a 957 microsecond average -- a fifteenfold tail on an idle cluster, and the kind of thing an average hides completely.

**Now:** Worst write latency in the interval.

### `latencyStddevWrite`

**Was:** Spread of write latency. High spread with a low average means the work is bimodal: most operations fast, some very slow.

**Now:** Standard deviation of write latency.

### `congestion`

**Was:** vSAN's own backpressure signal, raised when a layer cannot absorb the offered load and asks the layer above to slow down. Zero on a healthy cluster, and it reads zero here. Any sustained non-zero value is the single most important number on the screen.

**Now:** vSAN congestion raised at this layer.

### `unmapCongestion`

**Was:** Backpressure attributed to unmap and space-reclamation work.

**Now:** Congestion attributed to unmap operations.

### `highOIODurationPercentWrite`

**Was:** Proportion of the interval the owner spent with its write queue above its high-watermark. Measured at 3% here on an otherwise idle cluster. This is the metric vCenter surfaces as a top-line vSAN indicator, and it moves well before average latency does.

**Now:** High outstanding IO duration for writes, as a percentage of the interval.

### `owner2PCCommitLatencyAvgUs`

**Was:** Time to commit a write across its replicas using two-phase commit. This is the irreducible cost of making a write durable in more than one place, and it sets the floor under every write latency above it.

**Now:** Average latency, in microseconds, of the owner's 2PC (two-phase commit) of a write.

### `writeLeafOwnerLatencyLocal`

**Was:** Write latency for replicas that live on this host, so no network is involved.

**Now:** Write latency for replicas on this host.

### `writeLeafOwnerLatencyRemote`

**Was:** Write latency for replicas on other hosts, which includes the network round trip. Read as a pair with the local column: remote should be the slower of the two, and when it is not, the local disks are the problem.

**Now:** Write latency for replicas on other hosts.

### `readLeafOwnerLatencyLocal`

**Was:** Read latency served from this host's own disks. Measured at 1392 microseconds here against 905 for remote reads -- local slower than across the network, which inverts the expected order and points at a local device rather than the fabric.

**Now:** Read latency served from this host's own disks.

### `readLeafOwnerLatencyRemote`

**Was:** Read latency served from another host's disks, network included.

**Now:** Read latency served from another host's disks.

### `serverSwitchCount`

**Was:** Lifetime count of ownership changes: how often coordination of an object moved from one host to another. Cumulative since boot, so the value means little; a rate that climbs means objects are being handed around, which costs latency.

**Now:** Cumulative count of server switches.

### `numNetSchedRollingAvgLatUs`

**Was:** The rolling average latency vSAN's own scheduler is working from. This is the input to its throttling decisions, not an observation of guest latency.

**Now:** Rolling average latency, in microseconds, reported by adaptive network shaping.

### `numNetSchedGuestLTLatUs`

**Was:** Guest long-tail latency as the scheduler measures it. What it is trying to protect.

**Now:** Guest long-tail latency, in microseconds, reported by adaptive network shaping.

### `numNetSchedLowBandThreshUs`

**Was:** The latency threshold at which the scheduler moves a host into its low band. Context for the band counters -- without it they are unreadable.

**Now:** Latency threshold, in microseconds, for the low band.

### `numNetSchedLowBand`

**Was:** Times the scheduler placed this host in its low band, meaning it decided latency was bad enough to throttle rebuild and resync traffic hard to protect guest IO.

**Now:** Number of times this host was placed in the low band.

### `numNetSchedMidBand`

**Was:** Times the scheduler placed this host in its middle band: some throttling, latency elevated but not severe.

**Now:** Number of times this host was placed in the middle band.

### `numNetSchedLowBandSec`

**Was:** Seconds spent in the low band. More useful than the count beside it -- one long episode and many brief ones are different problems.

**Now:** Seconds spent in the low band.

### `numNetSchedLowToMidBand`

**Was:** Transitions from the low band up to the middle band, meaning conditions improved.

**Now:** Transitions from the low band to the middle band.

### `numNetSchedMidToLowBand`

**Was:** Transitions from the middle band down to the low band, meaning conditions worsened. A host oscillating between bands is unstable in a way neither band counter alone reveals.

**Now:** Transitions from the middle band to the low band.

### `numNetSchedSeenTotalTpBps`

**Was:** Total throughput the scheduler observed, guest and rebuild traffic together.

**Now:** Total throughput observed by adaptive network shaping.

### `numNetSchedSeenNonResyncTpBps`

**Was:** Throughput excluding resync. Subtract it from the total to see what rebuild traffic is actually consuming -- the pair answers 'is the rebuild hurting the guests'.

**Now:** Throughput observed by adaptive network shaping, excluding resync traffic.

### `numNetSchedControllerIopsLimit`

**Was:** The IOPS ceiling the scheduler is currently imposing. A limit far above actual load means it is not intervening.

**Now:** Controller IOPS limit reported by adaptive network shaping.

### `vmdiskQueueDepthWrite`

**Was:** Queue depth for writes to virtual disk objects at the component manager. Depth is the cause; the latency columns are the effect.

**Now:** Queue depth for virtual disk writes at the component manager.

### `vmdiskDispatchedCostWrite`

**Was:** Accumulated cost of dispatched virtual disk writes, in vSAN's internal scheduling units. Not comparable to a time or a byte count -- useful for comparing hosts against each other, not against a threshold.

**Now:** Cost of dispatched virtual disk writes, as reported by the component manager.

### `namespaceDispatchedCostWrite`

**Was:** The same cost measure for namespace objects, which hold VM configuration rather than guest data. Large values here with small virtual disk values mean the work is metadata, not guest IO.

**Now:** Cost of dispatched writes to namespace objects, which hold VM configuration files, as reported by the component manager.

### `numPendingResyncJobs`

**Was:** Rebuild jobs queued and not yet started. The single best measure of outstanding risk: until this reaches zero, some data is below its intended redundancy.

**Now:** Resync jobs queued and not yet started.

### `numRunningResyncJobs`

**Was:** Rebuild jobs currently executing. vSAN limits concurrency deliberately, so a large pending count with a small running count is normal pacing, not a stall.

**Now:** Resync jobs currently running.

### `numSuspendedResyncJobs`

**Was:** Rebuild jobs vSAN has paused, usually to protect guest IO. Sustained non-zero here with a non-zero pending count means rebuilds are not progressing, and the cluster is staying at reduced redundancy longer than it needs to.

**Now:** Resync jobs currently suspended.

### `numInflightPriorityResyncJobs`

**Was:** Rebuilds vSAN has prioritised, which it does when data is at genuine risk rather than merely non-compliant.

**Now:** Priority resync jobs in flight.

### `numInflightSharedResyncJobs`

**Was:** Rebuilds running at normal priority.

**Now:** Shared resync jobs in flight.

### `numPendingDecomResyncJobs`

**Was:** Rebuilds queued because a host or disk is being evacuated. Non-zero means a maintenance operation is waiting on data movement.

**Now:** Pending resync jobs created by decommissioning.

### `numPendingFullResyncJobs`

**Was:** Queued rebuilds that must copy a whole component rather than a delta. These are the expensive ones.

**Now:** Pending full resync jobs.

### `numRunningFullResyncJobs`

**Was:** Full-component rebuilds currently running.

**Now:** Running full resync jobs.

### `avgResyncParallelism`

**Was:** How many rebuild operations vSAN is running at once on average. Low parallelism with a deep pending queue is the signature of throttling.

**Now:** Average number of resync operations running in parallel.

### `numCompleteResyncOps`

**Was:** Lifetime count of completed rebuild operations. Cumulative since boot; the trend tells you whether progress is being made.

**Now:** Cumulative count of completed resync operations.

### `numCompleteFullResyncOps`

**Was:** Lifetime count of completed full-component rebuilds.

**Now:** Cumulative count of completed full resync operations.

### `iopsSegCleanerUnmap`

**Was:** Operations per second performed by the segment cleaner. ESA writes to a log and must later reclaim partially-used segments; this is that housekeeping, and it competes with guest IO for the same disks.

**Now:** Operations per second performed by the segment cleaner.

### `latencyAvgSegCleanerUnmap`

**Was:** Average latency of segment cleaning work.

**Now:** Average segment cleaner unmap latency.

### `latencyMaxSegCleanerUnmap`

**Was:** Worst segment cleaning latency in the interval. Measured at 370 milliseconds here against a 1.3 millisecond average. Housekeeping stalling for a third of a second is worth knowing about, and no other screen in this pack would show it.

**Now:** Worst segment cleaner unmap latency in the interval.

### `latencyStddevSegCleanerUnmap`

**Was:** Spread of segment cleaning latency.

**Now:** Standard deviation of segment cleaner unmap latency.

### `throughputSegCleanerUnmap`

**Was:** Bytes per second the segment cleaner is moving. This is write amplification made visible: capacity the disks are spending on vSAN's own bookkeeping rather than on guest data.

**Now:** Bytes per second moved by the segment cleaner.

### `segCleanerUnmapLeafOwnerMaxLatencyAvgUs`

**Was:** Worst average latency any single replica contributed to segment cleaning. Isolates one bad disk inside an otherwise healthy cleaning cycle.

**Now:** Segment cleaner unmap leaf-owner latency: the maximum of the averages, in microseconds.

### `unmapCount`

**Was:** Lifetime count of unmap operations. Cumulative since boot.

**Now:** Cumulative count of unmap operations.

### `readLatencyMaxUs`

**Was:** Worst read latency recorded in the zDOM layer. Reads 9.7 seconds here, which is not credible as an interval maximum -- it is very likely a since-boot high-water mark that the Performance Service does not document as such. Treat a large value as unverified until the behaviour is confirmed, and use the average column for decisions.

**Now:** Worst read latency recorded in the zDOM layer, in microseconds.

### `writeLatencyMaxUs`

**Was:** Worst write latency recorded in the zDOM layer. Subject to the same caveat as the read column beside it.

**Now:** Worst write latency recorded in the zDOM layer, in microseconds.

### `unmapLatencyMaxUs`

**Was:** Worst unmap latency recorded in the zDOM layer.

**Now:** Worst unmap latency recorded in the zDOM layer, in microseconds.

### `maxDiscUsedPct`

**Was:** Highest proportion of the log structure in use. Measured at 32% here. As this climbs the segment cleaner has to work harder and write amplification rises, so it is a leading indicator for the latency columns on the segment cleaning view.

**Now:** Highest disc used percentage in the interval.

### `latAvgTotalOpIO`

**Was:** Average latency of all zDOM operations together.

**Now:** Average latency of all zDOM operations.

### `latAvgTxnBank`

**Was:** Average latency of transaction bank operations -- the in-memory staging area a write passes through before it is logged.

**Now:** Average latency of transaction bank operations.

### `rateTotalCacheRef`

**Was:** Rate of references to zDOM's metadata cache, all kinds together. Context for the breakdown columns beside it rather than a health signal.

**Now:** Rate of zDOM cache references, all kinds together.

### `rateBankFlushTotalCacheRef`

**Was:** Cache references caused by flushing the transaction bank to disk.

**Now:** Cache references from flushing the transaction bank.

### `rateSegCleaningCtxDataTotalCacheRef`

**Was:** Cache references caused by segment cleaning. Rising here while guest IOPS is flat means housekeeping is taking a larger share of the metadata path.

**Now:** Cache references from segment cleaning.

### `rateTxnPrefetchTotalCacheRef`

**Was:** Cache references from prefetching metadata ahead of need. Effective prefetch is why read latency stays low; this is the work behind that.

**Now:** Cache references from transaction prefetch.

### `rateTxnLookupCacheRef`

**Was:** Cache references from metadata lookups that could not be satisfied by prefetch.

**Now:** Cache references from transaction lookups.

### `rateTxnReadWrite`

**Was:** Ratio of read to write transactions in the zDOM layer. Characterises the workload rather than its health.

**Now:** Read-write transaction rate in the zDOM layer.

### `checkpointWorkerWakeupMs`

**Was:** Interval at which the checkpoint worker wakes to persist metadata. Steady by design; a change means configuration changed or the worker is falling behind.

**Now:** Interval, in milliseconds, at which the checkpoint worker wakes.

### `portRxpkts`

**Was:** Packets received on this kernel port. Cumulative since boot, and context for the loss rates rather than a fault in itself.

**Now:** Packets received on this kernel port.

### `rdtTxThroughput`

**Was:** Bytes per second of outbound cluster directory traffic. Small and steady by nature -- a sudden rise usually means membership churn.

**Now:** CMMDS network read outbound throughput, in bytes per second.

### `groupTxUcast`

**Was:** Unicast membership messages sent. Modern vSAN uses unicast for membership, so this is the column that should be moving.

**Now:** Unicast membership messages sent.

### `groupTxMcast`

**Was:** Multicast membership messages sent. Zero is expected on any cluster since vSAN 6.6, which moved membership to unicast. Non-zero means a legacy configuration.

**Now:** Multicast membership messages sent.

### `kernelConsumedSize`

**Was:** Memory the vSAN kernel modules are actually using. Measured at 2.14 GB against 21.0 GB reserved, so roughly a tenth of the reservation.

**Now:** Memory in use by the vSAN kernel modules.

### `clomdConsumedSize`

**Was:** Memory used by clomd, which decides where objects and their replicas are placed. Growth here tracks object count, not IO.

**Now:** Memory used by clomd, the cluster level object manager daemon.

### `vsanmgmtdConsumedSize`

**Was:** Memory used by the vSAN management daemon, which answers the API calls this pack itself makes.

**Now:** Memory used by vsanmgmtd, the vSAN management daemon.

### `epdConsumedSize`

**Was:** Memory used by epd, which handles object distribution.

**Now:** Memory used by epd, a vSAN daemon.

### `osfsdConsumedSize`

**Was:** Memory used by osfsd, the object filesystem daemon that presents vSAN objects as namespaces.

**Now:** Memory used by osfsd, the object filesystem daemon.

### `vsandevicemonitordConsumedSize`

**Was:** Memory used by the device monitor, which watches disks for failure and degradation.

**Now:** Memory used by vsandevicemonitord, the vSAN device monitor daemon.

### `net|errorsRx_summation`

**Was:** Inbound errors summed across every uplink on the host, counted by vCenter rather than by this pack. This pack only measures uplinks that carry vSAN traffic, which on this cluster is two of four per host, so a standby uplink going bad is invisible to it. This column is here to close that gap.

**Now:** Inbound errors summed across every uplink on the host, counted by vCenter rather than by this pack.

### `net|usage_average`

**Was:** Total host network throughput, all uplinks and all traffic types. Context for the error columns and a check on whether vSAN is a large or a small share of what this host is doing.

**Now:** Network throughput of the host, all uplinks and all traffic types, as reported by vCenter.

### `cpu|usage_average`

**Was:** Host CPU usage from vCenter. On the screen so that vSAN latency can be read against host load: a saturated host produces vSAN latency that is not a vSAN problem.

**Now:** CPU usage of the host, as reported by vCenter.

### `cpu|capacity_contentionPct`

**Was:** Proportion of time virtual machines waited for CPU. This, not usage, is the contention signal -- a host can be busy without anything waiting, and can make things wait while looking only moderately busy.

**Now:** CPU contention for the host: the proportion of time virtual machines waited for CPU, as reported by vCenter.

### `mem|swapinRate_average`

**Was:** Rate at which the host is reading memory back from disk. Any sustained non-zero value is serious: it means memory was overcommitted far enough to page, and every latency figure on every other panel becomes unreliable while it continues.

**Now:** Rate at which the host reads swapped memory back from disk, as reported by vCenter.

### `sys|uptime_latest`

**Was:** Host uptime. Relevant here because many counters in this pack are cumulative since boot, so a recently rebooted host has small totals for reasons that have nothing to do with health.

**Now:** Time since the host last booted.

### `Sensor|status`

**Was:** Overall hardware sensor health, as the host's own sensors report it. This replaced a set of vSAN daemon liveness columns that could not be displayed: those carry a current value but no retained history, and a view queries a time range, so every cell came back blank.

**Now:** Overall hardware sensor health, as the host's own sensors report it.

### `vcfHealth|connectivity|criticalCount`

**Was:** Count of critical connectivity findings against this host. A tripwire rather than a diagnosis -- it tells you something is wrong and not what.

**Now:** Count of critical connectivity findings against this host.

## Dashboard narratives

Narratives were rewritten against each dashboard's actual panels. Several
described panels that had been moved or removed, and one stated that
throughput was deliberately absent from a screen that carries it.

### Rapid vSAN Overview

**Heading was:** vSAN overview &mdash; which layer is broken?

- The pager went off and you do not yet know where to look. Each table below is a layer of the IO path, top to bottom, and the job of this screen is to point at one of them inside a minute. Then move to the matching detail screen.

- Normal is front end above back end. The front end carries network hops, owner coordination and policy work the disks never see, so it should read higher. The two converging, or inverting, is the anomaly &mdash; not either number on its own.

- The owner row between them is new. It is the layer that coordinates each write across its replicas, so it holds the cost of making a write durable in more than one place. When the front end is slow and the back end is not, the owner row is usually where the difference went.

### Rapid vSAN Network

**Heading was:** vSAN network &mdash; is any layer losing frames right now?

- Four layers carry vSAN traffic and each fails independently: RDT, vSAN's own transport; TCP beneath it; the vmknic, the kernel port; and the physical NIC. One panel per layer, top to bottom. This is a triage screen, not a root-cause tool &mdash; it answers whether and where, not why.

- Read down and stop at the first unhappy layer. Latency at RDT but not TCP is vSAN's own queueing. Loss at the vmknic but not the NIC is the host, not the fabric. A clean NIC proves nothing about RDT, and a clean RDT proves nothing about the NIC.

- Every rate column is the period maximum, not the current value. That is deliberate and measured: an error burst lands inside one five-minute bucket and is gone. A current value misses it almost every time you look.

- Throughput is deliberately not on this screen. A NIC discarding a fraction of a percent of frames still moves traffic at line rate, so a throughput panel stays green through the exact fault this exists to find.

- Where a threshold is the vendor's, it says so; where it is ours, it says that too. The per-mille bands on the pNIC error columns are vCenter's own: alarm-261, "High pNic error rate detected", fires at 1 per mille on eight counters. Everything else here is this pack's judgement, not a published standard.

- The two pNIC panels are not duplicates. High pNIC error rate carries only those eight alarm counters, so the screen matches what vCenter would alarm on. pNIC stats &mdash; every counter adds the drops, ioChain and lifetime columns the alarm ignores. The narrow one tells you vCenter agrees; the wide one tells you what else the NIC reports.

- Lifetime counters answer a different question from rates. The rate columns say whether it is happening now; rxMissErrRaw says whether this NIC has ever been bad. A uplink reading zero today with tens of thousands of lifetime missed errors has a history worth knowing before you call it healthy.

- What this screen cannot see. This pack measures only uplinks carrying vSAN traffic, which on a typical host is two of four, so a standby uplink going bad is invisible here &mdash; which is why the last panel comes from vCenter and counts every uplink. Pause-frame counts carry no direction, so a non-zero value cannot separate "this host is drowning" from "the fabric is congested", and a zero means nothing at all unless flow control is enabled on that uplink.

### Rapid vSAN Storage

**Heading was:** vSAN storage &mdash; is it the disk or the queue?

- This screen descends from the vSAN view of a disk to the device itself, then back up to what a guest experiences. The useful comparison is between the layers, not against any fixed threshold.

- Compare disks against their peers, not against a number. A cluster of disks at 40 microseconds and one at 500 is the finding, whatever the absolute values are. One disk here was measured at 495 microseconds of device latency against 38 to 58 for its peers, with kernel latency flat &mdash; which is a slow device, not contention.

- The guest tables at the bottom come in two forms: per vSCSI controller, which is how vSAN accounts for IO, and per virtual machine, which is the unit a ticket gets raised about.

### Rapid vSAN DOM

**Heading was:** DOM &mdash; the three layers of a vSAN write

- DOM is the distributed object manager, and it has three layers. The client is the host a guest is running on. The owner is the host that coordinates a given object's writes, which may be a different host entirely. The component manager is what talks to the disks.

- A write passes through all three, so latency accumulates downward and should read highest at the client. Reading the same column across the three tables localises a problem to one layer in a way no single table can.

- The owner layer was previously absent from every screen in this pack. It returns 272 metrics and 87 of them move on an idle cluster. Its latency maximum was measured at 14.9 milliseconds against a 957 microsecond average, a fifteenfold tail that the averages everywhere else hide completely.

- The last table is vSAN's own congestion controller. It bands hosts by observed latency and throttles rebuild traffic to protect guest IO. The band counters say whether it is intervening, which nothing else here can show.

### Rapid vSAN Backpressure

**Heading was:** Backpressure &mdash; is vSAN throttling itself, and which layer is doing it?

- Congestion is vSAN telling you it has deliberately slowed something down to protect itself. It is not an error and it is not a failure &mdash; it is a control signal, and the useful question is never is there congestion but which layer raised it and why.

- Read this screen top down. The cluster tables say whether the whole cluster is under pressure. The per-host tables say whether it is one host. The RDT tables at the bottom say whether the problem is the network transport rather than the storage at all &mdash; which is the single most commonly misdiagnosed case, because every layer above reports congestion when the transport underneath is starved.

- The congestion TYPE is the diagnosis. Read congestion and write congestion point at different causes and different fixes. Unmap congestion is space reclamation competing with guest IO. Resync read congestion means rebuild traffic is the source, which is usually correct behaviour and self-clearing &mdash; the cluster is choosing redundancy over latency, and it will stop when the rebuild does.

- Component congestion against shared congestion is the host-versus-device call. Component congestion isolated to one object points at a device; shared congestion across a host points at the host. Acting on the wrong one replaces healthy hardware.

- On the RDT tables, kaReset deserves attention out of proportion to its size. Keepalive resets mean the transport dropped and re-established, and they survive a NIC that looks perfectly healthy on every error counter. Small buffer minima (txSbSpaceMin, rxSbSpaceMin) next to a rising queue latency is the signature of a transport running out of room rather than a disk running slow.

### Rapid vSAN Resync

**Heading was:** Resync &mdash; how much risk is outstanding, and who is paying for it?

- A resync means some data is below the redundancy its policy asks for. Two questions matter and they are different: how much work is left, and what is that work costing the guests.

- Zero across the top table is the normal and desirable reading. Nothing is rebuilding, so nothing is at reduced redundancy. The IO columns beside the job counts are there so that a screen of zeros can be told apart from a screen that is not collecting.

- If jobs are pending but not running, look at the scheduler table. vSAN deliberately throttles rebuild traffic when guest latency rises, so a deep queue with low parallelism is usually correct behaviour rather than a stall &mdash; but it does mean the cluster stays at reduced redundancy for longer, and that is a risk decision somebody should be making knowingly.

- Segment cleaning sits at the bottom because on ESA it competes with rebuild work for the same disks.

### Rapid vSAN ESA Write Path

**Heading was:** ESA write path &mdash; the log, and the cost of keeping it tidy

- ESA does not write in place. It appends to a log, acknowledges the write once it is logged, and later reclaims space by cleaning partially-used segments. That makes writes fast and makes housekeeping a first-class source of latency.

- This screen exists because none of that work was visible anywhere in this pack. Worst case segment cleaning latency was measured at 370 milliseconds against a 1.3 millisecond average on an otherwise idle cluster.

- Read it top down: the zDOM tables give the layer's own latency and throughput, the write path internals show how hard the metadata and caching machinery is working, and segment cleaning shows the reclamation cost. The log fill percentage is the leading indicator &mdash; as it rises, cleaning has to work harder and write amplification goes up with it.

- One caveat, stated plainly. The zDOM maximum latency columns read in whole seconds, which is not credible as an interval maximum and is very likely a since-boot high-water mark that the Performance Service does not document as such. Use the average columns for decisions until that is confirmed.

### Rapid vSAN Host Resources

**Heading was:** Host resources &mdash; is vSAN slow, or is the host out of road?

- Every latency figure on every other screen is only meaningful if the host had capacity to spare. This screen answers that first, so the others can be trusted. It shows what vSAN itself consumes on a host &mdash; memory, CPU, network &mdash; not the host's total load, which is vCenter's to report and appears on the Overview and Network screens.

- CPU contention matters more than CPU usage, and readyPct is the headline. A host can be busy with nothing waiting, and can make things wait while looking only moderately busy. Ready time is the one that hurts: it is vSAN's threads queued for a core they did not get. Used and run percentages are context for it, not peers of it.

- This table is per host, four rows, not per core. It replaced a per-CPU table of 244 rows that carried only generic utilisation and no ready time &mdash; more rows, less answer. If you need to find a single hot core, that is a vCenter question, not a vSAN one.

- Start with service memory. A daemon that is not answering explains more than any latency number will. This pack can measure what clomd, cmmdsd and the rest consume and reserve; it cannot see whether the process is responding, so a flat line here is not the same as a healthy daemon.

- The network table is vSAN's traffic only, aggregated per host. It is the same counters the Network screen breaks out per vmknic, summed &mdash; useful here as a resource figure (what is this host moving) rather than a fault-finding one. If a number looks wrong, the Network screen has the layer detail behind it.

- What this screen cannot tell you. Nothing here reports host memory pressure or swap &mdash; those are the host's totals, not vSAN's share, and they come from vCenter. A host can be swapping hard while every figure on this screen looks calm.
