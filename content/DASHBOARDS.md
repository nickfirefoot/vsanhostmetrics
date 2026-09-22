# Dashboard and alerting design

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
| `vmware_host_cpu` | 65 | 4 | Per-CPU utilisation |
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
which makes the collision a plain bug rather than a debatable modelling choice.

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
- Per-CPU utilisation

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

Needed because the pack is per-host and the questions are usually per-cluster:

- Cluster-wide TCP retransmit percentage — max and average across hosts
- Cluster-wide RDT latency — max across hosts, since one slow host is the
  problem, not the average
- Worst heap usage ratio across all heaps on a host, collapsing 31 objects into
  one number worth alerting on

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
