# Widget load behaviour under storage latency

**Not a product defect.** Established 2026-09-30: the intermittent loading is a
function of **read latency against NFS-backed storage** on this deployment,
combined with how much a widget has to read. It is not a bug to raise with
Broadcom, and an earlier version of this file wrongly framed it as one.

The evidence below is kept because it characterises the behaviour precisely and
justifies the architecture that avoids it -- not because anything here needs
reporting.

## Why the evidence fits storage latency

| Observation | Explanation |
|---|---|
| The one-hop widget (13 objects) never failed; two-hop widgets (658) failed about half the time | read volume, not traversal logic |
| Recovery tracked **elapsed time**, not any action taken | first read warms the cache; later reads hit it |
| Two browsers disagreed at the same instant | one was served warm, the other cold |
| Loading was all-or-nothing, never partial | the widget resolves its set before rendering |
| The `Edit` dialog was slow to open on exactly the widgets that failed | same reads, same cost |
| Data was provably present throughout | the source was never the problem |

## The architecture that avoids it

A **Scoreboard** in `metric.mode: resourceKind` / `subMode: resourceKindAll`
resolves its entire object set on every render. A **View List** does not:

| Mechanism | Effect |
|---|---|
| `pagination-control` `size=50` | reads a bounded page, not the whole set |
| `metadata` `maxPointsCount=5000` | caps the points fetched per render |
| view filters | shrink the working set before any read happens |

This is why the practitioner guidance recommends View List over Scoreboard for
many objects, recommends filters explicitly "for dashboards scalability", and
warns that several Scoreboards on one dashboard hurt load time. Those are not
style preferences -- they are I/O guidance, and on storage with meaningful read
latency they are the difference between a screen that loads and one that does
not.

See [`../content/DASHBOARD-PRACTICE.md`](../content/DASHBOARD-PRACTICE.md).

## Characterisation, retained

## Environment

| | |
|---|---|
| Product | **VCF Operations 9.1.1.0**, build 25679751 (released 2026-09-04) |
| Node | ONLINE, all 7 services (ADMINUI, LOCATOR, UI, CASA, COLLECTOR, API, ANALYTICS) report health OK |
| Adapter | third-party management pack, 848 objects across 32 resource kinds |
| Cluster | 4 hosts, ESA |

## Symptom

A Scoreboard widget configured as a receiver renders its frame but **no data**.

**The variable is elapsed time, not configuration.** The sequence, established
2026-09-29 after several misattributions:

1. The widget renders empty and stays empty.
2. Several minutes pass.
3. The browser is refreshed.
4. The widget populates -- and continues working.

**Widget configuration has no bearing on this.** Input Transformation depth was
tried at 2, 3, 4, 5 and 6 with no effect at any value. Earlier notes in this
repository claimed that editing the widget, or toggling the depth and toggling
it back, reliably fixed it. **That was a misattribution**: those actions each
take a minute or two and end in a reload, so they coincided with the recovery
rather than causing it.

Newly created dashboards show the same pattern -- empty for the first few
minutes after creation, then working.

Loading is **all-or-nothing**: when it works, all 28 cells (4 metrics x 7
objects) populate at once. A partial render has never been observed.

Two browsers loading the same dashboard at the same moment can disagree, which
is consistent with one having waited past the recovery point and the other not.

## The data is present throughout

Queried through `/suite-api` while a widget showed nothing:

- All 7 `VsanPnic` objects hold **72 samples over 6 hours**, spacing
  299-301 s, **no gaps**
- Newest sample **3.5 minutes old** at time of query
- `System Attributes|availability` **100%** on every object
- Every object `resourceState=STARTED`, `resourceStatus=DATA_RECEIVING`

## Relationships resolve correctly

Walking `CHILD` from the `ClusterComputeResource` the widget is scoped to:

| Depth | Objects | Includes |
|---|---|---|
| 1 | 13 | 7 cluster-scoped kinds of this adapter, 4 HostSystem, 2 ResourcePool |
| 2 | 658 | 21 host-scoped kinds including the 7 `VsanPnic` the widget wants |

So the object graph supports the traversal at every load, including loads that
render nothing.

## What differs between the affected and unaffected widgets

What distinguishes the widget that always works from those that do not is what
they target, not how they are configured:

| Widget | Target kind | Relation to the selected cluster | Objects returned | Behaviour |
|---|---|---|---|---|
| RDT latency | `VsanClusterRdtLatency` | **direct child** | **1** | **always loads** |
| pNIC errors | `VsanPnic` | child of child (via `HostSystem`) | 7 | intermittent |
| TCP retransmits | `VsanHostNet`, `VsanPnic` | child of child | 4 + 7 | intermittent |
| Network Observations | `VsanTcpIp` | child of child | 4 | intermittent |

Two candidate variables remain and cannot be separated from outside the
product: whether the target kind is a **direct child** of the selected object
or one relationship further out, and whether the widget resolves **one** object
or several. Every widget that fails is both indirect and multi-object; the one
that works is neither.

The `Edit` dialog for the failing widgets is also noticeably slower to open
than for the working one.

## Configuration of a failing widget

```
type              Scoreboard
selfProvider      false
relationshipMode  -1
depth             2..4  (fails at every value)
metric.mode       resourceKind
metric.subMode    resourceKindAll
periodLength      null
oldMetricValues   false
maxCellCount      100   (widget renders 28 cells, well under)
```

Fed by a `View` widget (self-provider, a view listing Cluster Compute Resource
objects) through a single `widgetInteractions` entry of type `resourceId`.

## Ruled out

| Hypothesis | Ruled out by |
|---|---|
| Missing or gappy data | 72/72 samples, no gaps, 100% availability |
| Collection stopped | every object `DATA_RECEIVING` |
| Broken relationships | CHILD walk returns the objects at depth 2 |
| Scoreboard 100-item limit (KB 2150364) | 28 cells rendered, limit 100 |
| Shared-dashboard auto-refresh rule (KB 376970) | dashboard is `shared: false` |
| Server-side state | two browsers disagree at the same instant |
| Service health | all 7 services OK, node ONLINE |

## Closest documented match

Not in the VCF Operations 9.1.1.0 core release notes. The same symptom and the
same workaround are documented for the Topology Graph widget in the VCF
Operations Management Pack for Protection and Recovery 9.1:

> "the Topology Graph widget does not load. The workaround is to edit the
> widget without making any changes, which refreshes the widget and it will
> start working."

That is the identical workaround, on a different widget, in the same release
family -- which points at the widget framework rather than at either pack.

## Note on scale

The reads grow with object count, and two families dominate it: `VsanDomWorld`
(78.8 objects per host) and `VsanHostCpu` (61.0, one per CPU thread) are 87% of
what the pack creates per host and appear on no screen. Turning them off takes
a host from 161 objects to 21. That reduces the read volume behind every
widget, whatever widget it is -- see `BACKLOG.md`.
