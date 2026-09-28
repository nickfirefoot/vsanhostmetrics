# Rapid vSAN dashboards — panel mockups

Companion to [`DASHBOARD-STORYBOARD.md`](DASHBOARD-STORYBOARD.md). Each panel
below names the **object type** in its header and the **exact metric key** on
every row, so a panel can be built straight from the picture.

Every "healthy" value is real, sampled from a live 4-host ESA cluster on
2026-09-28 — so this doubles as a baseline of what normal reads.

```
LEGEND   ● within bounds   ▲ yellow   ⬛ orange   ✖ red   · no data
         ↑ cumulative counter since boot — watch the delta, not the value
```

All panels are fed by the cluster selector. **Depth 1** = cluster-wide object
(proven wiring). **Depth 2** = hangs off HostSystem — verify per
`DASHBOARD-STORYBOARD.md` §3.2 before building.

---

## Screen 1 — Rapid vSAN Overview

```
┌─ CAPACITY ─────────────────────────────┐ ┌─ FRONT END — what VMs feel ──────────────┐
│ object: Vsan Cluster Capacity  depth 1 │ │ object: Cluster Domclient        depth 1 │
│ ● free           Free Capacity 10.12 TB│ │ ● latencyAvgRead   Read Latency    701 µs│
│ ● used           Used Capacity  3.32 TB│ │ ● latencyAvgWrite  Write Latency 1,518 µs│
│ ● total          Total Cap     13.44 TB│ │ ● congestion       Congestions         0 │
│ ● dedupRatio     Space Effic.   1.30 x │ │ ● iopsRead         Read IOPS          94 │
│ ● savedByDedup   Saved Cap      1.01 TB│ │ ● iopsWrite        Write IOPS        404 │
│                                        │ │ ● oio              Outstanding IO     20 │
│   24.7% used                           │ │ ● throughputRead   Read tput    1.6 MB/s │
│                                        │ │ ● throughputWrite  Write tput   6.1 MB/s │
└────────────────────────────────────────┘ └──────────────────────────────────────────┘

┌─ TRANSPORT — RDT ──────────────────────┐ ┌─ BACK END — what disks are doing ────────┐
│ object: vSAN Cluster RDT Latency  d 1  │ │ object: Cluster Domcompmgr       depth 1 │
│ ● avgLatency     RDT Avg Lat    386 µs │ │ ● latencyAvgRead   Read Latency    349 µs│
│ ● maxLatency     RDT Max Lat  8,789 µs │ │ ● latencyAvgWrite  Write Latency   237 µs│
│ ● minLatency     RDT Min Lat    109 µs │ │ ● congestion       Congestions         0 │
│ ↑ kaReset        Keepalive reset    13 │ │ ● oio              Outstanding IO      2 │
│ ↑ numReadyDelay  Num ready delay    25 │ │                                          │
└────────────────────────────────────────┘ └──────────────────────────────────────────┘

┌─ REBUILD ACTIVITY ─────────────────────────────────────────────────────────────────┐
│ object: Cluster Domcompmgr                                                 depth 1 │
│ ● iopsResyncRead      Resync Read IOPS      0   ● tputResyncRead    Resync Tput   0 │
│ ● latAvgResyncRead    Resync Read Lat    0 µs   ● iopsRecWrite      Rec Wr IOPS   0 │
│ ● throughputRecWrite  Rec Write Tput        0   ● latencyAvgRecWrite Rec Wr Lat 0 µs│
│   idle — nothing rebuilding                                                        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Normal relationship:** back end (349 µs) sits *below* front end (701 µs) —
the gap is network hops, owner coordination and policy. **Convergence or
inversion is the signal.**

**Degraded — failing uplink:** `latencyAvgRead` 12,400 µs and `latencyAvgWrite`
18,900 µs on Cluster Domclient, `avgLatency` 4,180 µs and `kaReset` rising
13→47 on RDT, while Cluster Domcompmgr stays at 352/240 µs. Front end wrecked,
back end innocent → Physical Network.

> **Correction to the storyboard:** `kaReset` and `numReadyDelay` are
> **cumulative since boot** (13 and 25, flat across an hour on a healthy
> cluster). The originally proposed bounds of 1/2/5 would sit permanently red.
> Show unbounded; alert on rate of change.

---

## Screen 2 — Rapid vSAN Physical Network

```
┌─ RING BUFFER OVERRUN ──────────────────────────────────────────────────────────────┐
│ object: vSAN Physical NIC     metric: rxMissErr     unit: %        depth 2         │
│ label: "pNIC RX missed error (ring buffer full)"    bounds: 0.1 / 0.5 / 1.0        │
│                                                                                    │
│  esxi01 vmnic0 ●0.0%   esxi01 vmnic2 ●0.0%   esxi02 vmnic0 ●0.0%                   │
│  esxi02 vmnic2 ●0.0%   esxi03 vmnic0 ●0.0%   esxi03 vmnic2 ●0.0%                   │
│  esxi04 vmnic0 ●0.0%                                              7 pNICs          │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ WIRE ERRORS ──────────────────────────────────────────────────────────────────────┐
│ object: vSAN Physical NIC                 all %, bounds 0.1 / 0.5 / 1.0   depth 2  │
│ ● rxCrcErr    pNIC RX CRC Error       0.0%   ● rxOvErr   RX Buffer Overflow   0.0% │
│ ● rxErr       pNIC RX Generic Error   0.0%   ● txCarErr  pNIC TX Carrier Err  0.0% │
│ ● rxFifoErr   pNIC RX FIFO Error      0.0%   ● txErr     pNIC TX Generic Err  0.0% │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ DISCARDS ─────────────────────────────────────────────────────────────────────────┐
│ object: vSAN Physical NIC                 all %, bounds 0.1 / 0.5 / 1.0   depth 2  │
│ ▲ portRxDrops        Inbound Drop Rate of vSwitch Port    0.0% .. 0.1% (worst)     │
│ ● portTxDrops        Outbound Drop Rate of vSwitch Port   0.0%                     │
│ ● rxPacketsLossRate  Inbound Packet Discard Rate          0.0%                     │
│ ● txPacketsLossRate  Outbound Packet Discard Rate         0.0%                     │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ FABRIC CONGESTION ────────────────────┐ ┌─ TCP HEALTH ─────────────────────────────┐
│ object: vSAN Physical NIC      depth 2 │ │ object: vSAN Host Network        depth 2 │
│ ● pauseCount  802.3x Pause Rate   0.0% │ │ · tcpTxRexmitRate  TX retransmit no data │
│               bounds 0.1/0.5/1.0       │ │ · tcpRxErrRate     RX err rate   no data │
└────────────────────────────────────────┘ └──────────────────────────────────────────┘
```

**Degraded — esxi03 vmnic2, failing transceiver:** `rxMissErr` 0.8%,
`rxCrcErr` 0.4%, `rxErr` 0.4%, `rxFifoErr` 0.1% on that one port; `pauseCount`
stays 0.0% everywhere.

**CRC high + pause clean** → one port's physical layer, swap the cable/optic.
**Pause high + CRC clean** → congested fabric, network team. Both on one screen
is what makes that call possible at a glance.

**Threshold source:** Broadcom's *Understanding vSAN Network TCP/IP
Expectations and Thresholds* — 0.1% warning, 0.5% immediate, 1.0% critical.
The adapter already converts per-mille to percent, so those apply directly.

> **Correction:** `tcpTxRexmitRate` and `tcpRxErrRate` return **no data at
> all** — absent, not zero. Build the panel, don't depend on it or alert on it.

---

## Screen 3 — Rapid vSAN Transport (RDT)

```
┌─ CONNECTION HEALTH ────────────────────────────────────────────────────────────────┐
│ object: vSAN Cluster RDT Latency                          no bounds       depth 1  │
│ ↑ kaReset        Keepalive reset      13    ↑ numReadyDelay  Num ready delay    25 │
│   cumulative since boot — the delta is the signal                                  │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ LATENCY ──────────────────────────────┐ ┌─ QUEUEING ───────────────────────────────┐
│ object: vSAN Cluster RDT Latency   d 1 │ │ object: vSAN Cluster RDT Latency  depth 1│
│ ● avgLatency  RDT Avg Latency   386 µs │ │ ● txQLatAvg  Avg Outbound Q Lat      8 µs│
│ ● maxLatency  RDT Max Latency 8,789 µs │ │ ● txQLatMax  Max Outbound Q Lat     16 µs│
│ ● minLatency  RDT Min Latency   109 µs │ │              bounds 500/2000/5000 µs     │
│   bounds 500 / 2000 / 5000 µs          │ │                                          │
└────────────────────────────────────────┘ └──────────────────────────────────────────┘

┌─ SOCKET BUFFER HEADROOM — ⚠ LOW IS BAD, COLOUR INVERTED ───────────────────────────┐
│ object: vSAN Cluster RDT Latency                                          depth 1  │
│ ● txSbSpaceMin  Socket Min Outbound Bytes   8.29 MB    free space remaining        │
│ ● rxSbSpaceMin  Socket Min Inbound Bytes    8.16 MB    0 = exhaustion = stall      │
│ ● txCtxQMax     Max Outbound Context Bytes      0 B                                │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ PER HOST / PER VMKERNEL NIC ──────────────────────────────────────────────────────┐
│ objects: vSAN RDT Latency  and  vSAN VMkernel RDT Latency      same keys, depth 2  │
│          avgLatency  maxLatency  txQLatAvg  txSbSpaceMin                           │
│ esxi01   ●   386 µs  ● 8,789 µs  ●    8 µs  ●  8.29 MB                             │
│ esxi02   ●   ...     ●   ...     ●  ...     ●  ...                                 │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Degraded:** `txSbSpaceMin` falling toward 0 while `avgLatency` climbs and
every pNIC counter stays clean = RDT stalling above a healthy NIC.

**`txSbSpaceMin` / `rxSbSpaceMin` are the only inverted tiles in the pack** —
they measure free space, so low is bad. Colour them backwards from everything
else or they read wrong.

---

## Screen 4 — Rapid vSAN Disk (ESA)

```
┌─ vSAN LAYER LATENCY — per disk, grouped by host ───────────────────────────────────┐
│ object: Vsan Esa Disk Layer                    colour RELATIVE to group   depth 2  │
│          avgLatReadCapacity   avgLatWriteCapacity                                  │
│ disk-1   ●   133 µs           ●   145 µs                                           │
│ disk-2   ●   151 µs           ●   170 µs                                           │
│ disk-3   ●   158 µs           ●   184 µs     ← median                              │
│ disk-4   ●   162 µs           ●   191 µs                                           │
│ disk-5   ●   171 µs           ●   203 µs                                           │
│ disk-6   ●   178 µs           ●   210 µs                                           │
│ disk-7   ▲   824 µs           ▲   904 µs     ← 5x median. THE signal here          │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ LAYER DIVERGENCE ─────────────────────────────────────────────────────────────────┐
│ object: Vsan Esa Disk Layer                                               depth 2  │
│ ● avgLatWritePerf      Latency write perf (average)   145 .. 815 µs  tracks cap.   │
│ · avgLatReadPerf       Latency read perf (average)    reads 0 on all 7 disks       │
│ ● avgLatUnmapCapacity  Latency unmap capacity (avg)                                │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ LOAD — context only, never the headline ──────────────────────────────────────────┐
│ object: Vsan Esa Disk Layer                                               depth 2  │
│ ● iopsReadCapacity  vSAN Layer Read IOPS   1 .. 58   ● iopsUnmapCapacity  unmap    │
│ ● iopsWriteCapacity vSAN Layer Write IOPS  2 .. 4                                  │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ SCSI FRONT END ───────────────────────────────────────────────────────────────────┐
│ object: Vsan Esa Disk Scsifw            16 metrics available              depth 2  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**The lab already shows the target pattern**: six disks 133–178 µs, one at
824 µs. Absolute thresholds miss it — 824 µs is not slow in itself. **Colour
relative to the group.**

> **No media-error counters exist** anywhere in the Performance Service — no
> SMART, no reallocated sectors. A bad device is inferred from timing alone.
> Put that on the screen.
>
> **Correction:** `avgLatReadPerf` reads 0 on all 7 disks. `avgLatWritePerf`
> populates.

---

## Screen 5 — Rapid vSAN DOM

```
┌─ CLIENT — what the VM feels ─┐ ┌─ OWNER — coordinates ┐ ┌─ COMP MGR — the disks ───┐
│ object: Cluster Domclient d1 │ │ obj: Cluster Domowner│ │ obj: Cluster Domcompmgr  │
│ ● latencyAvgRead     701 µs  │ │                      │ │ ● latencyAvgRead  349 µs │
│ ● latencyAvgWrite  1,518 µs  │ │  46 cluster metrics  │ │ ● latencyAvgWrite 237 µs │
│ ● congestion              0  │ │  — roll-up only,     │ │ ● congestion           0 │
│ ● iopsRead               94  │ │    too many for a    │ │ ● oio                  2 │
│ ● iopsWrite             404  │ │    rapid screen      │ │ ● iopsRead / iopsWrite   │
│ ● oio                    20  │ │                      │ │                          │
│   bounds 2000/5000/10000 µs  │ │                      │ │   same bounds            │
└──────────────────────────────┘ └──────────────────────┘ └──────────────────────────┘

┌─ CONGESTION BY TYPE ───────────────────────────────────────────────────────────────┐
│ object: Cluster Domclient                             bounds 1 / 10 / 50  depth 1  │
│ ● readCongestion  Read Congestions   0   ● unmapCongestion  Unmap congestion     0 │
│ ● writeCongestion Write Congestions  0                                             │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ PER HOST ─────────────────────────────────────────────────────────────────────────┐
│ objects: Host Domclient / Host Domowner / Host Domcompmgr    same keys,   depth 2  │
│          Client latencyAvgRead/Write     CompMgr latencyAvgRead/Write              │
│ esxi01   ●  690 / 1,490 µs               ●  340 / 230 µs                           │
└────────────────────────────────────────────────────────────────────────────────────┘
```

| `latencyAvgRead` Client | Comp Mgr | Means |
|---|---|---|
| high | low | above the disks — network, owner, or policy |
| high | high | the disks |
| low | high | local device or rebuild contention |

Lab now: 701/1,518 vs 349/237 µs — normal separation.

---

## Screen 6 — Rapid vSAN Resync

```
┌─ RESYNC LOAD ──────────────────────────┐ ┌─ RECOVERY WRITES ────────────────────────┐
│ object: Cluster Domcompmgr     depth 1 │ │ object: Cluster Domcompmgr       depth 1 │
│ ● iopsResyncRead    Resync R IOPS   0  │ │ ● iopsRecWrite       Rec Wr IOPS       0 │
│ ● tputResyncRead    Resync R Tput   0  │ │ ● throughputRecWrite Rec Wr Tput       0 │
│ ● latAvgResyncRead  Resync R Lat  0 µs │ │ ● latencyAvgRecWrite Rec Wr Lat     0 µs │
└────────────────────────────────────────┘ └──────────────────────────────────────────┘

┌─ GUEST IMPACT — is the rebuild starving production? ───────────────────────────────┐
│ object: Cluster Domclient                                                 depth 1  │
│ ● latencyAvgRead   Read Latency    701 µs   ● latencyAvgWrite  Write Lat  1,518 µs │
└────────────────────────────────────────────────────────────────────────────────────┘
```

All zero = idle, the healthy state. **During a rebuild**, resync throughput
climbing while `latencyAvgRead` and `latencyAvgWrite` stay flat is healthy; both climbing
together means the rebuild is eating production IO.

---

## Screen 7 — Rapid vSAN VM

```
┌─ WORST VMs BY LATENCY ─────────────────────────────────────────────────────────────┐
│ object: vSAN Virtual Machine       sort by latencyWrite desc    30 objects, d 1-2  │
│ VM         latencyRead  latencyWrite  iopsRead  iopsWrite                          │
│ ────────────────────────────────────────────────────────────────                   │
│ <vm-a>     ▲   726 µs   ▲  3,271 µs        169        152    ← busy, not sick      │
│ <vm-b>     ●     0 µs   ●    701 µs          0         12                          │
│ <vm-c>     ●     0 µs   ●    296 µs          0          4                          │
│   bounds 2000 / 5000 / 10000 µs                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ PER VIRTUAL DISK ─────────────────────────────────────────────────────────────────┐
│ object: vSAN vSCSI                                106 objects,  depth 2            │
│ VM / vmdk        latencyRead  latencyWrite  iopsRead  iopsWrite                    │
│ ────────────────────────────────────────────────────────────────                   │
│ <vm-a>/disk-1    ▲ 2,117 µs   ✖  8,587 µs       169       150   ← real outlier     │
│ <vm-b>/disk-1    ●     0 µs   ●    296 µs         0         0                      │
│   median across 106: 0 µs read / 296 µs write                                      │
│   also available: vSAN Virtual Disk (7 metrics, same shape)                        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Always pair IOPS with latency.** High latency at 169 IOPS is a busy VM; high
latency at 0 IOPS is a sick one. Without both, helpdesk escalates both.

---

## Metric key index — everything cited above

| Object type | Keys used | Depth |
|---|---|---|
| Vsan Cluster Capacity | `free` `used` `total` `dedupRatio` `savedByDedup` | 1 |
| Cluster Domclient | `latencyAvgRead` `latencyAvgWrite` `congestion` `readCongestion` `writeCongestion` `unmapCongestion` `iopsRead` `iopsWrite` `oio` `throughputRead` `throughputWrite` | 1 |
| Cluster Domcompmgr | `latencyAvgRead` `latencyAvgWrite` `congestion` `oio` `iopsResyncRead` `tputResyncRead` `latAvgResyncRead` `iopsRecWrite` `throughputRecWrite` `latencyAvgRecWrite` | 1 |
| Cluster Domowner | 46 metrics — roll-up only | 1 |
| vSAN Cluster RDT Latency | `avgLatency` `maxLatency` `minLatency` `kaReset` `numReadyDelay` `txQLatAvg` `txQLatMax` `txSbSpaceMin` `rxSbSpaceMin` `txCtxQMax` | 1 |
| vSAN Physical NIC | `rxMissErr` `rxCrcErr` `rxErr` `rxFifoErr` `rxOvErr` `txCarErr` `txErr` `portRxDrops` `portTxDrops` `rxPacketsLossRate` `txPacketsLossRate` `pauseCount` | 2 |
| vSAN Host Network | `tcpTxRexmitRate` `tcpRxErrRate` — **no data** | 2 |
| Vsan Esa Disk Layer | `avgLatReadCapacity` `avgLatWriteCapacity` `avgLatWritePerf` `avgLatReadPerf` (0) `avgLatUnmapCapacity` `iopsReadCapacity` `iopsWriteCapacity` `iopsUnmapCapacity` | 2 |
| vSAN RDT Latency / vSAN VMkernel RDT Latency | same keys as Cluster RDT Latency | 2 |
| Host Domclient / Domowner / Domcompmgr | same keys as their cluster roll-ups | 2 |
| vSAN Virtual Machine | `latencyRead` `latencyWrite` `iopsRead` `iopsWrite` | 1–2 |
| vSAN vSCSI | `latencyRead` `latencyWrite` `iopsRead` `iopsWrite` | 2 |

## Baseline — what normal reads (4-host ESA, 2026-09-28)

| Signal | Key | Normal |
|---|---|---|
| Front-end latency | Cluster Domclient `latencyAvgRead` / `latencyAvgWrite` | 701 / 1,518 µs |
| Back-end latency | Cluster Domcompmgr `latencyAvgRead` / `latencyAvgWrite` | 349 / 237 µs |
| RDT latency | `avgLatency` / `maxLatency` | 386 / 8,789 µs |
| RDT queueing | `txQLatAvg` / `txQLatMax` | 8 / 16 µs |
| RDT buffer headroom | `txSbSpaceMin` / `rxSbSpaceMin` | ~8.2 MB both |
| ESA disk latency | `avgLatReadCapacity` | 133–178 µs, one outlier 824 µs |
| pNIC errors | all keys | 0.0%, one port 0.1% `portRxDrops` |
| Congestion | `congestion` everywhere | 0 |
| Capacity | `used` / `total` / `dedupRatio` | 3.32 / 13.44 TB, 1.30x |

## Three corrections to the storyboard, from live data

1. **`kaReset` / `numReadyDelay` are cumulative** (13 and 25, flat for an
   hour). Bounds of 1/2/5 would sit permanently red. Unbounded; alert on delta.
2. **`tcpTxRexmitRate` / `tcpRxErrRate` return no data.** Build, don't depend.
3. **`avgLatReadPerf` is 0 on every disk.** `avgLatWritePerf` populates.
