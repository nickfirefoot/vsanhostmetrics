# Upstream observations — ESXi `/vsanmetrics` exposition

Issues in the host-side `/vsanmetrics` Prometheus endpoint, for reporting to
Broadcom. Everything here was observed directly on a live host, not inferred
from documentation. Nothing in this file is a defect in this repository's
management pack; our own bugs are tracked in `REPORT.md`.

## Environment

| | |
|---|---|
| Host | `esxi01.example.com` (single ESXi host, vSAN ESA) |
| ESXi version | **VMware ESXi 9.1.1.0.25714478** (`vmware -r` on the host; not discoverable remotely) |
| vSAN cluster UUID | `5deb636e-91b5-11f1-aef5-000c296fd50e` |
| Endpoint | `GET https://<host>/vsanmetrics`, bearer token auth |
| Endpoint server | `BaseHTTP/0.6 Python/3.11.15` (from the `server:` response header) |
| Observed | 2026-09-19 |
| Exposition size | 159 metric families, 30 source branches, 2152 series, ~624 KB |

A full catalogue of the exposition is in `docs/vsan-metrics-catalog.xlsx`,
regenerable with `tools/build_metric_catalog.py`.

Note that all of the below is observed on **ESXi 9.1.1**, i.e. a current
release, not a legacy build awaiting an upgrade.

---

## 1. `sack_send_blocks` and `sack_rexmits` HELP strings are swapped — HIGH

The HELP text for these two metrics describes the *other* metric. The metric
names and the counter values are mutually consistent; only the prose is wrong.

**Observed:**

```
# HELP vmware_esx_tcppkt_sack_send_blocks_total Total requested SACK retransmit of blocks by ESX TCP since boot. [from /net/nics $getVsanNetworkStats]
# HELP vmware_esx_tcppkt_sack_rexmits_total Total sent SACK asks for blocks by ESX TCP since boot. [from /net/nics $getVsanNetworkStats]
```

`sack_send_blocks` is described as *retransmits*; `sack_rexmits` is described as
*blocks sent*. (`sack_rcv_blocks_total` — "Total received SACK asks for blocks"
— is correct and matches its name.)

**Why we are confident the NAMES are right and the descriptions are wrong**, from
since-boot counters on the same scrape:

| Counter | Value |
|---|---|
| `vmware_esx_tcppkt_rcvoopack_total` | 44,810 |
| `vmware_esx_tcppkt_sack_send_blocks_total` | 50,095 |
| `vmware_esx_tcppkt_sndrexmitpack_total` | 12,633 |
| `vmware_esx_tcppkt_sack_rexmits_total` | 11,842 |

- `sack_send_blocks` (50,095) tracks `rcvoopack` (44,810) closely, ratio ≈ 1.12.
  That is exactly the expected relationship if the host emits SACK blocks in
  response to out-of-order arrivals — i.e. the metric counts blocks **sent**,
  per its name. Under the HELP text's reading it would have to track
  retransmits, which are 4× smaller.
- `sack_rexmits` (11,842) is 94% of `sndrexmitpack` (12,633). SACK-driven
  retransmits being most of all retransmits is plausible; the reverse is not.

**Impact:** anyone building dashboards or alerts from the HELP text — the normal
workflow — labels two panels backwards and mis-diagnoses SACK behaviour. This is
a silent correctness problem, since both metrics exist and both return plausible
numbers.

**Suggested fix:** swap the two HELP strings at the source
(`/net/nics $getVsanNetworkStats`).

## 2. No `# TYPE` lines anywhere in the exposition — MEDIUM

```
$ grep -c '^# TYPE' scrape.txt
0
```

Zero `# TYPE` lines across all 159 metric families, while `# HELP` is present for
158 of them. `# TYPE` is optional in the Prometheus text format but is
conventionally emitted, and its absence means a consumer cannot distinguish a
counter from a gauge without guessing.

**Impact:** consumers must infer semantics from the `_total` suffix. That
heuristic is not reliable here — e.g. `vmware_vsan_esa_disk_read_time_max` and
`vmware_esx_heap_usage_ratio` are clearly gauges, while several `_total` names
are cumulative counters requiring rate derivation. Getting this wrong produces
either meaningless rates or meaningless absolute values. Our catalogue's "Type"
column is explicitly labelled a guess for this reason.

**Suggested fix:** emit `# TYPE <name> counter|gauge` alongside each `# HELP`.

## 3. `vmware_esx_pnic_pkt_err_total` has no HELP line — LOW

It is the only family of 159 with no `# HELP` and therefore no declared source
branch, while its direct siblings from the same subsystem are documented:

```
$ grep -c '^# HELP vmware_esx_pnic_pkt_err_total' scrape.txt
0

# HELP vmware_esx_pnic_pkt_total Total Packets processed by ESX physical NIC since boot. [from /net/nics $getVsanNetworkStats]
# HELP vmware_esx_pnic_pkt_bytes_total Total Bytes processed by ESX physical NIC since boot. [from /net/nics $getVsanNetworkStats]
```

The metric itself is exported normally (4 series, split by `vmnic` and
`io_type`). This looks like a simple omission rather than an intentional
internal metric.

**Impact:** NIC error counts are exactly the sort of thing an operator wants to
alert on, and there is no description saying what counts as an "error" (CRC?
drops? both directions?).

## 4. All authentication failures return 403, never 401 — MEDIUM

Three requests, three different credential states, identical status:

| Request | Status |
|---|---|
| No `Authorization` header at all | `403` |
| `Authorization: Bearer definitely-not-a-real-token` | `403` |
| `Authorization: Bearer *******` (masked value pasted by mistake) | `403` |
| Valid token | `200` |

**Impact:** a consumer cannot distinguish "no credential supplied" from
"credential supplied but rejected". For a management pack this matters
concretely: an expired or rotated token is indistinguishable from a
misconfigured one, so the adapter cannot surface a specific, actionable error
and the operator is left guessing. RFC 7235 semantics would use `401` with a
`WWW-Authenticate` header for an authentication failure, reserving `403` for an
authenticated-but-unauthorised caller.

**Suggested fix:** return `401` for missing/invalid credentials.

## 5. `HEAD` returns 501 Not Implemented — LOW

```
$ curl -skI -H "Authorization: Bearer $TOK" https://<host>/vsanmetrics
HTTP/2 501
server: BaseHTTP/0.6 Python/3.11.15
```

`GET` on the same URL returns `200`. This is the default behaviour of Python's
`BaseHTTPRequestHandler` when `do_HEAD` is not implemented.

**Impact:** minor, but a `HEAD` request is the cheapest possible liveness/reachability
probe for a monitoring system, and here it fails in a way indistinguishable from
a real fault. It also forces a full ~624 KB `GET` just to check the endpoint is up.

## 6. Questions rather than defects

- **`sink_type="cold"`** appears on every sample in the exposition and is
  undocumented. What other values exist, and is it intended to be part of series
  identity? If it can change per-scrape it would break rate derivation for
  consumers that key on the full label set.
- **Concurrency of the exporter.** The `server:` header identifies a stock
  Python `BaseHTTP` server. If it is single-threaded, concurrent scrapes
  serialise — relevant because this host exposes **two** `metric_subscriptions`,
  implying more than one intended consumer. What is the supported scrape
  concurrency and interval?
- **Token scope, lifetime and subscription semantics.** Confirmed locally that
  a token is valid across the whole cluster rather than per-host.

  Further observed 2026-09-22, and it changes the model: `metric_subscriptions`
  is a **list, and every entry's token is valid simultaneously**. On
  2026-09-19 the host exposed one entry; by 2026-09-22 it exposed two entirely
  different ones, both returning 200 on two hosts, while the single token
  observed at 03:16 that same day returned 403 by 21:41 on every host.

  So entries are added and removed by something, and a consumer holding a token
  can have it invalidated underneath it within hours. Open questions:

  * **Answered 2026-09-23.** A subscription is a `vim.vsan.MetricProfile` in
    the cluster's `MetricsConfig.profiles` list, created through vCenter with
    `VsanClusterConfigSystem.ReconfigureEx` and the `Host.Inventory.EditCluster`
    privilege. The client generates the token itself as `uuid.uuid4()[:30]` --
    which is why these are 30 characters and look like truncated UUIDs.
    Reference: `vmware-archive/vsan-integration-for-prometheus`,
    `vsan-prometheus-setup/vsanSetupToken.py`.
  * **The reference implementation looks unsafe for multi-consumer clusters.**
    `SetupClusterMetricSpec()` builds `MetricsConfig(profiles=[])`, appends one
    profile, and calls `ReconfigureEx` -- never reading the existing profiles.
    If that replaces the list, running the supported setup tool silently breaks
    every other subscriber. Is `ReconfigureEx` on `metricsConfig` additive or
    replacing? Is there an append-only API, or must consumers race on a
    read-modify-write of a shared list?
  * What is the intended lifetime? An observed invalidation inside ~9 hours
    makes a pasted credential unworkable for unattended monitoring.
  * Can a consumer detect impending invalidation? Combined with issue 4, it
    currently presents as an undiagnosable 403, and an adapter that skips
    failed hosts reports an empty, *successful* collection.

  Documentation referring to `metric_subscriptions[0]` should say "any entry".
- **`server:` header disclosure.** The endpoint advertises its exact Python
  version. Minor information disclosure; worth suppressing on a management
  interface.

---

## Reproduction

```sh
# Token (per host, masked unless -n is passed -- note the -n, it is not obvious):
configstorecli config current get -c vsan -g system -k vsan -n
#   -> metric_subscriptions[].auth_token

curl -sk -H "Authorization: Bearer $TOK" https://<host>/vsanmetrics -o scrape.txt

grep -c '^# TYPE' scrape.txt                                  # issue 2 -> 0
grep '^# HELP vmware_esx_tcppkt_sack' scrape.txt              # issue 1
grep -c '^# HELP vmware_esx_pnic_pkt_err_total' scrape.txt    # issue 3 -> 0
curl -sk -o /dev/null -w '%{http_code}\n' https://<host>/vsanmetrics   # issue 4 -> 403
curl -skI -H "Authorization: Bearer $TOK" https://<host>/vsanmetrics   # issue 5 -> 501
```
