# Dashboards: operating knowledge

What this project has established about building dashboards in VCF Operations
9.1, separated into **verified**, **observed but unexplained**, and **assumed**.
Written because several days were lost to inferences presented as facts; the
distinction is the point of the document.

Companions: [`DASHBOARD-STORYBOARD.md`](DASHBOARD-STORYBOARD.md) (what to
build), [`DASHBOARD-MOCKUPS.md`](DASHBOARD-MOCKUPS.md) (what it should look
like), [`../docs/DASHBOARD-FORMAT.md`](../docs/DASHBOARD-FORMAT.md) (the file
format), [`../docs/WIDGET-LOAD-BEHAVIOUR.md`](../docs/WIDGET-LOAD-BEHAVIOUR.md) (the
open product defect).

---

## Provenance

Two sources, and they are not equivalent.

**Measured here**, against a live VCF Operations 9.1 instance and the exports
it produced. Everything in sections 1 to 5 that carries a number or names a
JSON field is of this kind, and section 6 records the ones that turned out to
be wrong.

**A practitioner guide Nick supplied**, "PART 2 - Consumption", 239 pages,
obtained from `https://isvara.io/api/download/part-2`. It is the reason this
project abandoned Scoreboards for View Lists. **This document is a distillation
of the parts that bore on the work, not a substitute for it** -- it was read
selectively and against one product version. For anything load-bearing, go to
the guide rather than to this summary, and treat a disagreement between them as
the guide being right until measured otherwise.

The separation into verified, observed and assumed exists because several days
were lost to inferences presented as facts. Keep it when editing.

## 1. The scale limit, and the widget that solves it

**A Scoreboard renders at most 100 cells. Cells = metrics x objects.** The
field is `maxCellCount: 100` in the widget JSON, so it counts rendered cells,
not configuration selections. Broadcom document it with no resolution and the
workaround "create multiple scoreboard widgets", noting that doing so "can
impact UI performance".

Measured object rates: ~1.75 vSAN pNICs and ~1.75 ESA disks per host, one each
of the per-host kinds, and exactly one of each cluster-scoped kind however
large the cluster. Where a cluster-scoped Scoreboard breaks:

| Panel | Breaks at |
|---|---|
| 4 metrics on `VsanPnic` | **14 hosts** |
| 11 metrics on `VsanTcpIp` | **9 hosts** |
| 10 metrics mixed | **7 hosts** |
| 1 metric on `VsanPnic` | 57 hosts |

**The fix is not to rearrange Scoreboards -- it is to stop using a Scoreboard
for many objects.** A Scoreboard is a summary widget. The widget built for many
objects is the **View List** (table): hundreds of rows, filterable, sortable,
per-cell colour coding, and no cell cap. Practitioner guidance is explicit that
`Object List` should be replaced by View List entirely -- "functionally it's a
superset" -- and that a filter is what makes a table scale, since showing tens
of thousands of objects will impact dashboard performance.

### Widget selection

Follow the practitioner convention; keep the variety small so users learn one
vocabulary across every screen.

| Widget | Use it for | Notes |
|---|---|---|
| **Scoreboard** | **Headline / banner summary** at the top, and **detail for a single object** | Shows the **present value only**, and colours on the last value rather than the period's average or peak. **Double-click a tile to open its trend chart** -- drill-down is based on *the object owning the metric* |
| **View List** | **Many objects.** The workhorse for per-NIC, per-disk, per-VM | Filter, sort, colour-coded cells, data transformation, parent values |
| **Top-N** | Worst N, value before object name | More eye-catching than a table. **Defaults to average -- change it to percentile**, since average is a lagging indicator. Users can change the percentile on the fly |
| **Heat Map** | Many objects where only the **present value** matters -- live NOC, capacity, configuration | **Not for performance**, where trend over time matters |
| **Trend Chart (View)** | History | Preferred over Metric Chart |
| **Text Display** | A "read me" explaining the screen | |

### Aggregation: never average

For summarising a period, the choice of statistic matters more than the widget:

| Statistic | Verdict |
|---|---|
| Current / last value | Fine for capacity, compliance, configuration. **Limited for performance** |
| **Average** | **A lagging indicator.** By the time the average looks bad, half the period was already bad. Not suitable for proactive monitoring |
| **Worst (max)** | Good for peak detection, and right for a 24-hour window (288 data points). Over a week, one spike sets it -- pair with percentile |
| **Worst 5th percentile** | The best midpoint for performance monitoring, and the right default over a week or month |

**Use worst and worst 5th percentile.** Not average.

### Thresholds and colour

A consistent scale so operators learn one rule: **Yellow = 2x Green, Orange =
2x Yellow, Red = 2x Orange** -- red ends up 8x green.

**Provenance, recorded because this will otherwise be re-litigated.** That scale
was chosen here for internal consistency alone: one rule an operator can hold in
their head, with no reference to any published figure. On the pNIC error columns
it puts yellow at **0.1%**.

vCenter's own `alarm-261`, "High pNic error rate detected", fires at **1 per
mille** on seven driver error counters -- the same number, arrived at by a
completely different route, and discovered afterwards rather than designed
toward. Broadcom use 0.1% as their published network warning figure generally,
which is also where the TCP out-of-order band here came from.

Two independent derivations landing on the same threshold is stronger evidence
than either on its own. **Do not "correct" the doubling scale toward some other
number without a measurement that beats both.**

| Colour | Meaning |
|---|---|
| Green -> Yellow -> Orange -> Red | performance and compliance, worsening |
| **Dark grey** | **wastage -- capacity allocated and not used.** On a capacity screen, low utilisation is dark grey rather than green, because the guide treats waste as a bigger problem than over-utilisation and because low usage can itself be the symptom of a bottleneck elsewhere (p44, p136-137). Omitted from the first version of this document |
| Grey | **collection error / missing data** -- not zero, and not healthy |
| Blue | neutral, no good/bad meaning |

The dark grey and plain grey bands are different things and the distinction is
easy to lose: one means nobody is using it, the other means we failed to find
out. On a performance screen rather than a capacity one the guide suggests red
for oversized instead, since oversizing hurts performance.

**A ratio without a super metric (p51).** A Gauge is a Scoreboard variant that
can take **another metric as its "total"**, so a percentage can be displayed
without authoring a super metric to compute it. Not needed by this project,
which has no super metrics, but it is the cheapest route to a ratio for anyone
who does.

## 2. Architecture: roll up, then dive

Broadcom hit the same wall in their own vSAN adapter and solved it by
publishing **pre-aggregated KPIs on the cluster object**:

| Their metric | Rolls up |
|---|---|
| `kpi\|esaDiskLatency_max` | worst latency across every disk in the cluster |
| `kpi\|hostVMKernelPacketDropped_sum` | sum across every host |
| `summary\|worst_vm_disk_latency` | worst VM |

One object, one cell each, constant at any cluster size -- and it answers the
question a rapid screen actually asks ("is anything wrong"), not "show me 112
values". Rollups are **additive**: every per-object metric stays where it is.

**Publish the offender's name as a string metric.** Broadcom ship string
metrics in Scoreboards, so a tile can read `"esxi03.example.com [vmnic2]"`
beside the worst value. This matters because drill-down is based on *the object
owning the metric* -- a rollup's object is the cluster, so navigation from it
can only scope a spoke to the cluster. The name closes that gap without
navigation.

### The shape

| Layer | Widget | Objects | Scales |
|---|---|---|---|
| **Hub** -- worst-in-cluster KPIs | Scoreboard (headline use) | 1 | forever |
| **Spoke** -- the full list | **View List, filtered** | all | built for it |
| **Spoke** -- worst N | Top-N with **percentile** | all | |
| **Spoke** -- live sweep | Heat Map (present value only) | all | |
| **Spoke** -- history | Trend Chart | 1-few | |

### Navigation between them

**Interaction is intra-dashboard; navigation is inter-dashboard (D2D).** D2D
drills down the object hierarchy or moves laterally -- **it cannot go up the
parent hierarchy**, so design the flow downward from the start.

D2D also exists to avoid deep dashboards: many widgets on one page are "harder
to understand and may suffer from loading time", which is worth weighing given
the open load defect. Prefer several focused screens over one that scrolls.

### Design tests to apply before building

- **Five seconds.** Can the screen be understood that fast? If yes, the user
  will invest minutes learning it. To pass, ask what can be *removed*.
- **Write the questions down** the screen must answer, with the metric and the
  visualisation for each.
- **Summary at the top, detail below** -- progressive disclosure, so the page
  loads fast and the eye goes to the big picture first.
- **An uber-dashboard that serves everyone gets used by no one.** Size matters
  too: a 4-host lab and a 64-host estate want different dashboards even for
  the same role and purpose.

## 3. Verified mechanics

Confirmed by building it, exporting it, and reading the result.

**Provider.** A `View` widget backed by a saved View definition, Self Provider
**ON**, Select First Row **ON**. Create the view under Views, subject
= the object type, data = `Configuration|Name`, **filter empty** so it returns
every object of that type rather than one. An Object List pinned to a named
object resolves only on the system it was built on and cannot ship.

**Receiver.** Self Provider **OFF**, wired from the provider by one
`widgetInteractions` entry of type `resourceId`. Every interaction in every
export examined -- including 15 in Broadcom's own dashboard -- is `resourceId`.
There is no metric-level interaction type in any observed content.

**Select First Row must be ON.** With it off, nothing is selected at load, no
interaction fires, and every receiver renders empty until something forces a
re-resolve. This is the single most common cause of a blank panel that "works
when I edit it".

**Dashboard time.** Performance panels need Period = Dashboard Time
(`periodLength: "dashboardTime"`) or the `1H/6H/24H` selector greys out with
*"one or more widget on this dashboard should be set to dashboardTime"*.
Broadcom set it on all seven of their numeric Scoreboards and omit it only on
the two that show configuration strings, where a time range is meaningless.
For **cumulative** counters, latest-value is correct and unset is defensible.

**Depth is cumulative**, not exact: depth N includes everything at N hops and
closer. Relationship depths in this pack, measured: cluster-scoped kinds at 1,
all host-scoped kinds including `VsanPnic` at 2, VM-scoped at 3.

**Do not hand-write the dashboard JSON.** Files assembled from a partial
reading of an export import without error and render wrongly. The fault was at
dashboard level -- `userId: ""` (a dashboard with no owner), wrong
`columnCount`/`columnProportion`/`shared`, and three keys that do not exist in
a real export. Build in the UI; clone a working export if generating.

## 4. Diagnosing an empty panel

Work down this list in order; the symptoms are indistinguishable but the
causes are not.

| Symptom | Likely cause |
|---|---|
| **Permanently** empty, never populates | **Wrong object type.** A metric key existing on a kind does not mean that kind serves it -- `tcpTxRexmitRate` is advertised on three kinds and served only by `vSAN TCP/IP`. Check for the same key on another kind. |
| Empty until any widget setting is changed | **Select First Row off** on the provider -- no selection fires at load |
| Empty, then loads after several minutes + reload | **Read latency**, not configuration. The widget is reading more than the storage serves quickly; the first read warms the cache. Use a View List rather than a Scoreboard for many objects -- see `../docs/WIDGET-LOAD-BEHAVIOUR.md` |
| Renders unrelated content (HA status, Health/Risk badges) | The widget fell back to a default object badge because its metric config did not resolve |
| `1H/6H/24H` greyed out | No widget set to dashboard time |

**Check the data before the dashboard.** `/suite-api/api/resources/{id}/stats`
and `/relationships/PARENT` (enum is **uppercase**) settle in seconds whether
the problem is collection, relationships or presentation.

## 5. Traps worth knowing

- **14 of 70 resource kinds are not named `vSAN ...`** -- ten with no prefix
  (`Cluster Domclient`, `Host Domcompmgr`, ...) and four spelled `Vsan`. They do
  not appear when searching "vSAN" in the object-type picker, and they include
  every DOM family and both ESA disk kinds. Logged in `BACKLOG.md`.
- **Only NICs carrying vSAN traffic get an object.** Standby uplinks are
  invisible; an absent NIC is not a healthy one.
- **64 VM-tier objects have no parent** -- vSphere Pod VMs, which the vCenter
  adapter does not model, so nothing can reach them by relationship.
- **Ratios are per-mille at source**, converted to percent by the adapter. A
  displayed `1` means 1%.
- **`kaReset`, `numReadyDelay`, `tcpSndZeroWin` and the `*Raw` family are
  cumulative since boot.** Absolute thresholds sit permanently red; alert on
  rate of change.
- **Socket buffer minimums invert** -- `txSbSpaceMin`/`rxSbSpaceMin` measure
  free space, so low is bad. The only inverted tiles in the pack.

## 6. Retracted claims

Kept deliberately. Each was stated confidently and was wrong.

| Claim | Why it was wrong |
|---|---|
| "NIC stats resolve at depth 2, buffer/CRC at depth 3" | Every pNIC error metric is on `VsanPnic` alone, at one depth. The apparent difference was panels re-resolving when any setting changed. |
| "Editing the widget reliably fixes it" | Editing takes a minute and ends in a reload. The variable is elapsed time. |
| "Depth-2 panels fail because a resolve walks 658 objects" | That was this repository's own API traversal method, not the product's. An indexed "descendants of X of kind Y" lookup is bounded. |
| "The TCP metrics return no data" | They return no data **on the object type the spec named**. `vSAN TCP/IP` serves them. |
| "`adapterName`/`docCenterKey`/`namePath` are present in every working export" | They appear in no real export. |

The pattern in all five: an observation generalised into a mechanism without
a way to test it. Where a claim cannot be falsified from outside the product,
it belongs in section 4 as a symptom, not here as a cause.

## 6a. Shipping views and dashboards in the pak

Views are referenced by GUID (`viewDefinitionId`) and there is **no API** to
create or list them -- `/suite-api/api/views` and `/viewdefinitions` both 404.
They are built in the UI, exported as XML, and **ship in the pak under
`content/reports/`** (confirmed with Broadcom; the SDK scaffolds no `views/`
directory and `mp_build` only builds subdirectories for `content/dashboards`
and `content/reports`).

```
content/reports/<view-name>/<view-name>.xml    # the view
content/dashboards/<name>/<name>.json          # references it by GUID
```

**The GUID travels with the XML.** It is not regenerated on import, which is
why Broadcom's shipped dashboard can hard-code a `viewDefinitionId` and have
it resolve on every customer install. So views are a one-time authoring cost,
not per-customer setup.

**Import views before dashboards**, or the dashboard arrives with dangling
references.

Practical consequence: a dashboard using View List widgets **cannot be
generated before its views exist**, because the GUIDs have to come from
somewhere. Author the views, export one, and the rest becomes mechanical.

## 7. Source

Sections 1 and 2 draw on *Part 2 of 4: Consumption* (August 2026), chapter
"The Art of Dashboard" -- practitioner guidance on VCF Operations dashboard
design. Retrieved from <https://isvara.io/api/download/part-2>.

What it settled that this project had open:

| Question | Answer |
|---|---|
| Does clicking a Scoreboard metric reach its trend? | **Yes -- double-click.** Drill-down is based on the object owning the metric |
| How do you show many objects? | **View List**, filtered. p47: "Use a filter if the number of items is large" |
| Is Heat Map right for the network sweep? | Only for **present value** / live NOC. Not for performance trend |
| Which statistic for a summary? | Worst and worst 5th percentile. **Never average** -- a lagging indicator |
| Is Object List ever right? | Only for throwaway dashboards. View List is a superset |

It also corroborated, independently, two things this project had reached the
hard way: that cluster-level rollups are how you escape per-object scale
limits, and that many widgets on one dashboard hurt load time.

**What is NOT the guide's, checked against all 239 pages:**

- **The 100-cell Scoreboard cap and the 7-to-14-host thresholds.** Zero hits
  for `maxCellCount`, "100 cells" or "cell limit" anywhere in it. The guide
  says to filter a View List when the item count is large; the number and the
  breaking point are this project's, from the Broadcom documentation and from
  measuring. An earlier version of the table above implied otherwise.
- **"Depth is cumulative" in relationship traversal.** The guide uses "depth"
  for something else entirely -- the depth of a *problem*, meaning its worst
  value, as against its *breadth*, meaning how many objects it touches
  (p90, p114). It never discusses traversal depth or `depth=` syntax. The
  traversal finding is measured here.

## 8. The saved column state must be stripped, not repaired

Every widget in a UI-exported dashboard carries a `states` blob holding
per-widget column visibility, keyed:

```
permTableView_widget_<tabId>_<widgetId>
```

**Strip it. Do not clone it, and do not repair it.** The repair was worse than
the bug, and the sequence is worth keeping because it is not obvious.

**Cloning it verbatim** leaves a key naming a widget that does not exist in the
generated dashboard. Operations finds no state for the widget it is drawing and
falls back to showing every column the view defines. This works, by accident.

**Rewriting the ids to the generated ones** makes the state apply. And the
state was written against a **different view**. Ours decoded to:

```
column-0            hidden=1
column-config|name1 hidden=0
```

The cluster selector renders a view whose only column is `Configuration|Name`,
not `config|name1`. So the state hid the object-name column and un-hid a column
that does not exist in that view. The widget still drew its frame, still found
the cluster, still auto-selected it and still drove every receiver on the
dashboard -- it simply showed one row containing `-`. It reads as a rendering
failure and is a column-visibility failure, which sent the first diagnosis at
the widget's height instead.

A states blob is one person's interface preference, captured in one browser
session, against one view. It has no business on generated content. Dropping it
restores the working behaviour by intent rather than by accident.

**The general lesson:** in a cloned export, a field that references its own
widget by id is inert while the id is wrong. Making the id right activates
whatever it says. Before repairing such a field, read what it will do once it
works.

## 9. Why two packs read the same pNIC error counters

Settled 2026-10-06 with the netstats pack (`VsphereNetStats`). The duplication is
deliberate and the reasoning is recorded because "why are two packs reading the
same counter" will be asked again.

**The counters are not vSAN's.** vCenter's `alarm-261`, "High pNic error rate
detected", is an OR of sixteen expressions: eight event types at yellow and red.
Seven of the eight map to ordinary driver error fields present on **every**
uplink in the estate, measured 15 of 15 including USB adapters and non-vSAN
Intel uplinks. Only `pausecount` is unavailable through esxcli. So neither the
counters nor the 1 per mille cutoff are vSAN judgements -- 1‰ is Broadcom's
published network warning figure.

**What is vSAN-specific is the collection path.** The Performance Service models
uplinks carrying vSAN traffic, so the alarm can only fire on those -- 7 of 18
here -- and is structurally silent on the rest.

**Both packs keep their own, by Nick's decision.** netstats collects the driver
breakdown for every vmnic through esxcli; this pack keeps its set on the vSAN
path. Three reasons worth preserving:

1. **The sources differ, so they corroborate rather than repeat.** vSAN health
   fired at 1‰ and 3‰ on five-minute samples while netstats' lifetime delta on
   the same uplink averaged **0.0027‰**. That is 370 to 1,100 times the weekly
   mean, and the disagreement is the finding: it localises the fault to bursts.
   Either number alone misleads. It is a third independent confirmation of the
   burst already measured here -- 1,140 packets in one interval, with the rate
   registering for one sample in eleven -- and of choosing MAX over the period.
2. **Neither may become a single point of failure.** If netstats deferred on
   vSAN uplinks the blind spot returns the moment it is uninstalled; if this
   pack deferred, the pause counts and the vSAN data-path depth go with it.
3. **Only the labelling needed fixing, and it was on this side.** The pNIC view
   now states it covers vSAN-tagged uplinks only.

### Corroboration this pack gained from that work

- **The 0.1% yellow band is the product's own threshold.** The strict-doubling
  scale put yellow at 0.1% on these columns, and `alarm-261` fires at exactly
  1‰. That was arrived at independently and lands on the same number.
- **A zero pause count is often meaningless, now with evidence.** Measured
  through `network.nic.pauseParams.list`: `nmlx5_core` uplinks have PauseRX and
  PauseTX on, `ixgben` uplinks have both off. On every Intel uplink there, a
  zero says nothing at all. The help text says so now.
- **Ring size is driver-dependent**, confirming BACKLOG §3.1: `ixgben` answers,
  `nmlx5_core` faults on all eight uplinks. Ring *utilisation* does not exist as
  a counter on either path.
- **The standby-uplink gap is closed by labelling, not by building.** netstats
  covers every vmnic regardless of vSAN tagging, so this pack needs a pointer on
  the screen rather than empty objects or a divergence supermetric.

**Not a correction this pack needs:** netstats had written that no vendor
publishes a threshold for these counters and corrected it. Nothing here ever
claimed that. This pack already attributed 0.1% to Broadcom for TCP
out-of-order, and now attributes the pNIC band to `alarm-261`.
