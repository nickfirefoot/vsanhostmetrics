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

Not yet seen, and both needed: **Text** and **Heatmap**.

## What is still unknown

Two gaps block generating a rapid dashboard:

1. **The Text widget.** Never present in any export so far, so its `type`
   string is unknown, as is whether the body is inline in `config` or
   references a file under `content/files/txtwidget/`. This is what carries
   interpretation guidance and KB links -- and it matters more than usual
   because the SDK gives metrics a label but **no description field**, so a
   text widget is the only place that guidance can live.
2. **`resourceKindMetrics`.** Binding by *kind* rather than by instance is the
   whole point of a rapid dashboard. Every sample has it empty, so the element
   shape is unknown, as is how `resourceKindId` encodes a custom adapter kind.
   A configured **Heatmap** would show both at once, since a heatmap is
   inherently kind-scoped.

Everything else -- envelope, layout, state encoding, metric keys, colour bounds
-- is now known well enough to generate from.

## Note on the UI bundle

Widget type names are presumably enumerated in the dashboard app's JavaScript,
but `/vcf-operations/ui/` serves only the login page unauthenticated; the app
bundle loads after session auth. Not reachable with an API token.
