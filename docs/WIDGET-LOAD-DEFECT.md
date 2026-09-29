# Widget data does not load until the widget is edited

Evidence package for a Broadcom support case. Everything below is measured,
not inferred.

## Environment

| | |
|---|---|
| Product | **VCF Operations 9.1.1.0**, build 25679751 (released 2026-09-04) |
| Node | ONLINE, all 7 services (ADMINUI, LOCATOR, UI, CASA, COLLECTOR, API, ANALYTICS) report health OK |
| Adapter | third-party management pack, 848 objects across 32 resource kinds |
| Cluster | 4 hosts, ESA |

## Symptom

A Scoreboard widget configured as a receiver renders its frame but **no data**.
It stays empty indefinitely. It populates after **any** of:

- editing the widget and changing nothing of substance (e.g. Input
  Transformation depth 2 -> 3 -> 2)
- clicking the dashboard refresh control, sometimes after several attempts
- reloading the browser
- waiting several minutes after dashboard creation

Loading is **all-or-nothing**: when it works, all 28 cells (4 metrics x 7
objects) populate. A partial render has never been observed.

Two browsers loading the same dashboard at the same moment disagree — one
populates, the other does not. That rules out server-side data availability.

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

## Depth is not the variable

**Input Transformation depth was tried at 2, 3, 4, 5 and 6. No value changes
the behaviour.** The affected widgets fail intermittently at every setting and
the unaffected one works at every setting. Configuration is therefore ruled
out as a factor, including the depth control itself.

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

## Question for support

Is there a load or query timeout governing widget object resolution, and is it
configurable? No such setting appears in the dashboard JSON (only
`refreshInterval`, `refreshContent`, `maxCellCount`) or in
`/suite-api/api/deployment/config/globalsettings` (only `PER_ACTION_TIME_OUT`
and `PER_RESOURCE_ACTION_TIME_OUT`, both for the Actions framework).

If resolution is bounded by a timeout, that would explain both the
intermittency and why editing the widget -- which appears to force a fresh
resolution -- reliably fixes it.

Note that the depth control is **not** the variable: values 2 through 6 were
each tried and none changes the behaviour. Whatever governs this is not
exposed in the widget configuration.
