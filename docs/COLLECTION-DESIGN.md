# Data gathering redesign

Written 2026-09-23 after measuring both data sources against the live lab.
Supersedes the single-source design in `app/adapter.py`.

## Why the current design has to change

It assumes one source, one credential and one shape. Each of those turned out
to be wrong.

**One source.** `/vsanmetrics` is not the only place these metrics live, and
for networking it is the weaker one. `vsan-tcpip-stats` carries 32 metrics
against our 11, including TCP errors, ECN, zero-window, half-open drops and
per-mille rates we cannot compute at all. Meanwhile perfsvc returns nothing for
heaps, slabs and CMMDS workload. Neither source dominates.

**One credential.** The host bearer token is a `MetricProfile` in a
cluster-wide list we do not own, cannot read back through the API
(`metricsConfig` returns `None`), and which is removed from under us -
observed twice in 24 hours. vCenter credentials have none of those properties.

**One shape.** Counters and gauges need different handling; we now know 178 of
385 are counters and the rest are not. perfsvc returns pre-reduced rates on a
fixed 5-minute cadence, the host returns raw cumulative counters at any
interval. A single code path cannot serve both.

## Architecture

A `Collector` protocol, two implementations, one merge step.

```
                    ┌───────────────────────┐
  ESXi hosts ──────►│ HostScrapeCollector   │──┐
  (bearer token)    │  /vsanmetrics         │  │
                    └───────────────────────┘  │   ┌─────────────┐
                                               ├──►│   merge     │──► CollectResult
                    ┌───────────────────────┐  │   │ ObjectKey → │
  vCenter ─────────►│ PerfSvcCollector      │──┘   │  Grouped    │
  (RO credentials)  │  VsanPerfQueryPerf    │      └─────────────┘
                    └───────────────────────┘
```

Both emit the existing `Dict[ObjectKey, Grouped]`, so `collect()` and the
generated schema are unchanged downstream. That is the whole point of having
built `group()` around a model: the merge step does not care where a sample
came from.

### Source routing

Per family, config-driven, defaulting to the measured recommendation:

| Resource kind | obj/host | Source | Why |
|---|---|---|---|
| `EsxTcpIp` | 1 | **perfsvc** | 32 metrics vs our 11; errors and congestion we cannot see |
| `EsxPnic` | 2 | **perfsvc** | 16 vs 6; CRC, carrier, FIFO, pause, port drops |
| `EsxRdt` / `VsanRdt` | 3 | **perfsvc** | min/max/avg latency, socket space, queue depth |
| `EsxWorld` | 267 | **perfsvc** | comparable depth, removes 267 objects/host |
| `HostCpu` | 65 | **perfsvc** | comparable, removes 65 objects/host |
| `VsanVdisk` / `VsanVscsi` | 18 | **perfsvc** | comparable or better |
| `VsanEsa` | 9 | **host** | 162 metrics vs 6 |
| `VsanDom` | 1 | **host** | 80 vs 14 |
| `VsanMemory` | 1 | **host** | 62 vs 2 |
| `VsanCmmds` | 1 | **host** | perfsvc returns no data |
| `EsxHeap` / `VsanHeap` | 62 | **host** | perfsvc returns no data |
| `EsxSlab` | 62 | **host** | perfsvc returns no data |
| `VsanDisk` | 2 | **host** | perfsvc returns no data (ESA has no disk groups) |

Host scrape drops from **494 objects/host to ~160**, and networking gets
*deeper* rather than thinner.

### Degradation

Each source fails independently and says so. The failure mode that must not
survive this redesign is the current one: every host 403s, `collect()` skips
them all, and Operations receives an **empty successful collection** with no
error. Requirements:

* a source failing entirely raises a specific, named error
* a 403 from the host names token replacement as the likely cause
* partial failure (3 of 4 hosts) still returns the 3 and logs the 1
* if a family's configured source is unavailable, fall back to the other
  source where one exists, and say so in the log

## Credentials

| Source | Credential | Failure mode |
|---|---|---|
| host scrape | bearer token, pasted | removed from the cluster profile list without warning |
| perfsvc | vCenter user + password | expires/rotates on your schedule, not vSAN's |

Read-only is sufficient for perfsvc - verified. `VsanPerfGetSupportedEntityTypes`
and `VsanPerfQueryPerf` need `System.View` and `System.Read`, nothing more. No
`Host.Inventory.EditCluster`, which is what registering a subscription would
have cost.

**This is the strongest argument for the hybrid.** A pack holding vCenter
credentials anyway loses little by also using them for metrics, and gains a
credential that does not evaporate daily.

## Open decisions

1. **Ship both collectors at once, or perfsvc first and keep the host scrape
   as-is?** Both is more work; perfsvc-first gets the network depth soonest.
2. **One adapter instance or two?** One instance holding both credentials is
   simpler to operate; two makes the failure domains independent and lets a
   site run host-only where vCenter access is not granted.
3. **Is the host scrape worth keeping at all**, given it costs a fragile
   credential for 308 metrics that are mostly deep diagnostics? A defensible
   position is perfsvc-only, accepting the loss.

## Not decided by this document

Counter/gauge classification, metric keying and the generated model all carry
over unchanged - they were built against the exposition and remain correct for
the host source. perfsvc needs its own generated model, derived the same way
from `VsanPerfGetSupportedEntityTypes` plus a live query, since the schema
understates what the API actually returns (32 metrics where 16 are advertised).
