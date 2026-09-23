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

## Widget types seen

`MetricChart`, `HealthChart`, `ResourceRelationshipAdvanced`, `PropertyList`.

## What is still unknown

The sample widgets were placed but never configured, so `config` is just
`{"title": ...}` and the `o:` state is empty. Two things we still cannot write:

1. **The Text widget.** Its `type` string is unconfirmed, as is whether its
   body is inline in `config` or references a file under
   `content/files/txtwidget/`. This is what a rapid dashboard needs for
   interpretation guidance and KB links — and it matters because the SDK gives
   metrics a label but no description field, so a text widget is the only place
   that guidance can live.
2. **Metric binding.** No sample shows how a widget names a resource kind and
   an attribute key. Without it, a heatmap cannot be pointed at
   `VsanPnic` / `rxMissErr`.

To close both, export one dashboard containing a **configured** Text widget
(with some text and a hyperlink) and a **configured** Heatmap (any object type
and metric). Configured, not merely dropped on the canvas — an unconfigured
widget carries none of the information we are missing.
