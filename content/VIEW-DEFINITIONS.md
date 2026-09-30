# View definitions to create

**Views ship in the pak under `content/reports/`** (confirmed with Broadcom).
The SDK scaffolds no `views/` directory and `mp_build` only calls
`build_subdirectories()` for `content/dashboards` and `content/reports`, so
reports is the folder that carries them -- one subdirectory per view, XML:

```
content/reports/<view-name>/<view-name>.xml      # the view definition
content/dashboards/<name>/<name>.json            # references it by viewDefinitionId
```

That makes these a **one-time build, not per-customer setup**. A view's GUID
travels with its XML rather than being regenerated on import -- which is how
Broadcom's own dashboard hard-codes
`viewDefinitionId=fc3518f5-893a-4935-9ac1-2f46b0e063d6` and resolves on every
customer install. Build once, export, ship.

**Import order matters:** views before dashboards, or the dashboard lands with
dangling references.

**Build these first.** A View List widget references a View by GUID
(`viewDefinitionId`), there is no API to create or list Views
(`/suite-api/api/views` and `/viewdefinitions` both return 404), so the Views
must exist in the UI before any dashboard can point at them.

Each is **Views -> Create View**, and takes a couple of minutes. You have
already built one this way (`vSAN Clusters`).

Common settings unless stated otherwise:

| Wizard step | Setting |
|---|---|
| 1 Name & Configuration | **Presentation: List** |
| 2 Data | Subject = the object type below; add the metrics listed |
| 2 Data -> Transformation | **Maximum** over the period -- *not* Average. Average is a lagging indicator: by the time it looks bad, half the period already was |
| 3 Time Settings | default |
| 4 Filter | **empty** unless stated, so the view generalises to any cluster |
| 5 Summary | Create |

Where a metric is a **cumulative counter** (`*Raw`, `kaReset`,
`numReadyDelay`, `tcpSndZeroWin`) use **Current / last value**, not Maximum --
the maximum of a counter that only rises is just its latest value.

---

## 1. `vSAN pNIC Errors`

Replaces the per-NIC Scoreboard. A table scales to hundreds of rows where the
Scoreboard caps at 100 cells; at 16 hosts the Scoreboard version is already
over.

| | |
|---|---|
| Subject | **vSAN Physical NIC** |
| Presentation | List |
| Transformation | Maximum |
| Filter | empty |
| Sort | `rxMissErr` descending -- worst NIC at the top |

Columns:

| Metric key | Label | Colour bands |
|---|---|---|
| *(object name)* | NIC | -- |
| `rxMissErr` | RX missed (ring full) % | 0.1 / 0.2 / 0.4 / 0.8 |
| `rxCrcErr` | RX CRC % | 0.1 / 0.2 / 0.4 / 0.8 |
| `rxErr` | RX generic % | 0.1 / 0.2 / 0.4 / 0.8 |
| `rxFifoErr` | RX FIFO % | 0.1 / 0.2 / 0.4 / 0.8 |
| `rxOvErr` | RX overflow % | 0.1 / 0.2 / 0.4 / 0.8 |
| `txCarErr` | TX carrier % | 0.1 / 0.2 / 0.4 / 0.8 |
| `txErr` | TX generic % | 0.1 / 0.2 / 0.4 / 0.8 |
| `portRxDrops` | vSwitch RX drop % | 0.1 / 0.2 / 0.4 / 0.8 |
| `portTxDrops` | vSwitch TX drop % | 0.1 / 0.2 / 0.4 / 0.8 |
| `pauseCount` | 802.3x pause % | 0.1 / 0.2 / 0.4 / 0.8 |

**Add lifetime columns**, transformation **Current** (a monotonic counter's
maximum is just its latest value), no colour bands:

| Metric key | Label |
|---|---|
| `rxMissErrRaw` | RX missed, lifetime |
| `rxCrcErrRaw` | RX CRC, lifetime |
| `rxErrRaw` | RX generic, lifetime |
| `rxOvErrRaw` | RX overflow, lifetime |

`portRxDrops` and `portTxDrops` have no Raw variant -- rate only.

> **Why both, demonstrated on the lab cluster 2026-09-30.** `esxi03 [vmnic2]`
> read `rxMissErrRaw` 10,524 -> 11,664 across one five-minute interval: **1,140
> receive packets dropped to a full ring buffer**. The rate metric registered
> `0.1%` for exactly one sample out of eleven and zero for the rest.
>
> - **Current** transformation on the rate would have missed it ten times out
>   of eleven.
> - **Maximum** catches it, at exactly the 0.1% warning threshold.
> - A window that excludes the burst still reads clean on the rate, while the
>   lifetime counter reads 11,664 regardless of when you look.
>
> Percentages answer *is it happening now*; lifetime counters answer *has this
> NIC ever been bad*. A screen carrying only the first shows an all-green
> esxi03.

Bands follow the convention that each is twice the last, anchored on
Broadcom's published 0.1% network warning threshold.

**Note on the screen, not in the view:** only uplinks carrying vSAN traffic
appear. Standby uplinks have no object, so an absent NIC is not a healthy one.

## 2. `vSAN Host TCP Health`

| | |
|---|---|
| Subject | **vSAN TCP/IP** -- *not* vSAN Host Network or vSAN VMkernel NIC, which advertise these keys and serve none of them |
| Transformation | Maximum, except `tcpSndZeroWin` = Current (cumulative) |
| Sort | `tcpTxRexmitRate` descending |

| Metric key | Label | Bands |
|---|---|---|
| `tcpTxRexmitRate` | TCP retransmit % | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpRxErrRate` | TCP RX error % | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpRcvdupackRate` | Duplicate ACK % | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpRcvoopackRate` | Out-of-order % | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpSackRcvBlocksRate` | SACK received % (peer missing our data) | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpTimeoutDropRate` | Timeout drop % | 0.1 / 0.2 / 0.4 / 0.8 |
| `tcpSndZeroWin` | Zero window (cumulative) | none -- watch the delta |

Leave `tcpHalfopenDropRate` **out** until the 7-9% reading on a healthy
cluster is understood (`BACKLOG.md`). A permanently amber column teaches
people to ignore the table.

## 3. `vSAN RDT Transport (per host)`

| | |
|---|---|
| Subject | **vSAN RDT Latency** |
| Transformation | Maximum, except the two cumulative counters |
| Sort | `maxLatency` descending |

| Metric key | Label | Notes |
|---|---|---|
| `avgLatency` | RDT avg latency µs | 500 / 1000 / 2000 / 4000 |
| `maxLatency` | RDT max latency µs | 5000 / 10000 / 20000 / 40000 |
| `txQLatAvg` | Outbound queueing µs | 500 / 1000 / 2000 / 4000 |
| `txSbSpaceMin` | TX buffer free bytes | **inverted -- low is bad** |
| `rxSbSpaceMin` | RX buffer free bytes | **inverted -- low is bad** |
| `kaReset` | Keepalive reset | Current; cumulative, no bands |
| `numReadyDelay` | Ready delay | Current; cumulative, no bands |

## 4. `vSAN ESA Disks`

| | |
|---|---|
| Subject | **Vsan Esa Disk Layer** (note: `Vsan`, not `vSAN`, in the picker) |
| Transformation | Maximum |
| Sort | `avgLatWriteCapacity` descending |

| Metric key | Label |
|---|---|
| `avgLatReadCapacity` | vSAN layer read latency µs |
| `avgLatWriteCapacity` | vSAN layer write latency µs |
| `avgLatWritePerf` | Perf tier write latency µs |
| `iopsReadCapacity` | Read IOPS |
| `iopsWriteCapacity` | Write IOPS |

**No fixed bands.** The signal is one disk diverging from its peers, not an
absolute number -- the lab shows six disks at 133-178 µs and one at 824 µs,
which no absolute threshold would catch. Sorting worst-first surfaces it.
Omit `avgLatReadPerf`: it reads 0 on every disk.

## 5. `vSAN VM Storage`

| | |
|---|---|
| Subject | **vSAN vSCSI** |
| Transformation | Maximum |
| Sort | `latencyWrite` descending |

| Metric key | Label | Bands |
|---|---|---|
| `latencyRead` | Read latency µs | 2000 / 4000 / 8000 / 16000 |
| `latencyWrite` | Write latency µs | 2000 / 4000 / 8000 / 16000 |
| `iopsRead` | Read IOPS | none |
| `iopsWrite` | Write IOPS | none |

**Keep IOPS beside latency.** High latency at high IOPS is a busy VM; high
latency at zero IOPS is a sick one. Without both, helpdesk escalates both.

**Known gap:** 27 of 106 vSCSI objects have no parent (vSphere Pod VMs), so a
cluster-scoped view will not reach them. See `BACKLOG.md`.

---

## What to send back

Once any one of these exists, **export a dashboard containing it**. That gives
me the `viewDefinitionId` GUID and the populated View List widget config --
the two things missing to generate the rest. Until then a generated file would
point at Views that do not exist and render empty.
