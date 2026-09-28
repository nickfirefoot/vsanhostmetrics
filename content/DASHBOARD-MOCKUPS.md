# Rapid vSAN dashboards — panel mockups

Companion to [`DASHBOARD-STORYBOARD.md`](DASHBOARD-STORYBOARD.md). That file
says *what to build*; this one shows *what it should look like when built*.

**Every "healthy" number below is real**, sampled from a live 4-host ESA
cluster on 2026-09-28. So these double as a baseline: this is what normal looks
like. Degraded panels are constructed to show a specific named failure.

```
LEGEND     ● green / within bounds      ▲ yellow      ⬛ orange      ✖ red
           ·  no data collected         ↑ cumulative counter, watch the delta
```

---

## Screen 1 — Rapid vSAN Overview

### Healthy — the cluster as it actually reads right now

```
┌─ CAPACITY ─────────────────────┐  ┌─ FRONT END — what VMs feel ─────────────┐
│ ● Free Capacity      10.12 TB  │  │ ● Read Latency             701 µs       │
│ ● Used Capacity       3.32 TB  │  │ ● Write Latency          1,518 µs       │
│ ● Total Capacity     13.44 TB  │  │ ● Congestions                  0        │
│ ● Space Efficiency     1.30 x  │  │ ● Read IOPS                   94        │
│ ● Saved Capacity      1.01 TB  │  │ ● Write IOPS                 404        │
│                                │  │ ● Outstanding IO              20        │
│   24.7% used                   │  │ ● Read / Write tput   1.6 / 6.1 MB/s    │
└────────────────────────────────┘  └─────────────────────────────────────────┘

┌─ TRANSPORT — RDT ──────────────┐  ┌─ BACK END — what disks are doing ───────┐
│ ● RDT Average Latency  386 µs  │  │ ● Read Latency             349 µs       │
│ ● RDT Max Latency    8,789 µs  │  │ ● Write Latency            237 µs       │
│ ● RDT Min Latency      109 µs  │  │ ● Congestions                  0        │
│ ↑ Keepalive reset         13   │  │ ● Outstanding IO               2        │
│ ↑ Num ready delay         25   │  │                                         │
└────────────────────────────────┘  └─────────────────────────────────────────┘

┌─ REBUILD ACTIVITY ──────────────────────────────────────────────────────────┐
│ ● Resync Read IOPS  0   ● Resync Read Tput  0 B/s   ● Resync Read Lat   0 µs│
│ ● Recovery Wr IOPS  0   ● Recovery Wr Tput  0 B/s   ● Recovery Wr Lat   0 µs│
│   idle — nothing rebuilding                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**What this teaches the operator about normal:** back-end latency (349 µs) is
*lower* than front-end (701 µs read, 1,518 µs write). That is correct and
expected — the front end carries network hops, owner coordination and policy
work that the disks never see. **Front-end higher than back-end is the normal
relationship; the two converging or inverting is the signal.**

### Degraded — a failing uplink, seen from Overview

```
┌─ FRONT END ────────────────────┐  ┌─ TRANSPORT — RDT ───────────────────────┐
│ ✖ Read Latency      12,400 µs  │  │ ⬛ RDT Average Latency    4,180 µs       │
│ ✖ Write Latency     18,900 µs  │  │ ✖ RDT Max Latency       61,000 µs       │
│ ▲ Congestions              4   │  │ ↑ Keepalive reset    13 → 47  RISING    │
│ ● Read IOPS               88   │  │ ↑ Num ready delay    25 → 310 RISING    │
└────────────────────────────────┘  └─────────────────────────────────────────┘
┌─ BACK END ─────────────────────┐
│ ● Read Latency        352 µs   │   front end wrecked, back end fine,
│ ● Write Latency       240 µs   │   transport bad  →  go to Physical Network
└────────────────────────────────┘
```

**This is the whole point of Overview.** Front end destroyed, back end
untouched, transport bad — the disks are innocent and the answer is one
screen to the right. Sixty seconds, no storage expertise required.

> ### Correction to the storyboard — `kaReset` and `numReadyDelay`
>
> The storyboard said these "should be zero forever" and proposed bounds of
> 1 / 2 / 5. **That is wrong.** Live sampling shows `kaReset` = 13 and
> `numReadyDelay` = 25, *flat across every sample in an hour* — they are
> **cumulative since boot**, not per-interval.
>
> An absolute threshold would sit permanently red on a healthy cluster and
> train everyone to ignore the tile. What matters is **whether the number is
> increasing**. Show them as plain values with no bounds, and alert on
> rate-of-change instead (a supermetric, or the widget's own delta/rate
> transformation if one is available). Mark them `↑` on screen so nobody reads
> the absolute value as a fault.

---

## Screen 2 — Rapid vSAN Physical Network

### Healthy — every counter genuinely zero

```
┌─ RING BUFFER OVERRUN ───────────────────────────────────────────────────────┐
│  esxi01 vmnic0 ●0.0%   esxi01 vmnic2 ●0.0%   esxi02 vmnic0 ●0.0%            │
│  esxi02 vmnic2 ●0.0%   esxi03 vmnic0 ●0.0%   esxi03 vmnic2 ●0.0%            │
│  esxi04 vmnic0 ●0.0%                                          7 pNICs       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ WIRE ERRORS ───────────────────────────────────────────────────────────────┐
│  RX CRC      ● 0.0%      RX Generic   ● 0.0%      RX FIFO    ● 0.0%         │
│  RX Overflow ● 0.0%      TX Carrier   ● 0.0%      TX Generic ● 0.0%         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ DISCARDS ──────────────────────────────────────────────────────────────────┐
│  vSwitch Port RX Drop   ● 0.0%  ..  ▲ 0.1% (worst pNIC)                     │
│  vSwitch Port TX Drop   ● 0.0%                                              │
│  Inbound Packet Discard ● 0.0%      Outbound Packet Discard ● 0.0%          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ FABRIC CONGESTION ────────────┐  ┌─ TCP HEALTH (per host) ─────────────────┐
│ ● 802.3x Pause Rate     0.0%   │  │ · TCP TX retransmit rate     no data    │
│                                │  │ · TCP RX error rate          no data    │
└────────────────────────────────┘  └─────────────────────────────────────────┘
```

A screen of zeroes **is** the healthy state here. The one non-zero reading in
the whole lab is a single pNIC at 0.1% vSwitch RX drop — right at Broadcom's
warning line, and exactly the kind of thing this screen exists to surface.

### Degraded — esxi03 vmnic2, failing transceiver

```
┌─ RING BUFFER OVERRUN ───────────────────────────────────────────────────────┐
│  esxi01 vmnic0 ●0.0%   esxi01 vmnic2 ●0.0%   esxi02 vmnic0 ●0.0%            │
│  esxi02 vmnic2 ●0.0%   esxi03 vmnic0 ●0.0%   esxi03 vmnic2 ✖0.8%  ◄── HERE  │
│  esxi04 vmnic0 ●0.0%                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
┌─ WIRE ERRORS — esxi03 vmnic2 ───────────────────────────────────────────────┐
│  RX CRC ⬛0.4%   RX Generic ⬛0.4%   RX FIFO ▲0.1%   TX Carrier ●0.0%        │
└─────────────────────────────────────────────────────────────────────────────┘
┌─ FABRIC CONGESTION ────────────┐   CRC + ring overrun on ONE port, pause
│ ● 802.3x Pause Rate     0.0%   │   clean  →  bad cable/optic on that port,
└────────────────────────────────┘   not a congested fabric
```

**CRC high + pause clean** localises to one port's physical layer. **Pause
high + CRC clean** would be the opposite finding — a congested fabric, which
is the network team's problem, not a hardware swap. Putting both on one screen
is what makes that distinction available at a glance.

> ### Correction to the storyboard — the TCP health panel
>
> `tcpTxRexmitRate` and `tcpRxErrRate` **return no data at all** from the
> Performance Service on this cluster — not zero, absent. This matches the
> earlier report that TCP errors "always read 0" through the vCenter adapter.
>
> Build the panel, because it costs nothing and may populate on other
> versions or configurations, but **do not design the screen around it** and
> do not raise alerts on it. Retransmits are a genuine gap in this pack; see
> `BACKLOG.md`. If retransmit visibility is needed, it has to come from
> elsewhere.

---

## Screen 3 — Rapid vSAN Transport (RDT)

```
┌─ CONNECTION HEALTH ─────────────────────────────────────────────────────────┐
│ ↑ Keepalive reset          13        ↑ Num ready delay          25          │
│   cumulative — watch the delta, not the value                               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ LATENCY ──────────────────────┐  ┌─ QUEUEING ──────────────────────────────┐
│ ● RDT Average Latency  386 µs  │  │ ● Avg Outbound Queueing Latency    8 µs │
│ ● RDT Max Latency    8,789 µs  │  │ ● Max Outbound Queueing Latency   16 µs │
│ ● RDT Min Latency      109 µs  │  │                                         │
└────────────────────────────────┘  └─────────────────────────────────────────┘

┌─ SOCKET BUFFER HEADROOM — ⚠ LOW IS BAD ─────────────────────────────────────┐
│ ● Socket Min Outbound Bytes   8.29 MB       free space remaining            │
│ ● Socket Min Inbound Bytes    8.16 MB       0 = exhaustion = stall          │
│ ● Max Outbound Context Bytes  0 B                                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ PER HOST (depth 2) ────────────────────────────────────────────────────────┐
│           avgLat   maxLat   txQLatAvg   txSbSpaceMin                        │
│ esxi01   ● 386µs  ● 8.8ms   ●   8µs     ● 8.29 MB                           │
│ esxi02   ● ...    ● ...     ●  ...      ● ...          + vSAN VMkernel RDT  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Degraded:** `txSbSpaceMin` falling toward 0 with `avgLatency` climbing and
every pNIC counter clean = RDT stalling above a healthy NIC. Colour the two
`*SbSpaceMin` tiles **inverted** — low is bad — or they read backwards.

---

## Screen 4 — Rapid vSAN Disk (ESA)

```
┌─ vSAN LAYER LATENCY — per disk, grouped by host ────────────────────────────┐
│           Read      Write          median 158 / 184 µs                      │
│ disk-1  ●  133µs  ●  145µs                                                  │
│ disk-2  ●  151µs  ●  170µs                                                  │
│ disk-3  ●  158µs  ●  184µs                                                  │
│ disk-4  ●  162µs  ●  191µs                                                  │
│ disk-5  ●  171µs  ●  203µs                                                  │
│ disk-6  ●  178µs  ●  210µs                                                  │
│ disk-7  ▲  824µs  ▲  904µs   ◄── 5x the median. THE signal on this screen   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ LAYER DIVERGENCE ─────────────────────────────────────────────────────────┐
│ Write perf tier   145 µs .. 815 µs     tracks capacity tier — normal        │
│ Read perf tier    · no data (all 7 disks read 0)                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ LOAD — context only, never the headline ───────────────────────────────────┐
│ Read IOPS    1 .. 58        Write IOPS   2 .. 4                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**The lab already shows the exact pattern this screen hunts:** six disks at
133–178 µs and one at 824 µs. Absolute thresholds would miss it — 824 µs is
not slow in absolute terms. **Colour relative to the group, not to a fixed
number.**

> **No media-error counters exist** in the Performance Service — no SMART, no
> reallocated sectors. A bad device is inferred from timing only. Say so on
> the screen.
>
> **`avgLatReadPerf` reads 0 on all 7 disks** — the read perf-tier metric is
> empty on ESA. Drop it or label it clearly; `avgLatWritePerf` does populate.

---

## Screen 5 — Rapid vSAN DOM

```
┌─ CLIENT ───────────────┐ ┌─ OWNER ──────────────┐ ┌─ COMPONENT MANAGER ────┐
│ what the VM feels      │ │ coordinates + policy │ │ what the disks did     │
│ ● Read Latency  701 µs │ │                      │ │ ● Read Latency  349 µs │
│ ● Write Latency 1518 µs│ │  46 cluster metrics  │ │ ● Write Latency 237 µs │
│ ● Congestions      0   │ │  — roll-up only,     │ │ ● Congestions      0   │
│ ● Read IOPS       94   │ │    too many for a    │ │ ● Outstanding IO   2   │
│ ● Write IOPS     404   │ │    rapid screen      │ │                        │
│ ● Outstanding IO  20   │ │                      │ │                        │
└────────────────────────┘ └──────────────────────┘ └────────────────────────┘

┌─ CONGESTION BY TYPE ────────────────────────────────────────────────────────┐
│ ● Read Congestions  0     ● Write Congestions  0     ● Unmap congestion  0  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ PER HOST (depth 2) ────────────────────────────────────────────────────────┐
│          Client R/W        CompMgr R/W                                      │
│ esxi01  ● 690 / 1490 µs   ● 340 / 230 µs                                     │
│ esxi02  ● ...             ● ...                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Reading it — the whole diagnostic in three lines:**

| Client | Comp Mgr | Means |
|---|---|---|
| high | low | above the disks — network, owner, or policy |
| high | high | the disks |
| low | high | local device or rebuild contention |

Lab right now: client 701/1518 µs, compmgr 349/237 µs — normal separation.

---

## Screen 6 — Rapid vSAN Resync

```
┌─ RESYNC LOAD ──────────────────┐  ┌─ RECOVERY WRITES ───────────────────────┐
│ ● Resync Read IOPS        0    │  │ ● Recovery Write IOPS        0          │
│ ● Resync Read Throughput  0 B/s│  │ ● Recovery Write Throughput  0 B/s      │
│ ● Resync Read Latency     0 µs │  │ ● Recovery Write Latency     0 µs       │
└────────────────────────────────┘  └─────────────────────────────────────────┘

┌─ GUEST IMPACT — is the rebuild starving production? ────────────────────────┐
│ ● Front-end Read Latency   701 µs      ● Front-end Write Latency  1,518 µs  │
└─────────────────────────────────────────────────────────────────────────────┘
```

All zeroes = nothing rebuilding, which is the healthy idle state.

**During a rebuild** the guest-impact row is the one that matters — resync
throughput climbing while front-end latency stays flat is a healthy rebuild;
both climbing together means it is eating production IO.

---

## Screen 7 — Rapid vSAN VM

```
┌─ WORST VMs BY LATENCY ──────────────────────────────────────────────────────┐
│ VM                      Read Lat   Write Lat   Read IOPS   Write IOPS       │
│ ─────────────────────────────────────────────────────────────────────────── │
│ <vm-a>                 ▲ 726 µs   ▲ 3,271 µs        169          152        │  busy
│ <vm-b>                 ●   0 µs   ●   701 µs          0           12        │
│ <vm-c>                 ●   0 µs   ●   296 µs          0            4        │
│ ... 30 VMs, worst first                                                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─ PER VIRTUAL DISK (vSCSI, 106 objects) ─────────────────────────────────────┐
│ VM / vmdk               Read Lat   Write Lat   Read IOPS   Write IOPS       │
│ ─────────────────────────────────────────────────────────────────────────── │
│ <vm-a> / disk-1        ▲ 2,117µs  ✖ 8,587 µs       169          150        │  ◄ outlier
│ <vm-b> / disk-1        ●     0µs  ●   296 µs         0            0        │
│   median across all 106:  0 µs read / 296 µs write                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Always show IOPS beside latency.** High latency at 169 IOPS is a busy VM;
high latency at 0 IOPS is a sick one. Without the pair, helpdesk escalates
both. The lab has a genuine example: one vmdk at 8,587 µs write against a
median of 296 µs.

---

## Baseline summary — what normal reads on a 4-host ESA cluster

| Signal | Normal (measured 2026-09-28) |
|---|---|
| Front-end latency (DOM Client) | 701 µs read / 1,518 µs write |
| Back-end latency (DOM Comp Mgr) | 349 µs read / 237 µs write |
| RDT average / max latency | 386 µs / 8,789 µs |
| RDT queueing latency | 8 µs avg, 16 µs max |
| RDT socket buffer minimum | ~8.2 MB free both directions |
| ESA disk latency | 133–178 µs typical, one outlier at 824 µs |
| All pNIC error counters | 0.0%, except one port at 0.1% vSwitch RX drop |
| All congestion counters | 0 |
| Capacity | 3.32 TB of 13.44 TB used (24.7%), 1.30x efficiency |
| Resync | idle |

**Front end sits above back end by design** — the gap is network, owner
coordination and policy. Convergence or inversion is the anomaly.

## Three corrections to the storyboard, from live data

1. **`kaReset` / `numReadyDelay` are cumulative**, not per-interval (13 and 25,
   flat for an hour). Proposed bounds of 1/2/5 would sit permanently red. Show
   unbounded; alert on rate of change.
2. **`tcpTxRexmitRate` / `tcpRxErrRate` return no data.** Build the panel, do
   not depend on it.
3. **`avgLatReadPerf` is 0 on every disk.** The read perf-tier metric is empty
   on ESA; `avgLatWritePerf` populates.
