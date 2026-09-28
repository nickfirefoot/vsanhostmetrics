# Rapid vSAN dashboards — storyboard and build spec

**For whoever builds these in the Operations UI.** Every panel below is
specified down to the metric key, so nothing here requires guessing what was
meant. Where something is unverified it says so; please treat those as
questions rather than instructions.

**Panel-by-panel mockups with real measured values are in
[`DASHBOARD-MOCKUPS.md`](DASHBOARD-MOCKUPS.md)** — what each screen should
look like built, healthy and degraded, plus a baseline of what normal reads.

Build them in the UI. Do not hand-write the dashboard JSON — see
[Appendix A](#appendix-a-why-this-is-a-spec-and-not-a-file) for why.

---

## 1. What these screens are for

A **rapid** dashboard answers one question in about sixty seconds:

> Is something broken right now, and which layer is it in?

It is **not** a root-cause tool. It exists to catch **grey-state failure** —
partial degradation that leaves everything nominally green. A NIC dropping
0.1% of frames still moves traffic at line rate, so throughput and latency
look healthy through the exact fault the screen exists to find.

Two consequences that shape every layout below:

1. **Errors, loss and congestion lead. Throughput never leads.** Throughput is
   context for an error, not a signal on its own.
2. **Non-zero is the catch.** Most error counters here sit at exactly zero on
   a healthy cluster. A panel full of zeroes is the normal, good state.

---

## 2. Cluster first

The vSAN IO path is a cluster-wide object graph. A slow VM's DOM Client runs
on one host, its DOM Owner on another, its components on several more. A
host-first view fragments the thing being diagnosed.

So **every screen has one cluster selector at the top**, and every panel below
is fed from it.

What the selector reaches, measured on a live cluster (2026-09-25):

```
selected ClusterComputeResource
│
├── depth 1  our cluster-wide objects ...... DOM roll-ups (client / owner /
│                                            compmgr), RDT latency, ZDOM,
│                                            capacity, data protection
│
├── depth 1  HostSystem  (4 on the lab cluster)
│   │
│   └── depth 2  per-host objects .......... pNICs, VMkernel NICs, ESA disks,
│                                            per-host DOM, TCP/IP, memory, CPU
│
└── depth 1  ResourcePool → VMs
```

**Panels on cluster-wide objects are one hop. Panels on NICs, disks or
per-host anything are two hops.** That distinction drives the widget settings
in §3 and is the single most useful fact on this page.

---

## 3. How to build the skeleton (do this once, reuse everywhere)

### 3.1 The cluster selector

An Object List widget pins to one named cluster and only resolves on the
system it was built on, so it cannot ship. Use a **View** widget instead —
this is what Broadcom's own vSAN dashboards use.

1. **Views → Create View**
2. Name: `vSAN Clusters`
3. Subject: **Cluster Compute Resource**
4. Data: add `Configuration|Name` (transformation `Current`, no timestamp)
5. **Filter: leave empty** — so it returns every cluster, not one
6. Create

Then on each dashboard, add a **View** widget, point it at `vSAN Clusters`,
Self Provider **ON**, Select First Row **ON**.

### 3.2 The receiver widgets

Every other panel is a receiver fed by that selector:

| Setting | Value |
|---|---|
| Self Provider | **OFF** |
| Interaction | provider = the `vSAN Clusters` View widget |
| Depth / relationship | must reach **2** hops for NIC, disk and per-host panels |

**Confirmed working** on 2026-09-25: a Scoreboard with Self Provider off,
fed by a cluster selection, rendering `avgLatency` from **vSAN Cluster RDT
Latency** — a depth-1 kind. Exported at
`docs/assets/dashboard.interaction-working.json`.

### 3.1a If a panel is blank on load but fills when you change a setting

**Symptom:** the pNIC panels populate sometimes and not others, with nothing
done differently. Changing the Input Transformation depth from 2 to 3 and back
makes them appear.

**Not a data problem.** Checked against the stored series: all seven pNIC
objects hold 72 samples over six hours on an exact five-minute cadence, no
gaps, newest sample 3.5 minutes old, 100% availability, all `DATA_RECEIVING`.

**Cause:** a receiver renders nothing until the provider *fires a selection*.
The confirmed-working export has `selectFirstRow: false` on its provider, so on
dashboard load no row is selected, no interaction fires, and every receiver
below is blank. Editing any receiver setting forces it to re-resolve against
whatever selection exists by then, which is why toggling the depth "fixes" it.

**Fix: set Select First Row ON on the provider widget.** A selection then
always exists at load and the interaction fires without anyone clicking. Do
this on every screen — it is the difference between a dashboard that works and
one that works only after you poke it.

Worth checking alongside it: the Scoreboard's **Show old metric values**. The
working export has it off, and with collection and widget refresh both on 300
seconds the two drift in and out of phase, which can blank a panel for part of
each cycle. Turning it on makes a panel show the last known value rather than
nothing.

### 3.2a The working recipe — confirmed in the UI, 2026-09-28

| Setting | Value |
|---|---|
| Input Transformation | **All objects** |
| Output Transformation | **VCF world performance list** |
| Depth | **2 or more** (see below) |
| Select First Row on the provider | **ON** — see §3.1a |

**Depth is cumulative, not exact.** A depth of N includes everything at N hops
*and closer*, so anything visible at 2 is also visible at 3.

**Every pNIC metric lives on one object type at one depth.** `rxCrcErr`,
`rxMissErr`, `rxErr`, `rxFifoErr`, `rxOvErr` and `pauseCount` all belong to
`vSAN Physical NIC` and nothing else; `portRxDrops` additionally exists on
`vSAN Host Network` and `vSAN VMkernel NIC`, and those are host-scoped too. So
there is no NIC metric that sits deeper than another, and **depth 2 is enough
for all of them**.

> **An earlier version of this file claimed NIC stats resolved at depth 2 and
> buffer/CRC counters at depth 3. That was wrong** and is corrected here. It
> came from observing panels fill at one depth and not another, which was
> really the stale-resolution problem in §3.1a — changing *any* receiver
> setting forces a re-resolve, so changing the depth appeared to be what
> mattered. With Select First Row on, CRC now shows at both 2 and 3, as it
> should.

**The relationships behind depth 2 are confirmed** (2026-09-28, by walking
CHILD from the cluster through Operations' own API): depth 1 returns the 7
cluster-scoped kinds, depth 2 returns all 21 host-scoped kinds including
`vSAN Physical NIC` (7 objects) and `Vsan Esa Disk Layer` (7). So the object
graph supports every depth-2 panel in this document.

What remains unconfirmed is only the **widget setting** that makes a receiver
walk two hops rather than one. That is a configuration question, not a data
one — if a depth-2 panel comes up empty, the relationship is not the cause.

**One exception, and it is real:** 64 objects in the VM tier have no parent at
all — 10 of 30 `vSAN Virtual Machine`, 27 of 60 `vSAN Virtual Disk`, 27 of 106
`vSAN vSCSI`. They belong to vSphere Pod VMs, which Operations' vCenter
adapter does not model, so nothing can reach them by relationship. Screen 7 is
incomplete until that is fixed; see `BACKLOG.md`.

### 3.3 Widget choice

| Use | Widget |
|---|---|
| Key figures for the selected cluster | **Scoreboard**, per-metric colour bounds |
| Scanning every NIC / disk / host at once | **Heatmap**, grouped by host |
| Worst-N ranking (VMs, disks) | **Top-N** or a sorted **List** |
| The explainer panel | **Text**, one per screen |

### 3.4 House style

- Title every screen `Rapid vSAN <subject>` — typing "rapid" surfaces the set.
- Value font **10pt**, label **9pt**. Operations defaults to 24/16, which is
  sized for one big number per box; these panels carry several.
- Panels ordered **worst-first**, left to right, top to bottom.
- Every spoke screen links back to **Overview** and across to **Host**.

---

## 4. Screen-by-screen

### Screen 1 — Rapid vSAN Overview

> **The pager fires at 02:00.** The on-call engineer has no idea which layer
> is at fault. This screen's only job is to point at one of five spokes within
> a minute, then get out of the way.

All panels are **depth 1** — the proven-working case. Build this one first.

```
┌──────────────────────────────────┬──────────────────────────────────────────┐
│ CLUSTER SELECTOR (View)          │ HOW TO READ THIS (Text)                  │
│ vSAN Clusters                    │ non-zero is the catch; ratios are % ...   │
├──────────────────┬───────────────┴──────────────┬───────────────────────────┤
│ CAPACITY         │ FRONT END — what VMs feel    │ TRANSPORT — RDT           │
│ free / used      │ DOM Client latency, IOPS,    │ avg + max latency,        │
│ total, dedup     │ congestion                   │ keepalive resets          │
│                  │        → Screen 5            │        → Screen 3         │
├──────────────────┴──────────────────────────────┼───────────────────────────┤
│ BACK END — what disks are doing                 │ REBUILD ACTIVITY          │
│ DOM Comp Mgr latency, congestion                │ resync IOPS / tput / lat  │
│        → Screen 4                               │        → Screen 6         │
└─────────────────────────────────────────────────┴───────────────────────────┘
```

| Panel | Object type | Metric key | Label | Unit | Yellow / Orange / Red |
|---|---|---|---|---|---|
| Capacity | Vsan Cluster Capacity | `free` | Free Capacity | bytes | — |
| | | `used` | Used Capacity | bytes | — |
| | | `total` | Total Capacity | bytes | — |
| | | `dedupRatio` | Space Efficiency Ratio | ratio | — |
| Front end | Cluster Domclient | `latencyAvgRead` | Read Latency | µs | 2000 / 5000 / 10000 |
| | | `latencyAvgWrite` | Write Latency | µs | 2000 / 5000 / 10000 |
| | | `congestion` | Congestions | count | 1 / 10 / 50 |
| | | `iopsRead` | Read IOPS | IOPS | — |
| | | `iopsWrite` | Write IOPS | IOPS | — |
| | | `oio` | Outstanding IO | count | — |
| Transport | vSAN Cluster RDT Latency | `avgLatency` | RDT Average Latency | µs | 500 / 2000 / 5000 |
| | | `maxLatency` | RDT Max Latency | µs | 5000 / 20000 / 50000 |
| | | `kaReset` | Keepalive reset | count | **none — cumulative, see below** |
| | | `numReadyDelay` | Num ready delay | count | **none — cumulative** |
| Back end | Cluster Domcompmgr | `latencyAvgRead` | Read Latency | µs | 2000 / 5000 / 10000 |
| | | `latencyAvgWrite` | Write Latency | µs | 2000 / 5000 / 10000 |
| | | `congestion` | Congestions | count | 1 / 10 / 50 |
| Rebuild | Cluster Domcompmgr | `iopsResyncRead` | Resync Read IOPS | IOPS | — |
| | | `tputResyncRead` | Resync Read Throughput | B/s | — |
| | | `latAvgResyncRead` | Resync Read Latency | µs | 5000 / 20000 / 50000 |
| | | `iopsRecWrite` | Recovery Write IOPS | IOPS | — |

**`kaReset` deserves its own tile, but not a threshold.** A keepalive reset
means RDT gave up on a peer connection. Live sampling shows it **cumulative
since boot** -- 13 on the healthy lab cluster, flat across an hour -- so an
absolute bound would sit permanently red. Show it unbounded and alert on
**rate of change**. The same applies to `numReadyDelay` (25, flat).

**Capacity is on Overview deliberately** — exhaustion takes a cluster
read-only, which is an outage, not a performance issue.

---

### Screen 2 — Rapid vSAN Physical Network

> **Storage says the network is fine; the network team says storage is fine.**
> This screen is the referee. It speaks the network team's vocabulary — CRC,
> FIFO, carrier, ring buffer — so it can be handed over without translation.

**Depth 2.** Verify §3.2 before building.

```
┌──────────────────────────────────┬──────────────────────────────────────────┐
│ CLUSTER SELECTOR                 │ HOW TO READ THIS                         │
├──────────────────────────────────┴──────────────────────────────────────────┤
│ RING BUFFER OVERRUN — the NIC could not keep up        (Heatmap, per pNIC)  │
│ rxMissErr                                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ WIRE ERRORS — something is physically wrong   (Heatmap grid, per pNIC)      │
│ rxCrcErr │ rxErr │ rxFifoErr │ rxOvErr │ txCarErr │ txErr                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ DISCARDS — the switch or vSwitch threw traffic away                         │
│ portRxDrops │ portTxDrops │ rxPacketsLossRate │ txPacketsLossRate           │
├──────────────────────────────────┬──────────────────────────────────────────┤
│ CONGESTION — fabric, not NIC     │ TCP HEALTH            (per host)         │
│ pauseCount (802.3x)              │ tcpTxRexmitRate, tcpRxErrRate            │
└──────────────────────────────────┴──────────────────────────────────────────┘
```

| Panel | Object type | Metric key | Label | Unit | Yellow / Orange / Red |
|---|---|---|---|---|---|
| Ring overrun | vSAN Physical NIC | `rxMissErr` | pNIC RX missed error (ring buffer full) | % | 0.1 / 0.5 / 1.0 |
| Wire errors | vSAN Physical NIC | `rxCrcErr` | pNIC RX CRC Error | % | 0.1 / 0.5 / 1.0 |
| | | `rxErr` | pNIC RX Generic Error | % | 0.1 / 0.5 / 1.0 |
| | | `rxFifoErr` | pNIC RX FIFO Error | % | 0.1 / 0.5 / 1.0 |
| | | `rxOvErr` | pNIC RX Buffer Overflow Error | % | 0.1 / 0.5 / 1.0 |
| | | `txCarErr` | pNIC TX Carrier Error | % | 0.1 / 0.5 / 1.0 |
| | | `txErr` | pNIC TX Generic Error | % | 0.1 / 0.5 / 1.0 |
| Discards | vSAN Physical NIC | `portRxDrops` | Inbound Packet Drop Rate of vSwitch Port | % | 0.1 / 0.5 / 1.0 |
| | | `portTxDrops` | Outbound Packet Drop Rate of vSwitch Port | % | 0.1 / 0.5 / 1.0 |
| | | `rxPacketsLossRate` | Inbound Packet Discard Rate | % | 0.1 / 0.5 / 1.0 |
| | | `txPacketsLossRate` | Outbound Packet Discard Rate | % | 0.1 / 0.5 / 1.0 |
| Congestion | vSAN Physical NIC | `pauseCount` | pNic 802.3x Pause Rate | % | 0.1 / 0.5 / 1.0 |
| TCP health | vSAN Host Network | `tcpTxRexmitRate` | TCP TX retransmit (rate) | — | **returns no data** |
| | | `tcpRxErrRate` | TCP RX errors (rate) | — | **returns no data** |

**The two TCP metrics return no data at all** from the Performance Service --
absent, not zero (verified 2026-09-28). Build the panel since it costs
nothing and may populate elsewhere, but do not design the screen around it or
alert on it. Retransmit visibility is a genuine gap; see `BACKLOG.md`.

**Threshold source:** Broadcom's *Understanding vSAN Network TCP/IP
Expectations and Thresholds* — warning 0.1%, immediate 0.5%, critical 1.0%.
The adapter already converts these ratios from per-mille to percent, so the
published figures apply directly with no arithmetic.

**Distinctions worth putting in the text panel**, because they get conflated:

- **RX missed** — the ring buffer had no free descriptor; the packet died
  before the driver saw it. The NIC is being overrun.
- **RX dropped / discard** — discarded higher up the stack.
- **RX error** — arrived damaged.
- **Pause / PFC** — the *host asking the switch to slow down*. A congested
  fabric, not a failing NIC. Different problem, different team.

---

### Screen 3 — Rapid vSAN Transport (RDT)

> **The network screen is green and storage is still slow.** RDT is vSAN's own
> transport, above TCP. It can stall on socket buffer exhaustion or queueing
> while every NIC counter stays clean.

Cluster panel is **depth 1**; per-host panels are **depth 2**.

```
┌──────────────────────────────────┬──────────────────────────────────────────┐
│ CLUSTER SELECTOR                 │ HOW TO READ THIS                         │
├──────────────────────────────────┴──────────────────────────────────────────┤
│ CONNECTION HEALTH          kaReset  │  numReadyDelay        (cluster-wide)  │
├─────────────────────────────────────────────────────────────────────────────┤
│ LATENCY          avgLatency │ maxLatency │ minLatency        (cluster-wide) │
├─────────────────────────────────────────────────────────────────────────────┤
│ QUEUEING         txQLatAvg │ txQLatMax                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ SOCKET BUFFER HEADROOM — low MIN means exhaustion                           │
│ txSbSpaceMin │ rxSbSpaceMin │ txCtxQMax                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ PER HOST — same signals, per host and per VMkernel NIC       (depth 2)      │
│ vSAN RDT Latency  │  vSAN VMkernel RDT Latency                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Panel | Object type | Metric key | Label | Unit | Yellow / Orange / Red |
|---|---|---|---|---|---|
| Connection | vSAN Cluster RDT Latency | `kaReset` | Keepalive reset | count | **none — cumulative** |
| | | `numReadyDelay` | Num ready delay | count | **none — cumulative** |
| Latency | | `avgLatency` | RDT Average Latency | µs | 500 / 2000 / 5000 |
| | | `maxLatency` | RDT Max Latency | µs | 5000 / 20000 / 50000 |
| | | `minLatency` | RDT Min Latency | µs | — |
| Queueing | | `txQLatAvg` | Average Outbound Queueing Latency | µs | 500 / 2000 / 5000 |
| | | `txQLatMax` | Max Outbound Queueing Latency | µs | 5000 / 20000 / 50000 |
| Buffers | | `txSbSpaceMin` | Socket Min Outbound Bytes | bytes | **low is bad** |
| | | `rxSbSpaceMin` | Socket Min Inbound Bytes | bytes | **low is bad** |
| | | `txCtxQMax` | Max Outbound Context Bytes | bytes | — |
| Per host | vSAN RDT Latency | same keys | | | |
| Per VMkernel NIC | vSAN VMkernel RDT Latency | same keys | | | |

**Socket buffer panels invert.** Every other panel on every screen is "high is
bad". `txSbSpaceMin` and `rxSbSpaceMin` are *free space remaining*, so **low
is bad** — they measure headroom, and zero means exhaustion. Colour them
inverted and label them so nobody reads a small number as healthy. This is the
single most misreadable pair in the pack.

---

### Screen 4 — Rapid vSAN Disk (ESA)

> **A disk is dying but SMART says it is fine.** Look for one device whose
> *max* service time diverges from its peers, and for the physical layer
> diverging from the vSAN layer.

**Depth 2.**

```
┌──────────────────────────────────┬──────────────────────────────────────────┐
│ CLUSTER SELECTOR                 │ HOW TO READ THIS + BLIND SPOT WARNING    │
├──────────────────────────────────┴──────────────────────────────────────────┤
│ vSAN LAYER LATENCY — per disk, grouped by host          (Heatmap)          │
│ avgLatReadCapacity │ avgLatWriteCapacity                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ LAYER DIVERGENCE — vSAN layer vs perf tier                                  │
│ avgLatReadPerf │ avgLatWritePerf │ avgLatUnmapCapacity                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ LOAD — context only, never the headline                                     │
│ iopsReadCapacity │ iopsWriteCapacity │ iopsUnmapCapacity                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ SCSI FRONT END                        (Vsan Esa Disk Scsifw, 16 metrics)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Panel | Object type | Metric key | Label | Unit |
|---|---|---|---|---|
| vSAN layer latency | Vsan Esa Disk Layer | `avgLatReadCapacity` | vSAN Layer Average Read Latency | µs |
| | | `avgLatWriteCapacity` | vSAN Layer Average Write Latency | µs |
| Divergence | | `avgLatReadPerf` | Latency read perf (average) | µs — **reads 0 on every disk** |
| | | `avgLatWritePerf` | Latency write perf (average) | µs |
| | | `avgLatUnmapCapacity` | Latency unmap capacity (average) | µs |
| Load | | `iopsReadCapacity` | vSAN Layer Read IOPS | IOPS |
| | | `iopsWriteCapacity` | vSAN Layer Write IOPS | IOPS |
| | | `iopsUnmapCapacity` | IOPS unmap capacity | IOPS |

> **State this on the screen, in the text panel:**
> There are **no media-error counters anywhere in the vSAN Performance
> Service** — no reallocated sectors, no SMART, no uncorrectable errors. This
> screen infers a bad device from *timing*, not from the device admitting
> fault. A green screen here does not mean the hardware is healthy.

Latency thresholds are deliberately blank: they are workload-dependent, and
the signal is **one disk diverging from its peers**, not an absolute number.
Set the bands after a baseline run, or colour relative to the group.

---

### Screen 5 — Rapid vSAN DOM

> **Storage is slow cluster-wide.** DOM has three roles and the answer is
> nearly always "one of these three". This screen puts them side by side so
> the comparison is immediate.

Cluster roll-ups are **depth 1**; per-host breakdowns are **depth 2**.

```
┌──────────────────────────────────┬──────────────────────────────────────────┐
│ CLUSTER SELECTOR                 │ HOW TO READ THIS — what the roles are    │
├─────────────────┬────────────────┴─────────────┬───────────────────────────┤
│ CLIENT          │ OWNER                        │ COMPONENT MANAGER         │
│ what the VM     │ coordinates the write,       │ what the local disks      │
│ actually feels  │ enforces the policy          │ actually did              │
│                 │                              │                           │
│ latency R/W     │ (46 cluster metrics)         │ latency R/W               │
│ congestion      │                              │ congestion                │
│ IOPS R/W        │                              │ IOPS R/W + resync         │
│ oio             │                              │ oio                       │
├─────────────────┴──────────────────────────────┴───────────────────────────┤
│ CONGESTION BY TYPE      readCongestion │ writeCongestion │ unmapCongestion  │
├─────────────────────────────────────────────────────────────────────────────┤
│ PER HOST — the same three roles, per host                     (depth 2)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Panel | Object type | Metric key | Label | Unit | Yellow / Orange / Red |
|---|---|---|---|---|---|
| Client | Cluster Domclient | `latencyAvgRead` | Read Latency | µs | 2000 / 5000 / 10000 |
| | | `latencyAvgWrite` | Write Latency | µs | 2000 / 5000 / 10000 |
| | | `congestion` | Congestions | count | 1 / 10 / 50 |
| | | `iopsRead` / `iopsWrite` | Read / Write IOPS | IOPS | — |
| | | `oio` | Outstanding IO | count | — |
| Comp Mgr | Cluster Domcompmgr | `latencyAvgRead` | Read Latency | µs | 2000 / 5000 / 10000 |
| | | `latencyAvgWrite` | Write Latency | µs | 2000 / 5000 / 10000 |
| | | `congestion` | Congestions | count | 1 / 10 / 50 |
| Congestion by type | Cluster Domclient | `readCongestion` | Read Congestions | count | 1 / 10 / 50 |
| | | `writeCongestion` | Write Congestions | count | 1 / 10 / 50 |
| | | `unmapCongestion` | Unmap congestion | count | 1 / 10 / 50 |
| Per host | Host Domclient / Domowner / Domcompmgr | same keys | | | |

**Reading it:** Client latency high but Comp Mgr low → the problem is above
the disks (network, owner coordination, or policy). Both high → the disks. Comp
Mgr high alone → local device or rebuild contention.

**DOM Owner carries 288 per-host metrics and 46 cluster metrics** — far too
many for a rapid screen. Use the cluster roll-up here and leave the detail to
drill-down.

---

### Screen 6 — Rapid vSAN Resync

> **A host or disk was just lost.** Two questions: is it rebuilding, and will
> it finish before something else fails.

**Depth 1.** All from Cluster Domcompmgr.

| Panel | Metric key | Label | Unit |
|---|---|---|---|
| Resync load | `iopsResyncRead` | Resync Read IOPS | IOPS |
| | `tputResyncRead` | Resync Read Throughput | B/s |
| | `latAvgResyncRead` | Resync Read Latency | µs |
| Recovery writes | `iopsRecWrite` | Recovery Write IOPS | IOPS |
| | `throughputRecWrite` | Recovery Write Throughput | B/s |
| | `latencyAvgRecWrite` | Recovery Write Latency | µs |
| Guest impact | `latencyAvgRead` / `latencyAvgWrite` | front-end latency | µs |

**Pair rebuild rate against guest latency on the same screen** — the real
question during a rebuild is whether it is starving production, and that is
only visible with both in view.

---

### Screen 7 — Rapid vSAN VM

> **"My VM is slow."** Helpdesk needs to confirm or clear storage in one look,
> without a storage background.

Sorted **worst-latency first**. Objects are named after the real VM.

| Panel | Object type | Metric key | Label | Unit | Yellow / Orange / Red |
|---|---|---|---|---|---|
| Worst VMs | vSAN Virtual Machine | `latencyRead` | vSAN Layer Read Latency | µs | 2000 / 5000 / 10000 |
| | | `latencyWrite` | vSAN Layer Write Latency | µs | 2000 / 5000 / 10000 |
| | | `iopsRead` / `iopsWrite` | Read / Write IOPS | IOPS | — |
| Per virtual disk | vSAN vSCSI | `latencyRead` / `latencyWrite` | latency | µs | 2000 / 5000 / 10000 |
| | | `iopsRead` / `iopsWrite` | IOPS | IOPS | — |
| | vSAN Virtual Disk | (7 metrics) | | | |

**Show IOPS beside latency.** High latency at high IOPS is a busy VM; high
latency at *low* IOPS is a sick one. Without the pair, helpdesk cannot tell
them apart and escalates both.

---

### Screens 8–10 — sketched, not specified

| Screen | Status |
|---|---|
| **Rapid vSAN Host** | The drill-down every spoke links to: one host, all of its NICs, disks, DOM roles, CPU, memory. Needs a **host** selector rather than a cluster one; spec it once §3.2 is answered. |
| **Rapid vSAN OSA** | Disk groups, cache/capacity tiers, `diskgroupCongestion*Sched`. **Blocked:** the lab is ESA-only, so these families return nothing here and the model for them is provisional. Needs a real OSA cluster first. |
| **Rapid vSAN ESA internals** | ZDOM segment cleaning, VTX cache, compression ratio. Mostly from families the pack does **not yet collect** — see `BACKLOG.md`. Not buildable today. |

---

## 5. Blind spots — put these on the screens

An operator who believes a green dashboard means healthy hardware is worse off
than one who knows what it cannot see.

| Blind spot | Which screen must say so |
|---|---|
| **No disk media-error counters exist** anywhere in the Performance Service | Disk |
| **No NIC ring-buffer utilisation** — only overflow after the fact, so there is no early warning, only damage | Physical Network |
| **No compression metrics**; `savedByDedup` is dedup-and-compression combined as one ESA figure | Overview (capacity) |
| Ratios are **percent after conversion** — `1` means 1%, not one packet | every screen with a % metric |
| **Socket buffer minimums invert** — low is bad | Transport |

---

## 6. Build order

1. **Overview** — depth 1 only, proven wiring, highest value per hour.
2. **The depth-2 test** from §3.2 — one Scoreboard on `vSAN Physical NIC` /
   `rxMissErr`. Everything below depends on the answer.
3. **Physical Network** — the most-requested screen.
4. **VM** — highest audience volume.
5. **DOM**, **Transport**, **Disk**, **Resync**.
6. **Host** drill-down, once the selector question is settled.

## 7. What to send back

An **export of one finished screen** is worth more to this project than a
description of it. With one real multi-panel dashboard exported to JSON, the
remaining screens can be generated mechanically rather than built by hand. The
Overview screen is the ideal one to send.

Also worth flagging back:

- Did depth 2 work from a cluster selector, or was a second selector needed?
- Any threshold here that proved wrong in practice — they are starting points
  from Broadcom's published network figures and reasonable guesses elsewhere,
  not measured values.
- Any panel where the metric turned out not to mean what its label claims.

---

## Appendix A — why this is a spec and not a file

Dashboards were attempted as generated JSON first. That failed repeatedly, and
the reason is worth recording so nobody retries it the same way.

The dashboard format has fields with no public documentation. Files assembled
from a partial reading of an export imported without error but rendered
wrongly — a generic object badge instead of the configured metrics, or "this
dashboard is not done configuring", or blank panels. The eventual cause was at
the dashboard level, not the widget level: generated files carried `userId`
as an empty string — a dashboard with no owner — plus three keys that do not
exist in a real export at all.

The deeper problem was the feedback loop. Verifying each attempt required a
human to import the file and describe what appeared on screen, so every
iteration cost a round trip and several were spent chasing the wrong layer.
Building in the UI has none of that cost: the tool validates as you go and you
can see the result.

**So: build in the UI, export once, and mechanical generation becomes safe** —
because it can then clone a known-good artifact instead of reconstructing one.

Reference material, if useful:

| File | What it holds |
|---|---|
| `docs/DASHBOARD-FORMAT.md` | the format as far as it is understood, and where it misled |
| `docs/assets/dashboard.interaction-working.json` | the one confirmed-working provider→receiver export |
| `docs/METRICS-GUIDE.md` | what every metric family *is* |
| `README.md` → Metric reference | all 989 metrics with official names |
| `BACKLOG.md` | known gaps, unit conflicts, uncollected families |
