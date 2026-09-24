# Dashboard and alerting design

> **Sections below "What we have to work with" describe the retired host-scrape
> model** (`vmware_esx_*` resource kinds) and are kept for the threshold and
> HCIBench research in them. The current model is the Performance Service one;
> see "Rapid dashboards" immediately below and the metric reference in
> `README.md`.

## Rapid dashboards

A *rapid* dashboard answers one question -- "is this subsystem bad right now?"
-- across every object at once. It is explicitly **not** for root cause. Its job
is to catch **grey-state failure**: the partial, degraded condition that leaves
everything nominally up.

That framing decides the metric selection, and it argues against the obvious
choice. A NIC dropping 0.1% of frames still moves traffic at line rate, so a
dashboard built from throughput and latency shows green through the exact
failure it exists to catch. **Rapid dashboards are built from error, loss and
congestion signals; throughput appears only as context.**

**Naming: `Rapid <domain> <subject>`.**

```
Rapid vSAN Network      Rapid vSAN Disk        Rapid vSAN Backpressure
Rapid vSAN Capacity     Rapid vSAN Resync      Rapid vSAN Memory
```

Three reasons, in order of how much they matter:

1. **Typing "rapid" surfaces the whole family.** Under pressure nobody
   navigates a folder tree; they type three letters. These are the screens
   someone opens when something is already wrong.
2. **The domain segment keeps families distinct as more packs arrive.** A
   separate network-statistics pack contributes `Rapid Network ...` without
   colliding, and typing "rapid vsan" narrows to this one.
3. They sort together in the dashboard list.

Keep the prefix even when it reads redundantly inside a vSAN-only pack. The
convention is for the operator's search box, not for this repository.

Shared shape:

- One heatmap per signal family, every object as a cell. Non-zero is the catch.
- No drill-down, no topology, no time-series-per-object. Those are cause tools.
- Sorted so the worst cell is top-left; an all-green screen is the normal state.

### 1. Network rapid — READY

| Panel | Metrics | Catches |
|---|---|---|
| pNIC hardware errors | `rxCrcErr`, `rxFrmErr`, `rxLgtErr`, `rxOvErr`, `rxFifoErr`, `txCarErr`, `txWinErr`, `txHeartErr`, `txAbortErr` | bad cable, bad optic, bad port, failing NIC |
| Ring overrun | `rxMissErr` | NIC being overrun -- ring had no descriptor |
| Drop/discard rates | `portRxDrops`, `portTxDrops`, `rxPacketsLossRate`, `txPacketsLossRate`, `ioChainRxdrops`, `ioChainTxdrops` | loss above the driver |
| Fabric backpressure | `pauseCount`, `pfcCount` | congested fabric rather than broken NIC |
| TCP health | `tcpRcvoopackRate`, `tcpTxRexmitRate`, `tcpRcvdupackRate`, `tcpRxErrRate` | path quality, reordering, retransmission |
| Context (small) | `rxThroughput`, `txThroughput` | is this link even carrying traffic |

Resource kinds: `VsanPnic` (per vmnic), `VsanHostNet`, `VsanTcpIp`, `VsanVnic`.

Note the drop/discard and pause metrics are **per-mille**; see `BACKLOG.md`.
A value of 1 is 0.1%, which is already Broadcom's warning threshold for
out-of-order. Do not read them as packet counts.

### 2. vSAN backpressure rapid — READY

Congestion is vSAN's own "I am overloaded" signal and is the storage-path
equivalent of pause frames. Available on ESA through the DOM entities.

| Panel | Metrics | Catches |
|---|---|---|
| Congestion by type | `congestion`, `readCongestion`, `writeCongestion`, `unmapCongestion`, `recoveryWriteCongestion`, `segCleanerUnmapCongestion` | which layer is pushing back |
| Component/shared | `componentCongestion`, `sharedCongestion`, `resyncReadCongestion` | contention vs resync interference |
| RDT pressure | `txSbSpaceMin`, `rxSbSpaceMin`, `txCtxQMax`, `txQLatAvg`, `numReadyDelay`, `kaReset` | vSAN's own transport stalling |

Resource kinds: `VsanHostDomclient`, `VsanHostDomcompmgr`, `VsanHostDomowner`,
`VsanRdtLatency`, `VsanVnicRdtLatency`.

`kaReset` (keepalive reset) is worth a panel of its own -- RDT connections
resetting is a strong grey-state signal that survives a healthy-looking NIC.

### 3. Disk rapid — READY, but not the way you would expect

**There are no disk error counters anywhere in the Performance Service.**
Verified across `vsan-esa-disk-layer`, `vsan-esa-disk-scsifw`, `capacity-disk`,
`cache-disk`, `ddh-disk` and `disk-group`: zero metrics matching
error/fail/retry/timeout/smart/media/realloc. The service is a *performance*
service; media health is not in it.

NVMe media errors, reallocated blocks and SMART thresholds live on the host
(`esxcli storage core device smart get`). Collecting them means a second
gathering point, which `docs/COLLECTION-DESIGN.md` forbids without retiring the
overlap first. That is a deliberate decision, not an oversight.

So a disk rapid dashboard detects a sick device by **latency behaviour**, which
is how a failing NVMe actually presents before it fails outright:

| Panel | Metrics | Catches |
|---|---|---|
| Service-time outliers | `maxReadTimePerf`, `maxWriteTimePerf`, `maxReadTimeCapacity`, `maxWriteTimeCapacity` | the one slow IO a mean hides -- the strongest available signal |
| Device vs guest divergence | `latencyDevDAvg` vs `latencyDevGAvg`, `latencyDevKAvg` | queueing above the device: kernel latency rising while device latency does not |
| Physical vs vSAN layer | `latencyDevRead/Write` vs `avgLatReadCapacity`/`avgLatWriteCapacity` | isolates the drive from the vSAN layer above it |
| Queue depth | `outstandingCmdCount` | saturation |
| Context | `iopsDevRead/Write`, `throughputDevRead/Write` | is it even being asked to do work |

Resource kinds: `VsanEsaDiskLayer`, `VsanEsaDiskScsifw`, both per physical disk
with the disk named `NVMe <model> <serial> (<host>)`.

The tell for a dying NVMe is `maxWriteTimePerf` spiking while median latency and
IOPS stay flat. A mean-based panel will not show it; use max, and compare each
disk against its siblings on the same host rather than a fixed threshold.

### 4. HBA / OSA rapid — BLOCKED, schema exists

The OSA entity types are advertised and modelled but return nothing on an ESA
cluster, so none of this can be built or tested on `example.com`:
`disk-group` (38 metrics), `capacity-disk` (13), `cache-disk` (8),
`ddh-disk` (10), `clom-disk` (3).

They are the right source when an OSA cluster is available. The OSA grey-state
signals are different from ESA's and better: `disk-group` carries
`diskgroupCongestionReadSched`/`WriteSched`, `componentCongestionReadSched`,
`iopsDelayPctSched` and `latencySched`, plus a full resync breakdown by *reason*
(`...Decom`, `...FixComp`, `...Policy`, `...Rebalance`). `capacity-disk` adds
`deleteCongestion` and both physical- and vSAN-layer latency on the same object,
and `ddh-disk` adds `logCongestion`.

Still no error counters -- same conclusion as ESA.

**Blocked on:** an OSA cluster to generate data against. Until then the model
entries are unverified.

### 5. File services — BLOCKED, and thin

`vsan-file-service` exists in the schema with **8 metrics**: `readLatency`,
`writeLatency`, `readOpTotal`, `writeOpTotal`, `readRequested`,
`writeRequested`, `readTransferred`, `writeTransferred`. Silent here because
file services are not enabled.

Requested vs transferred bytes is the one genuinely interesting pair -- a
persistent gap means the protocol layer is not delivering what was asked for.
Otherwise this is a performance view, not a health one: no share, quota,
session, protocol-error or NFS/SMB-specific metrics at all. A file services
rapid dashboard is possible but will be weak.

Related and also silent: `vsan-iscsi-host`, `vsan-iscsi-target`,
`vsan-iscsi-lun` (10 metrics each, IOPS/bandwidth/latency plus `queueDepth`).

**Blocked on:** enabling file services on a cluster.

### 6. S3 / object store — NOT AVAILABLE

Searched all 69 advertised entity types and all 839 documented metric ids,
names and descriptions for `s3`, `bucket`, `object store`, `objectstore`.
**Zero matches.** Nothing in this Performance Service version corresponds to an
object store.

If a future release adds it, the expected shape is a new entity type appearing
in `VsanPerfGetSupportedEntityTypes`. `tools/model_from_perfsvc.py` regenerates
the model from a live service, so it would be picked up by re-running it
against a cluster on that release -- the pack does not need code changes to
*discover* new entity types, only to name and label them.

### Other candidates worth considering

- **Resync / rebuild rapid.** `VsanHostDomowner` carries 71 resync-related
  metrics including `numPendingDecomResyncJobs`, `avgResyncParallelism` and
  `numInflightPriorityResyncJobs`. Answers "is this cluster rebuilding, why,
  and is it keeping up" -- the question after a host or disk drops out.
- **Capacity rapid.** `VsanClusterCapacity` is only 6 metrics (`total`, `used`,
  `free`, `dedupRatio`, `savedByDedup`, `totalDpOverhead`) but capacity
  exhaustion is the failure that takes a cluster read-only.
- **Memory / heap rapid.** `VsanMemory` (50 metrics) and `VsanSystemMemory`.
  Heap exhaustion is a classic grey failure: everything works until an
  allocation fails.


Groundwork for the content that ships in the pak's `content/` directory.
Nothing here is built yet — this is the plan, written before the panels so the
metric model can be checked against what the dashboards actually need.

Metrics with no symptoms attached are just storage. This is gap #3 in
`README.md`, and at 385 metrics across 16 resource kinds it stops being
optional: nobody navigates that by hand.

## What we have to work with

Per host, from `app/model.py`:

| Resource kind | Obj/host | Metrics | Answers |
|---|---|---|---|
| `vmware_esx_tcppkt` | 1 (per stack) | 11 | Is the TCP layer healthy? Retransmits, out-of-order, duplicate ACKs |
| `vmware_esx_pnic` | 2 (per vmnic) | 6 | Is the physical NIC dropping or erroring? |
| `vmware_esx_rdt` | 1 | 2 | RDT round-trip latency, checksum mismatches |
| `vmware_vsan_rdt` | 1 | 2 | RDT throughput |
| `vmware_vsan_dom` | 1 | 80 | The vSAN IO path: IOPS and latency by io_type, role, sink |
| `vmware_vsan_cmmds` | 1 | 33 | Cluster directory health: heartbeats, update latency |
| `vmware_vsan_memory` | 1 | 62 | Memory by type |
| `vmware_vsan_esa` | 9 | 162 | ESA internals, splinter DB |
| `vmware_esx_heap` | 31 | 1 | Heap exhaustion risk |
| `vmware_vsan_heap` | 31 | 5 | Heap exhaustion risk |
| `vmware_esx_slab` | 62 | 2 | Slab exhaustion risk |
| `vmware_host_cpu` | 65 | 4 | Per-CPU utilization |
| `vmware_esx_world` | 167 | 3 | Per-world CPU — the churning majority of objects |
| `vmware_vsan_vscsi` | 16 | 6 | Per-VM virtual SCSI |
| `vmware_vsan_vdisk` | 2 | 5 | Per-vdisk |
| `vmware_vsan_disk` | 2 | 1 | Physical disk |

Metric keys carry `|` separators, so Operations renders a tree —
`total` → `rx`/`tx` — rather than 385 flat entries. Dashboards should lean on
that hierarchy rather than fighting it.

## Reference: how HCIBench presents these metrics

HCIBench ships ~142 Grafana dashboards built against vSAN's internal stats
(`vmware-labs/hci-benchmark-appliance`, under
`HCIBench/automation/conf/grafana/dashboards/humbug/`). It is the closest thing
to an authoritative answer on which of these metrics matter and how to group
them, so it is worth copying the shape rather than inventing one.

**Important caveat: it is a different data source.** Those dashboards query
InfluxDB against vSAN Observer's metric set — `tcpRxPackets`, `tcpSndacks`,
`tcpBadsyn`, `tcpConndrops` — which is richer than what `/vsanmetrics` exposes.
The queries cannot be lifted. The panel design can.

### What it independently confirms

**rx and tx are always separate series.** Every networking dashboard pairs
`rxPackets`/`txPackets` and `rxThroughput`/`txThroughput` in one panel. That is
exactly the split the `io_type` fix introduced, arrived at independently —
which makes the collision a plain bug rather than a debatable modeling choice.

**Error and drop ratios are shown in per-mille, not percent.** Every such panel
is titled "(per-mille)". These values are tiny — our measured `duplicateAckPct`
was 0.122% — and per-mille reads better at that magnitude.

We keep **percent** anyway, because Broadcom's published thresholds are stated
in percent (0.1% / 0.5% / 1.0% for out-of-order). Matching the threshold units
matters more than readability; a symptom definition written against a number in
different units is a bug waiting to happen. Worth revisiting if we ever publish
our own thresholds.

**Latency panels come in avg / max / min triples.** The RDT dashboard shows all
three separately, because with latency the maximum is the interesting number —
one slow host is the problem, not the average across hosts. Relevant to the
supermetrics below.

### Panel structure worth copying

| Dashboard | Panels, in order |
|---|---|
| Physical NIC | Packets/sec · Throughput · Error rate · vSwitch port drops · IO chain drops · Flow control |
| TCP/IP | Packets/sec · Throughput · Connections · Transmission · Errors · Congestion |
| Host | Packets/sec · Throughput · Discards · Port drops · IO chain drops · TCP rexmit rate · TCP rx error rate |

Units: `binBps` for throughput, `µs` for latency, `short` for counts and ratios.

### What we can and cannot reproduce from `/vsanmetrics`

| Panel | Ours? | Notes |
|---|---|---|
| Packets/sec | ✅ | `total\|rx`, `total\|tx` on `EsxTcpIp`; `pkt_total\|rx/tx` on `EsxPnic` |
| Throughput | ✅ | `bytes_total\|rx/tx`, `pkt_bytes_total\|rx/tx` |
| NIC error rate | ⚠️ partial | we have `pkt_err_total\|rx/tx` only — no CRC, carrier, FIFO or missed-error breakdown |
| TCP transmission | ✅ | dup ACKs, dup packets, out-of-order, retransmits, all three SACK counters |
| RDT latency | ⚠️ partial | `latency_us` only — no min/max, no socket space, no queue depth |
| TCP connections | ❌ | no conndrops, keepalive timeouts, or connect counts in the exposition |
| TCP errors | ❌ | no badsyn, badrst, bad checksum, short packets |
| TCP congestion | ❌ | no zero-window or ECN counters |
| vSwitch / IO chain drops | ❌ | not exposed |
| Flow control | ❌ | no pause or PFC counters |

So roughly half of HCIBench's networking panels are reachable. The gaps are all
because `/vsanmetrics` exposes less than vSAN Observer does, not because of
anything in this adapter — worth stating plainly when someone asks why our
dashboard is thinner.

### One concrete improvement to adopt

HCIBench derives rate-of-total ratios for **seven** TCP counters, not four:
retransmits, duplicate ACKs, out-of-order, duplicate packets, **plus all three
SACK counters** (`sackSendBlocksRate`, `sackRcvBlocksRate`,
`sackRexmitsRate`). We currently derive four. Adding the three SACK ratios is
cheap and matches the reference.

## Proposed dashboards

Ordered by how often someone will actually open them.

### 1. vSAN Network Health
The original purpose of this pack, and the one with real thresholds behind it.

- TCP retransmit / out-of-order / duplicate-ACK percentages, per host, heat map
- Physical NIC throughput and error rate, per vmnic
- RDT round-trip latency, per host
- RDT checksum mismatches — should be flat zero; any movement is a finding

Feeds from `tcppkt`, `pnic`, `esx_rdt`, `vsan_rdt`. Low cardinality, so this
works at any site size.

### 2. vSAN IO Path
- DOM IOPS and latency split by `io_type` (read/write/unmap/recoveryWrite/
  resyncRead) and `role` (client/owner/component)
- Resync traffic called out separately — it is the usual explanation for
  latency that looks unexplained
- Per-vdisk and per-VM vSCSI for drill-down

Feeds from `vsan_dom`, `vsan_vdisk`, `vsan_vscsi`, `vsan_disk`.

### 3. Host Resource Pressure
- Heap and slab usage ratios, worst-N across hosts
- Memory by type
- Per-CPU utilization

Feeds from `esx_heap`, `vsan_heap`, `esx_slab`, `vsan_memory`, `host_cpu`.
Heap and slab exhaustion is the interesting signal — these are the counters
that explain "vSAN stopped accepting IO" after the fact.

### 4. Cluster Services
- CMMDS update latency and heartbeat misses
- Heartbeat soft timeouts — an early warning for partition

Feeds from `vsan_cmmds`.

### 5. ESA Internals
Deliberately last. 162 metrics of splinter DB detail that matter during a
support case and never otherwise. Build it when a case needs it.

## Symptom definitions

The only thresholds we have on authority are Broadcom's, for TCP, currently in
`app/constants.py`:

| Metric | Warning | Immediate | Critical |
|---|---|---|---|
| `outOfOrderPct` | 0.1% | 0.5% | 1.0% |
| `retransmitPct` | — | — | 0.5% |
| `duplicateAckPct` | — | — | 1.0% |

**These cannot be used until the denominator is fixed.** See `BACKLOG.md`: the
percentages currently divide receive-side events by a transmit-side packet
count. Alerting on them today would fire on nothing meaningful.

Everything else needs baselining before a threshold can be honest. The useful
first move is not to invent numbers but to collect for a fortnight and use
Operations' own dynamic thresholds, then promote the ones that prove stable
into static symptom definitions.

Exceptions — metrics where any non-zero value is worth a symptom regardless of
baseline:

- RDT checksum mismatches
- CMMDS heartbeat misses and soft timeouts
- pNIC error counters

## Supermetrics

The pack collects per host (and per heap, per NIC, per world); the questions
people ask are per cluster. Supermetrics bridge that.

**Prefer max over average.** HCIBench's RDT dashboard shows latency as separate
avg / max / min panels, and the max is the one that matters: one slow host is
the problem, and averaging across hosts hides it. Same for every "worst of N"
rollup below - a host with 61 healthy heaps and one at 98% should alert, and
its average will not.

| Name | Rolls up | Why |
|---|---|---|
| `clusterMaxRetransmitPct` | max `retransmitPct` across `EsxTcpIp` | The TCP ratio with a published threshold |
| `clusterMaxOutOfOrderPct` | max `outOfOrderPct` across `EsxTcpIp` | Broadcom thresholds are per host; this makes them cluster-visible |
| `clusterMaxRdtLatency` | max `latency_us` across `EsxRdt` | One slow host defines cluster behavior |
| `clusterAvgRdtLatency` | avg `latency_us` across `EsxRdt` | Baseline to read the max against |
| `hostWorstHeapUsage` | max `usage_ratio` over that host's `EsxHeap` + `VsanHeap` | Collapses 62 objects per host into one alertable number |
| `hostWorstSlabUsage` | max over that host's `EsxSlab` | Same, for slabs |
| `clusterRdtChecksumMismatch` | sum `checksum_mismatch_count` across `EsxRdt` | Should be flat zero; any movement is a finding |

Expected syntax, following Operations' supermetric form:

```
max(${adaptertype=VsanHostMetrics, objecttype=EsxTcpIp, metric=retransmitPct})
```

**Unverified.** That is the documented shape, but neither the syntax nor the
file format for shipping supermetrics in a pak has been tested here - the SDK
scaffolds `content/supermetrics/` with no schema, unlike `alertdefs` and
`traversalspecs` which both ship an `.xsd`. Build the first one in the UI,
export it, and use that as the template. Do not hand-write the XML from a
guess.

**Depends on the `HostSystem` relationship.** A cluster-scoped rollup needs
Operations to know which hosts belong to which cluster. These objects are
currently an island, so "across the cluster" has nothing to resolve against.
Until that is fixed, rollups can only be scoped by custom group or adapter
instance - which works, but is manual. That makes the relationship a
prerequisite for this section rather than a nice-to-have.

## Where the metrics we cannot reach actually live

Worth knowing before anyone tries to find them in `/vsanmetrics`: they are not
there, and no amount of parsing will surface them.

HCIBench collects via **Telegraf's vSphere input plugin against vCenter's
SDK**, reading the **vSAN Performance Service**
(`HCIBench/automation/conf/vsphere_template.conf`):

```
[[inputs.vsphere]]
  vcenters = ["https://<vcenter-ip>/sdk"]
  vsan_metric_include = [
     "performance.vsan-host-net",    # the TCP stats
     "performance.vsan-pnic-net",    # physical NIC
     "performance.vsan-vnic-net",    # virtual NIC
     "performance.host-memory-heap",
     "performance.host-cpu", ...
  ]
```

`run_telegraf.rb` skips any cluster where the Performance Service is not
enabled, which tells you how hard the dependency is.

**This is the same source as vCenter's "Performance for Support" UI.** So a
like-for-like equivalent of that UI needs this API, not the host endpoint.
`derive_percentages()` already hinted at it - its original docstring suggested
finding an rx-only counter "from the vsan-vnic-net entity via /vsanperf".

| | `/vsanmetrics` (this pack) | vSAN Performance Service |
|---|---|---|
| Path | ESXi host directly | vCenter SDK |
| Requires vCenter | No | **Yes** |
| Requires Performance Service | No | **Yes**, plus a stats object consuming vSAN capacity |
| Credential | cluster-wide bearer token | vCenter account |
| Breadth | 155 metric names | substantially more |
| Survives vCenter outage | **Yes** | No |

These are complementary rather than competing. The host scrape is the
always-available floor - it keeps working when vCenter is down, which is
exactly when you want network telemetry. The Performance Service is what makes
a Performance-for-Support equivalent possible. A mature pack probably wants
both, and that is an architectural decision, not a backlog item.

Note `HANDOFF.md` fence #2 lists destructive `VsanPerformanceManager` methods
to avoid, which implies the read methods were always considered in scope.
## Pack health: watching the Cloud Proxy

The adapter instance object (`VsanHostMetrics_adapter_instance`, named after
your account) already carries everything needed, generated by Operations. No
new metrics required - this dashboard is pure assembly.

It matters more than usual here because the schema went from 1 object per host
to ~494, and a Cloud Proxy is often deployed at the smallest size.

### Measured baseline, 2026-09-22

Four hosts, from the build host with the real adapter code:

```
8,698 samples -> 2,067 objects in 3.38s   = 1.1% of the 300s interval
python heap peak   9.9 MB
process max RSS   50.5 MB   (container limit 1024 MB)
rate cache file    1.15 MB
result payload     1.87 MB per collection  (0.47 MB per host)
```

**The adapter is not the constraint.** 50 MB against a 1 GB limit, three
seconds against a five-minute interval. What scales is the payload and the
object count: 0.47 MB and 494 objects *per host*, so a Cloud Proxy serving 64
hosts ships ~30 MB per collection and registers ~31,600 objects.

### Counters to watch, and what they mean

| Metric | Baseline | Watch for |
|---|---|---|
| **Data Collection Duration (ms)** | ~3,400 at 4 hosts | The single best health signal. Scrapes are sequential, so it grows linearly with host count. Approaching the 300s interval means collections overlap and start being skipped |
| **Docker \| Memory \| Usage (%)** | ~5% of 1024 MB | Steady growth between restarts suggests a leak; the rate cache is the only thing that grows unboundedly |
| **Docker \| Memory \| Limit (MB)** | 1024 | Raise via `container_memory_limit` if usage approaches it |
| **Docker \| CPU \| Usage (%)** | low | Parsing is the bulk of the work and is CPU-bound |
| **Docker \| Restart count** | 0 | **Any increase is a crash.** Also means the rate cache was lost, so that cycle emits no rates |
| **Docker \| Availability** | 1 | Container not running |
| **Number of Objects Collected** | ~494 per host | A step down means a host stopped responding - `collect()` skips failed hosts rather than failing the collection, so this is how a partial failure shows up |
| **Number of Metrics Collected** | ~2,200 per host | Same signal, finer grained |
| **Number of No Data Receiving Objects** | **non-zero, noisy** | See the caveat below |
| **Number of Objects Reported as Not Existing** | **non-zero, noisy** | See the caveat below |

### The world-churn caveat

`vmware_esx_world` objects are processes. They appear and vanish between
collections, so **"No Data Receiving" and "Not Existing" will never be zero and
will fluctuate constantly** - 267 objects per host of legitimate churn. Do not
alert on them as they stand.

If those counters turn out to be useful, the fix is the per-family collection
toggle in `BACKLOG.md`: switching `world` off takes a host from 494 objects to
227 and makes the churn counters meaningful again.

### Cloud Proxy VM itself

Separately, from the vCenter adapter's `VirtualMachine` object for the proxy:
CPU ready time, memory ballooning/swap, and datastore latency. A proxy that is
CPU-starved shows up there long before it shows up as collection duration,
because the adapter will simply take longer without erroring.

## Open dependencies

1. **The `io_type` denominator fix** — blocks every TCP symptom definition.
2. **No relationship to `HostSystem`** — dashboards cannot pivot from a host in
   the vCenter adapter to these objects. This is the single biggest usability
   gap, bigger than any missing panel.
3. **Counter versus gauge classification** — a rate computed from a gauge is
   meaningless, and a dashboard showing it looks authoritative anyway.
4. **Per-family collection toggles** — a 500-host site probably does not want
   167 per-world objects per host. Dashboards should degrade gracefully when a
   family is switched off.

## Build order

1. Fix the denominator, then ship the TCP symptom definitions — the only
   alerting we can justify from published thresholds
2. vSAN Network Health dashboard
3. `HostSystem` relationship, so any of it is navigable
4. Supermetrics for cluster rollups
5. Everything else, driven by what people actually ask for
