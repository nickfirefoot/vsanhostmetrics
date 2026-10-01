# Dashboard refinement — for review

Written 2026-10-01 against a live collection from the three-host ESA cluster:
739 objects, 5,203 metric values, 34 resource kinds. Every number quoted below
is measured, not estimated. Every column named was checked against the model and
against that collection, so no column here is a guess at a metric name.

## The question you asked: do we need vCenter's stats?

**Yes, for four things, and no for everything else.** The evidence:

A built-in vSAN adapter (`VirtualAndPhysicalSANAdapter`) is installed on the
instance but **is not collecting** — one object in inventory, the adapter instance
itself. So it contributes nothing today.

vCenter's own `HostSystem` object defines **56 `vsan|*` statkeys** that overlap this
pack heavily: `domClient`, `domOwner`, `domCompManager`, `network`, `middleLayer`,
`memory`, `vsancpu`. On this instance **every one of them is empty**. I checked all
56 for data and got zero. They are populated by the built-in vSAN adapter, which is
not running. So vCenter is **not** a usable source for vSAN metrics here.

What vCenter *does* carry, verified with live values, and what this pack cannot get
any other way:

| From vCenter | Why this pack cannot supply it |
|---|---|
| `net|errorsRx_summation` and siblings | This pack only sees uplinks carrying vSAN traffic, two of four per host here. A standby uplink going bad is invisible to it. vCenter counts every uplink. |
| `health|reports|vsan|clomdLiveness`, `cmmdsdLiveness`, `epdLiveness`, `httpSvcResp` | This pack measures how much memory those daemons consume but has no way to ask whether they are answering. |
| `cpu|capacity_contentionPct`, `mem|swapinRate_average` | Host-wide contention. This pack sees vSAN's own CPU and memory, not what the host as a whole is doing. |
| `health|reports|memory|totalUncorrectedErrorsSinceBoot`, `psod|psod7DaysCount` | Hardware and crash history. Entirely outside the Performance Service. |

Two new views borrow exactly those and nothing more, using the same cross-adapter
mechanism the cluster selector already uses. **No new collection is involved** —
the columns point at an adapter that is already running.

The overlap is deliberately *not* borrowed. Where vCenter has four `domOwner` keys
and this pack has 272, borrowing would add a shallower copy of something already
present.

## What was wrong with the five dashboards

Found by comparing the collected data against what the screens actually showed:

1. **Resync had no content of its own.** All three of its views also appeared on
   Overview, so it was a duplicate screen with a different name.
2. **The DOM owner layer was absent everywhere.** It returns 272 metrics live and 87
   of them move. It is the layer that coordinates each write across its replicas, so
   it holds the distributed-write cost — and nothing displayed it.
3. **zDOM, the ESA write path, was absent.** 71 metrics on the write path plus 19 on
   per-host top stats, none on a screen.
4. **Only cluster aggregates for the back end.** `VsanHostDomcompmgr` returns 72
   metrics per host and no view used it, so "which host's disks are slow" was
   unanswerable.
5. **The vmknic was invisible.** The pNIC view shows the wire and the host view shows
   the total; the kernel port in between, where host-attributable loss appears first,
   had no view. It shows 0.1% transmit loss here.

## Three findings worth acting on, from the data itself

| Finding | Measured |
|---|---|
| Segment cleaning stalls | worst-case **370 ms** against a **1.3 ms** average |
| DOM owner write tail | max **14.9 ms** against a **957 µs** average |
| Local reads slower than remote | local **1,392 µs**, remote **905 µs** |

The first two are tail-latency problems that averages hide completely. The third
inverts the expected order — crossing the network should cost more than not
crossing it — and points at a local device rather than the fabric.

## The seven dashboards

Was five. Two are new: **ESA Write Path** and **Host Resources**.

### Rapid vSAN Overview

| Panel | View | Columns | Live signal |
|---|---|---|---|
| Capacity | vSAN Cluster Capacity | 5 | 5 of 5 columns moving |
| Front end - what VMs feel | vSAN Cluster DOM Client | 11 | 7 of 11 columns moving |
| Coordination - the owner | vSAN Cluster DOM Owner **(new)** | 10 | 7 of 10 columns moving |
| Back end - the disks | vSAN Cluster DOM Component Manager | 6 | 5 of 6 columns moving |
| Transport - RDT | vSAN Cluster RDT | 8 | 8 of 8 columns moving |
| Host services - are they up? | vSphere Host vSAN Services **(new)** | 10 | from vCenter, verified populated |

### Rapid vSAN Network

| Panel | View | Columns | Live signal |
|---|---|---|---|
| RDT latencies - per host | vSAN RDT Transport Per Host | 10 | 10 of 10 columns moving |
| RDT latencies - per vmknic | vSAN vmknic RDT Latency **(new)** | 9 | 9 of 9 columns moving |
| TCP error types | vSAN Host TCP Health | 12 | 2 of 12 columns moving |
| pNIC stats - vSAN uplinks | vSAN pNIC Errors | 17 | 3 of 17 columns moving |
| vmknic - the kernel port | vSAN vmknic **(new)** | 10 | 7 of 10 columns moving |
| Host network - all vSAN | vSAN Host Network | 8 | 5 of 8 columns moving |
| Every uplink - from vCenter | vSphere Host Uplinks and Load **(new)** | 10 | from vCenter, verified populated |
| CMMDS - cluster membership | vSAN CMMDS Network **(new)** | 10 | 8 of 10 columns moving |

### Rapid vSAN Storage

| Panel | View | Columns | Live signal |
|---|---|---|---|
| ESA disks - vSAN layer | vSAN ESA Disks | 5 | 5 of 5 columns moving |
| ESA disks - physical layer | vSAN ESA Disk Physical Layer | 5 | 5 of 5 columns moving |
| Back end - per host | vSAN Host DOM Component Manager **(new)** | 13 | 13 of 13 columns moving |
| Capacity | vSAN Cluster Capacity | 5 | 5 of 5 columns moving |
| VM storage - per controller | vSAN VM Storage | 4 | 4 of 4 columns moving |
| VM latency - per VM | vSAN VM Latency **(new)** | 6 | 6 of 6 columns moving |

### Rapid vSAN DOM

| Panel | View | Columns | Live signal |
|---|---|---|---|
| Cluster - client | vSAN Cluster DOM Client | 11 | 7 of 11 columns moving |
| Cluster - owner | vSAN Cluster DOM Owner **(new)** | 10 | 7 of 10 columns moving |
| Cluster - component manager | vSAN Cluster DOM Component Manager | 6 | 5 of 6 columns moving |
| Per host - client | vSAN Host DOM | 6 | 5 of 6 columns moving |
| Per host - owner | vSAN Host DOM Owner **(new)** | 14 | 14 of 14 columns moving |
| Per host - component manager | vSAN Host DOM Component Manager **(new)** | 13 | 13 of 13 columns moving |
| Owner network scheduler | vSAN Host DOM Owner Scheduler **(new)** | 12 | 12 of 12 columns moving |

### Rapid vSAN Resync

| Panel | View | Columns | Live signal |
|---|---|---|---|
| Jobs outstanding - the risk | vSAN Cluster Resync Jobs **(new)** | 14 | 1 of 14 columns moving |
| Rebuild IO rates | vSAN Cluster Resync | 6 | 0 of 6 columns moving — correct, nothing to report |
| Guest impact - front end | vSAN Cluster DOM Client | 11 | 7 of 11 columns moving |
| Back end during rebuild | vSAN Cluster DOM Component Manager | 6 | 5 of 6 columns moving |
| Is vSAN throttling itself? | vSAN Host DOM Owner Scheduler **(new)** | 12 | 12 of 12 columns moving |
| Segment cleaning | vSAN Segment Cleaning Per Host **(new)** | 10 | 10 of 10 columns moving |

### Rapid vSAN ESA Write Path

| Panel | View | Columns | Live signal |
|---|---|---|---|
| zDOM - cluster | vSAN zDOM Cluster **(new)** | 7 | 7 of 7 columns moving |
| zDOM - per host | vSAN zDOM Per Host **(new)** | 11 | 11 of 11 columns moving |
| Write path internals | vSAN zDOM Write Path **(new)** | 10 | 10 of 10 columns moving |
| Segment cleaning | vSAN Segment Cleaning Per Host **(new)** | 10 | 10 of 10 columns moving |
| Back end - per host | vSAN Host DOM Component Manager **(new)** | 13 | 13 of 13 columns moving |

### Rapid vSAN Host Resources

| Panel | View | Columns | Live signal |
|---|---|---|---|
| vSAN service health | vSphere Host vSAN Services **(new)** | 10 | from vCenter, verified populated |
| Host load - from vCenter | vSphere Host Uplinks and Load **(new)** | 10 | from vCenter, verified populated |
| vSAN daemon memory | vSAN Host Memory **(new)** | 12 | 12 of 12 columns moving |
| Physical CPU - per pCPU | vSAN Host CPU **(new)** | 3 | 3 of 3 columns moving |

## Panels that will read empty, and why that is correct

You saw "mostly" populating. These are the blanks, and none of them is a fault:

| Panel | Reading | Why |
|---|---|---|
| Resync → Rebuild IO rates | all six columns zero | Nothing is resyncing. Zero is the desirable answer. |
| Resync → Jobs outstanding | 1 of 14 moving | Same reason. The one moving column is guest write IOPS, there so a screen of zeros can be told apart from a screen that is not collecting. |
| Network → TCP error types | 2 of 12 moving | An error view. Zeros are good news. The two that move are duplicate-ack rate at 0.2% and half-open drop rate at 8.7%. |
| Network → pNIC stats | 3 of 17 moving | Same. Port RX drops 0.2%, and the lifetime missed-error counter at 11,664. |
| Overview and DOM → congestion columns | zero | vSAN raises congestion only when a layer cannot absorb load. Sustained non-zero would be the single most important number on the screen. |

## Open questions for you

1. **`VsanDomWorld` costs 243 of the 739 objects — a third of the collection — and
   every one of its three metrics is always zero.** `VsanHostVsansparse` is 21
   metrics, all zero. `VsanVirtualDisk` is 60 objects for one useful metric. A
   per-family toggle would cut the object count by roughly a third at no loss. This
   is already in the backlog; the measurement is new.
2. **`VsanCpu` returns `maxRunPct` and `maxUsedPct` but leaves `avgRunPct`,
   `avgUsedPct`, `readyPct`, `runPct` and `usedPct` at zero.** Five of seven fields
   never populate. Either upstream does not fill them or this pack reads them wrong,
   and I have not determined which.
3. **zDOM maximum latency columns read in whole seconds** — 9.7 s for reads, 2.7 s
   for writes. That is not credible as an interval maximum and is very likely a
   since-boot high-water mark the Performance Service does not document as such. The
   help text says so and points at the average columns instead. Worth confirming
   before anyone treats those numbers as real.
4. **The borrowed vCenter columns assume the vCenter adapter is present.** It will be
   on any VCF Operations instance, but the two `vSphere ...` views are the only
   content here with a dependency outside this pack.

## Confirmed this session

**Pak content import preserves view widget bindings.** This was the last open
question about the delivery path. Importing a dashboard through the Operations UI
strips `viewDefinitionId`, `selfProvider` and the provider's pinned resource; the pak
content path does not. The 1.3.1 install populated without any manual re-wiring.

**One portability defect found and fixed.** The dashboard template carried a pinned
root on the cluster selector that came out of the browser session it was exported
from:

```json
{"resourceId": "resource:id:0_::_", "resourceName": "VCF World",
 "resourceKindId": "002010VcfAdapterVCFWorld",
 "id": "Ext.vcops.chrome.model.Resource-592"}
```

`id` is an ExtJS client-side model reference. It names a JavaScript object inside one
page load and means nothing on any other instance, or on a later visit to the same
one. It is now stripped at build time. The rest of the blob is kept, because
`resourceKindId` is a kind key rather than an instance id and every instance has
exactly one VCF World at the root of its hierarchy.

## Sharing the cluster selection across the Rapid dashboards

Asked during review: should each dashboard carry its own cluster selector, or
should they share one so the scope survives moving between screens?

**They should share, and the format supports it, but not through a widget.**
Each dashboard document has a `dashboardNavigations` field, and that is the
mechanism for handing the selected object to another dashboard. In the working
export this pack clones from, it is an **empty object**:

```json
"dashboardNavigations": {}
```

So there is no proven example of its shape to copy. Writing it from first
principles is specifically the thing that has already failed here once:
dashboards built with invented keys imported, rendered generic badges, and
reported themselves as not finished configuring. The format is reliably
clonable and not reliably reconstructable, and that has not changed.

**What works today without it.** The provider widget ships with
`selectFirstRow` enabled:

```json
"selectFirstRow": {"selectFirstRow": true}
```

On a single-cluster instance every dashboard therefore selects that cluster on
load and populates with no interaction at all. That is why the screens came up
populated rather than waiting for a click. On a multi-cluster instance the
selection would have to be made once per screen.

**To get true shared scope**, the route that has worked every previous time is
the same one: configure navigation between two dashboards once in the user
interface, export the result, and clone the `dashboardNavigations` block from it.
One exported example is enough to generate it for all seven. Until that example
exists, a per-dashboard selector with `selectFirstRow` is the honest choice
rather than a guessed structure.

### A related defect found while answering this

Every widget in the template carries a `states` blob holding column visibility,
keyed by the dashboard and widget it was saved against:

```
permTableView_widget_<tabId>_<widgetId>
```

Cloning copied that key verbatim, so it named a dashboard and a widget that do
not exist in the generated output. Operations then had no saved state for the
widget it was actually drawing and fell back to defaults, which is why a cloned
selector showed a column the hand-built original had hidden. The ids are plain
hex and hyphens and survive the blob's URL encoding untouched, so the fix is a
literal substitution at build time. 441 state references across the seven
dashboards are now self-consistent, verified after generation.
