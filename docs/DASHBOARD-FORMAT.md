# VCF Operations dashboard JSON — what we know

Reverse-engineered from a dashboard exported out of `operations.example.com`
(VCF Operations 9.x) on 2026-09-23. The raw export is committed at
`docs/assets/dashboard.sample.json` so this is checkable.

There is **no public API for dashboards** — `/suite-api/api/dashboards` is a
genuine 404, `/suite-api/internal/dashboards` is blocked at the web tier
regardless of role, and `POST /api/content/operations/export` only exports
content the calling user *owns* (sharing grants visibility, not ownership).
So the only way to obtain one of these is the UI's Export button.

## Envelope

A UI export is a zip containing `dashboard/dashboard.json`:

```json
{
  "entries": {},
  "dashboards": [ { ...one object per dashboard... } ],
  "uuid": "<export uuid>"
}
```

Inside a pak, dashboards instead go one-per-subdirectory as
`content/dashboards/<name>/<name>.json`, with optional
`content/dashboards/<name>/resources/<name>.properties` for localization.
`mp-build` enforces that layout (`build_subdirectories`).

**[unverified]** Whether the pak form wants this same `{entries, dashboards[],
uuid}` envelope or a bare dashboard object. Test before relying on it.

## Dashboard object

| Field | Observed | Notes |
|---|---|---|
| `name` | `"sample"` | display name |
| `id` | uuid | referenced by every widget's `tabId` |
| `userId` / `lastUpdateUserId` | uuid | **owner** — this is why API export missed it |
| `shared` | `true` | visibility, independent of ownership |
| `gridsterMaxColumns` | `12` | the layout grid is 12 columns wide |
| `widgets` | array | see below |
| `homeTab`, `rank`, `locked`, `hidden`, `disabled`, `autoswitchEnabled` | | presentation flags |
| `dashboardNavigations` | `{}` | widget-to-widget interaction wiring, empty here |

## Widget object

```json
{
  "tabId": "<dashboard id>",
  "id": "<widget uuid>",
  "type": "MetricChart",
  "title": "Metric Chart",
  "config": { "title": "Metric Chart" },
  "gridsterCoords": { "x": 1, "y": 19, "w": 4, "h": 6 },
  "states": [ { "key": "...", "value": "<url-encoded>" } ]
}
```

Layout is `gridsterCoords` on a 12-column grid. `x`/`y` are grid cells, not
pixels; `h: 6` was a normal single-widget height in the sample.

### `states` encoding

`states[].value` is **URL-encoded**, prefixed by a one-letter type tag and a
colon. Decoded:

```
s%3A%7B%22dateRange%22...  ->  s:{"dateRange":"dashboardTime","dateFrom":null,
                                 "dateTo":null,"timeFrom":null,"timeTo":null}
o%3A                       ->  o:        (empty — widget never configured)
```

`s:` is a JSON payload; `o:` appeared empty on an unconfigured widget. The
`key` is composite:

```
perm<StateName>_<WidgetType>_widget_<dashboardId>_<widgetId>
```

so state keys have to be rewritten whenever a widget or dashboard id changes.
That is the main hazard in hand-authoring these.

## Metric binding

From a *configured* `MetricChart` (`docs/assets/dashboard.sample-configured.json`):

```json
"metric": {
  "mode": "resource",
  "resourceMetrics": [{
    "metricKey":      "cpu|demandPct",
    "metricName":     "CPU|Demand",
    "resourceId":     "resource:id:0_::_",
    "resourceName":   "esxi03.example.com",
    "resourceKindId": "002006VMWAREHostSystem",
    "metricUnitId":   "percent",
    "unit":           "%",
    "redBound": null, "orangeBound": null, "yellowBound": null,
    "colorMethod": 2, "isStringMetric": false
  }],
  "resourceKindMetrics": []
}
```

The important parts:

- **`metricKey`** is the attribute key as the adapter defines it. For this pack
  that is the raw perfsvc id -- `rxMissErr`, `txSbSpaceMin` -- and `metricName`
  is the display path.
- **`resourceKindId`** is an internal encoded id (`002006VMWAREHostSystem`),
  *not* the plain adapter kind key. How that encoding is derived for a custom
  adapter kind such as `VsanPnic` is **[unverified]**.
- **`resourceMetrics` binds specific objects; `resourceKindMetrics` binds a
  whole kind.** The second is what a rapid dashboard needs -- every vmnic in
  the cluster, not one hand-picked instance -- and it is empty in every sample
  so far, so its element shape is unknown.
- Colour bounds (`redBound`/`orangeBound`/`yellowBound`) are per-widget, so a
  panel can carry thresholds without any alert definition. Useful given
  thresholds are deliberately deferred.

Generic config keys that appear on every configured widget: `refreshInterval`
(seconds), `widgetId` (must equal the widget's own `id`), `selfProvider`,
`customFilter`, `relationshipMode`, `description`.

## Widget types seen

`MetricChart`, `HealthChart`, `ResourceRelationshipAdvanced`, `PropertyList`.

`Heatmap`, `TextDisplay`, `View`.

## The text widget: `TextDisplay`

```json
{
  "type": "TextDisplay",
  "config": {
    "description":  "inline text, shown when no location is set",
    "locationUrl":  "",        // fetch the body from a URL instead
    "locationFile": "",        // or from an uploaded file
    "viewModeHTML": true,      // render as HTML -- hyperlinks work
    "refreshInterval": 300
  }
}
```

Three ways to supply the body, and the choice matters:

- **`description`** -- inline. Travels with the dashboard, works with no
  egress, but changing it means re-importing the dashboard everywhere.
- **`locationUrl`** -- fetched at render time. Points at e.g.
  `https://raw.githubusercontent.com/nickfirefoot/vsanhostmetrics/main/content/help/network-rapid.html`,
  so guidance can be corrected in the repo and every customer picks it up on
  next render, with no redeploy. Requires egress **from the browser**, and
  degrades to an empty panel without it.
- **`locationFile`** -- an uploaded file.

`viewModeHTML: true` means KB links and formatting work.

This matters more than convenience: the SDK gives metrics a label but **no
description field** (`define_metric` has no such parameter, and `add_attribute`
writes only a nameKey), so there is nowhere per-metric to hang "what this
means". A TextDisplay widget is the only place interpretation can live.

Sensible split: essentials inline via `description`, depth via `locationUrl`.

## The heatmap: `Heatmap`

```json
"config": {
  "configs": [{
    "groupBy": { "adapterKind": "VMWARE", "resourceKind": "ClusterComputeResource",
                 "id": "004null002006VMWAREClusterComputeResource",
                 "type": "resourceKind", "text": "Cluster Compute Resource" },
    "colorBy": { "value": "" },          // the metric to colour cells by
    "sizeBy":  { "value": "" },
    "color": { "thresholds": { "values": [0, 50, 100],
                               "colors": ["#67CA16", "#FFDB24", "#FF4D2E"] } },
    "solidColoring": false, "relationalGrouping": false, "focusOnGroups": true
  }],
  "refreshInterval": 300, "mode": "resource", "depth": 10
}
```

Thresholds and colours are per-widget, so a panel carries its own banding with
no alert definition behind it -- useful while thresholds are deliberately
deferred. Green/amber/red are `#67CA16`, `#FFDB24`, `#FF4D2E`.

### The `resourceKindId` encoding, decoded

Resource kinds are referenced by an encoded id, not the plain key:

```
002 + <3-digit length of adapterKind> + <adapterKind> + <resourceKind>
```

Verified against both observed samples:

| Encoded | adapterKind | resourceKind |
|---|---|---|
| `002006VMWAREHostSystem` | `VMWARE` (6) | `HostSystem` |
| `002006VMWAREClusterComputeResource` | `VMWARE` (6) | `ClusterComputeResource` |

`groupBy.id` prefixes that with `004null`. For this pack, `adapterKind` is
`VsanHostMetrics` (15 characters), so:

```
VsanPnic     -> 002015VsanHostMetricsVsanPnic
VsanHostNet  -> 002015VsanHostMetricsVsanHostNet
VsanTcpIp    -> 002015VsanHostMetricsVsanTcpIp
```

## Importing: UI only

`POST /api/content/operations/import` rejects a UI-exported dashboard zip with
`INVALID_FILE_FORMAT` -- tested with an untouched export straight from the UI,
so the API's content format is **not** the UI's dashboard format, and the API
cannot be used to ship or test dashboards. Use **Dashboards -> Import** in the
UI, or ship them inside the pak under `content/dashboards/<name>/<name>.json`.

## What is still unknown

`colorBy.value` and `sizeBy.value` were empty in the sample -- the heatmaps
were placed and grouped but never pointed at a metric. The field exists and is
named; its populated form (a bare attribute key, or an encoded id like
`groupBy.id`) has not been observed.


## Scoreboard: object-enumerated, and why that rules it out for a shipped pack

A Scoreboard completed through the UI (`docs/assets/dashboard.scoreboard-working.json`)
settles how object scope works, and it is not what `mode: "resourceKind"`
suggests:

```json
"selfProvider": {"selfProvider": true},
"metric": {"mode": "resourceKind", "resourceKindMetrics": [...]},
"resource": [
  {"name": "esxi03.example.com [vmnic2]", "id": "resource:id:0_::_"},
  {"name": "esxi04.example.com [vmnic2]", "id": "resource:id:1_::_"}
]
```

**`mode: "resourceKind"` only selects which kind's metrics are offered. The
objects come from `resource[]`, enumerated by name**, with index-placeholder
ids (`resource:id:N_::_`). A self-providing Scoreboard therefore contains a
hand-picked object list.

Consequences, and they are decisive:

- It **cannot ship in a pak**. The names are specific to the estate it was
  built in; a customer would import references to NICs that do not exist.
- It **does not scale**. Add a host and the dashboard must be edited.
- It gives **no scope control** -- every enumerated object appears at once,
  which is what "all NICs on all hosts in one jumbled scoreboard" looks like.

An empty `resource: []` is what Operations means by "widget configuration is
not complete": the widget has no objects, so there is nothing to render.

### Therefore

| Need | Widget |
|---|---|
| Scan every object of a kind at once | **Heatmap** -- kind-scoped via `groupBy` + `attributeKind`, never enumerates objects |
| Key figures for a *selected* object | **Scoreboard with `selfProvider: false`**, fed by a provider widget |

This is exactly the layout Broadcom's own vSAN dashboard uses, and the reason
is now clear rather than stylistic: their fifteen Scoreboards are all
`selfProvider: false` precisely because enumerating objects does not survive
being shipped to someone else's environment.

### Metric entry, as the UI writes it

```json
{ "metricKey": "rxMissErr",
  "metricName": "pNIC RX missed error (ring buffer full)",
  "resourceKindName": "vSAN Physical NIC",
  "resourceKindId": "resourceKind:id:0_::_",
  "yellowBound": null, "orangeBound": null, "redBound": null,
  "colorMethod": 1, "handleOldColoring": false,
  "isStringMetric": false, "link": "", "id": "extModel3435-1" }
```

Note `metricName` is our generated label, confirming the adapter's labels flow
through to dashboard content. Bounds default to `null` (no banding) and must be
set explicitly.

## Still unknown

The **provider widget**. Broadcom's is a `View` with a `viewDefinitionId`,
which is separate shippable content. Whether a simpler provider exists that
needs no view definition -- and its config shape -- has not been observed. This
is the last gap before dashboards can ship in the pak.
