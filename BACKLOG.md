# BACKLOG

## Pending next release — batched, do not ship individually

Changes committed to source but **not yet in a published pak**. Batch these
into one release rather than cutting a version per fix.

| Item | Status | Needs |
|---|---|---|
| **Object-name overwrite** | **fixed, needs rebuild** | the pack renamed every vCenter HostSystem to its MoRef; names correct themselves once redeployed |
| Drop `Actual`/`Raw` duplicate metrics | proposed | ~50 metrics, identical to their base in every observed pair; pure clutter on a dashboard |
| Per-mille to percent conversion | proposed | `portRxDrops = 1` means 0.1% and nothing says so. Evidence settled; needs the go-ahead since it changes emitted values |
| Derived error ratios | proposed | raw counters have no perspective -- 4 errors against 1M packets is noise, against 1K it is a fire. Compute `*PerMillionPackets` in the adapter where numerator and denominator are both already in hand |
| **Namespace metric keys into a tree** | proposed, **breaking** | keys are flat (`rxMissErr`). Operations renders `\|`-separated keys as a tree, so `Network\|pNIC\|Errors\|RX missed` would fan 994 attributes into browsable branches instead of one list. Changing a key orphans its history and breaks any dashboard or symptom referencing it, so it is a major-version change, not a tidy-up |
| **Per-family collection toggles, `host-cpu` off by default** | proposed | `VsanHostCpu` is 244 objects for `coreUtilPct`/`pcpuUsedPct`/`pcpuUtilPct` -- generic per-core host CPU the built-in vCenter adapter already collects. With `VsanDomWorld` (315) that is 66% of all objects for 24% of the series. `vsan-cpu` (4 objects, includes `readyPct`) answers "is vSAN CPU-starved" and should stay on |
| **Restructure into fewer top-level branches** | proposed | a host currently fans straight out into ~5 network families and 6 DOM families. Target: Network / Storage / Cluster / Compute / VM at the top, everything else nested beneath. Cosmetic in the guide, structural if done via metric keys -- see the namespacing row |
| **Pick a better default throughput unit** | proposed, small | `DATA_RATE` is a single family holding bits and bytes, binary and decimal, each with a conversion factor -- so `Mbit/s` is already selectable in the UI from the `B/s` we declare, and no value conversion is needed. The open question is only which default reads best unscaled. We declare `BIBYTE_PER_SECOND` (binary, scales to KiB/s and MiB/s) because HCIBench charts these as `binBps`; `BYTE_PER_SECOND` (decimal, scales to kB/s and MB/s) matches how networking is normally discussed. **[unverified]** whether Operations converts across bit/byte within the family or only within one subtype -- worth checking in the UI before changing anything |
| **Drop the redundant "(%)" from labels** | proposed | added so the per-mille conversion was visible in the name, but Operations renders the `RATIO.PERCENT` unit alongside the value anyway, giving "Inbound Packet Drop Rate of vSwitch Port (%)  0.1 %". Several official names already say "Rate" or "Percentage" too. Remove the suffix and let the unit carry it -- the conversion itself stays |
| Real EULA (`eula.txt`) | committed | rebuild — the scaffold placeholder left the install form's agreement box empty |
| Network rapid dashboard | generated, imports, panels error | `colorBy` binding confirmed against a working example |
| `TextDisplay` inline body | does not render | a configured example; `description` was assumed to be the body field |
| `TextDisplay` `locationUrl` | "URL is not available" | lab egress is fine (Cloud Proxy reaches raw.githubusercontent 200/56ms), so the suspect is `text/plain` + `nosniff` being rejected in HTML view mode. GitHub Pages would serve `text/html` and settle it |
| Backpressure + disk rapid dashboards | designed, not built | the same `colorBy` fix; then ~20 min each |

| **Cluster selector on rapid dashboards** | **schema confirmed 2026-09-25** | Object List (cluster, selfProvider on) → Scoreboard (selfProvider off, `relationshipMode -1`, `depth 4`, `subMode resourceKindAll`) wired by one `widgetInteractions` entry; `dashboardNavigations` stays empty. Proven in the UI on a cluster-scoped kind; `docs/assets/dashboard.interaction-working.json`. Builder emits it (`scoreboard_receiver`, `object_list_pinned`). **Open:** (1) whether depth 4 reaches host-scoped kinds (pNIC is cluster → host → pNIC) — `dist/dashboards/rapid-receiver-probe.zip` answers it; (2) the *generic* cluster-list provider — the export is pinned to one cluster by MoRef, which only resolves on the system it came from. Needs one more UI export with the Object List rooted at vSphere World / vCenter filtered to Cluster Compute Resource |

### Rapid dashboards — the full set

Designed in `content/DASHBOARDS.md`, blocked on the Scoreboard binding probe.
Once that is confirmed, each is roughly twenty minutes: the panel selection and
thresholds are already decided, only the widget envelope was wrong.

A *rapid* dashboard answers "is this subsystem bad right now?" across every
object at once. Not root cause. Built from **error, loss and congestion**
signals, never throughput -- a NIC dropping 0.1% of frames still moves traffic
at line rate, so a throughput panel shows green through the exact failure the
screen exists to catch.

| # | Dashboard | State | Signals |
|---|---|---|---|
| 1 | **Rapid vSAN Network** | panels chosen, generator written | pNIC hardware errors (`rxCrcErr`, `rxFrmErr`, `rxLgtErr`, `rxOvErr`, `rxFifoErr`, `txCarErr`, `txWinErr`, `txHeartErr`, `txAbortErr`), ring overrun (`rxMissErr`), drop rates (`portRxDrops`, `portTxDrops`, `rxPacketsLossRate`, `txPacketsLossRate`, `ioChain*drops`), fabric backpressure (`pauseCount`, `pfcCount`), TCP health (`tcpRcvoopackRate`, `tcpTxRexmitRate`, `tcpRcvdupackRate`, `tcpRxErrRate`) |
| 2 | **Rapid vSAN Backpressure** | designed | congestion by type (`congestion`, `readCongestion`, `writeCongestion`, `unmapCongestion`, `recoveryWriteCongestion`, `segCleanerUnmapCongestion`), contention vs resync (`componentCongestion`, `sharedCongestion`, `resyncReadCongestion`), RDT pressure (`txSbSpaceMin`, `rxSbSpaceMin`, `txCtxQMax`, `txQLatAvg`, `numReadyDelay`, `kaReset`) |
| 3 | **Rapid vSAN Disk** | designed | **not** error-based -- there are no disk error counters anywhere in the Performance Service. Detects a sick device by latency behaviour: service-time outliers (`maxReadTimePerf`, `maxWriteTimePerf`, `maxReadTimeCapacity`, `maxWriteTimeCapacity`), device-vs-guest divergence (`latencyDevDAvg` vs `latencyDevGAvg`, `latencyDevKAvg`), physical-vs-vSAN-layer latency, queue depth (`outstandingCmdCount`) |

Notes that must survive into the built dashboards:

- **`kaReset` deserves its own panel.** RDT keepalive resets are a strong
  grey-state signal that survives a perfectly healthy-looking NIC.
- **Disk panels must use max, not mean.** A dying NVMe shows as
  `maxWriteTimePerf` spiking while median latency and IOPS stay flat; a
  mean-based panel hides exactly that. Compare each disk against its siblings
  on the same host rather than a fixed threshold.
- **State the blind spot on the screen.** No disk media-error counters and no
  NIC ring-buffer *utilisation* exist, so a green disk panel does not mean
  healthy hardware. The text panel says so.

### Out of scope — separate packs, separate streams

Context for both has been handed off to their own agents and removed from here,
so this backlog stays about the vSAN pack.

| Pack | Directory | Dashboards will be |
|---|---|---|
| vSphere network statistics | `~/vsphere-net-stats-mp/` | `Rapid Network <subject>` |
| Memory tiering | `~/vsan-mem-tier-mp/` | `Rapid MemTier <subject>` |

Note for whoever picks up memory tiering: this pack's `VsanMemory` (50 metrics)
and `VsanSystemMemory` cover vSAN's own heap and slab consumption, which is a
different subsystem from memory tiering. Do not conflate them.

### Blocked on hardware or configuration, not on work

| Dashboard | Blocked by |
|---|---|
| **Rapid vSAN HBA/OSA** | an OSA cluster. The schema is *richer* than ESA's -- `disk-group` carries scheduler congestion, `iopsDelayPctSched`, `latencySched`, and resync broken out by reason (evacuation / repair / policy / rebalance); `capacity-disk` adds `deleteCongestion` plus physical- and vSAN-layer latency on one object; `ddh-disk` adds `logCongestion`. All silent on ESA, so unverifiable here. Still no error counters |
| **Rapid vSAN File Services** | vSAN file services enabled somewhere. Only 8 metrics (`readLatency`, `writeLatency`, `readOpTotal`, `writeOpTotal`, `requested`/`transferred` bytes). Requested vs transferred is the one genuinely useful pair; no share, quota, session or protocol-error metrics exist, so it will be weak |
| **iSCSI** | iSCSI enabled. `vsan-iscsi-host` / `-target` / `-lun`, 10 metrics each |
| **S3 / object store** | nothing to build. Searched all 69 entity types and 839 documented metrics for s3/bucket/object store: zero matches. A future release would surface as a new entity type that `tools/model_from_perfsvc.py` picks up without code changes |

### Lower priority, worth considering

- **Resync / rebuild rapid.** `VsanHostDomowner` carries 71 resync metrics
  including `numPendingDecomResyncJobs`, `avgResyncParallelism` and
  `numInflightPriorityResyncJobs`. Answers "is it rebuilding, why, and is it
  keeping up" -- the question immediately after a host or disk drops out.
- **Capacity rapid.** `VsanClusterCapacity` is only 6 metrics (`total`, `used`,
  `free`, `dedupRatio`, `savedByDedup`, `totalDpOverhead`), but capacity
  exhaustion is the failure that takes a cluster read-only.
- **Memory / heap rapid.** `VsanMemory` (50 metrics) and `VsanSystemMemory`.
  Heap exhaustion is the classic grey failure: everything works until an
  allocation does not.

### Scale notes (from the collector-binding question)

An adapter instance is **pinned to one collector** — all collection for that
vCenter runs in one container on one Cloud Proxy and does not fan out.

- More clusters in a vCenter: same instance, same proxy.
- More vCenters: one instance each, assignable to different proxies.
- One very large vCenter: **does not split**; that proxy is the ceiling.
- HA: assign the instance to a *collector group* rather than a single proxy.

Measured headroom: 847 objects collected in ~9s against a 5-minute cycle, so
roughly 30x per instance. The first constraint at a large site is more likely
**object count in the analytics cluster** than proxy CPU — `VsanDomWorld` alone
is 315 objects on four hosts and scales per host. Per-family collection
toggles (already on this backlog) are the lever for that.

**Blocking all dashboard work:** the lab still runs **1.1.9**, which collects
nothing (`ObjectKeyAlreadyExistsException`, fixed in 1.2.0). With zero
`VsanPnic` objects the panels cannot render, so a correct dashboard and a
broken one look identical. Install 1.2.0 before drawing any conclusion.


Work not done, roughly in the order it becomes worth doing. Items move out of
here when they land in a commit.

## Blocking further confidence

**Cold-run the `REQUIREMENTS.md` checklist.** The real test of a runbook is
someone following it without the context that wrote it. Run steps 1-3 from a
clean shell and see whether the document is followable or silently assumes
things only this project knows. Cheap, and it is the only way to find out.

**Verify the fast path.** `README.md` §7 claims a code-only change needs only
a rebuild, a `DIGEST` swap in the Cloud Proxy's `.conf`, and a collector
restart — no pak reinstall. That is the README's claim, not a tested fact, and
several other things lean on it. Confirm on the first code-only iteration.

Relevant data point from 2026-09-22: **adding a host to the adapter instance
did not recycle the container** (`restarts=0`, `StartedAt` unchanged), so the
config change applied hot and the rate cache survived — the existing two hosts
never dropped a cycle. Good news for reconfiguration, but it means the
collector does *not* restart the container on every change, so a digest swap
may well need an explicit restart rather than being picked up. Test that
specifically rather than assuming.

~~**Finish steps 9-10.**~~ ✅ Done 2026-09-22. Pak installed, adapter instance
created, three `VsanHostTcpIp` objects collecting with real identifiers, values
cross-checked against an independent computation outside Operations. The full
ten-step checklist in `REQUIREMENTS.md` is verified.

## Automation, once the above is proven

**`post-receive` hook on a bare repo on the build host.** Push over SSH, hook
runs tests, bumps `Implementation-Version`, runs `mp-build`, and either swaps
the digest (fast path) or uploads the pak. Deliberately deferred: automating a
sequence whose last steps have never been executed would give repeatability of
the wrong thing. Design notes are in the session history; the shape is a bare
repo plus hook rather than a webhook receiver, because no inbound listener is
needed beyond SSH.

## Correctness

~~**`io_type` label collision silently discards half the traffic.**~~
✅ **Fixed 2026-09-22** in the model-driven rebuild. The schema is now generated
from the exposition, and the rule that fixes it is structural rather than a
special case: a label distinguishing *entities* becomes object identity, a
label distinguishing *measurements of one entity* becomes part of the metric
key. So `total{io_type=rx}` and `total{io_type=tx}` are `total|rx` and
`total|tx`, and the same applies automatically to pnic, dom, vdisk and vscsi.
`group()` reports any unexpected collision instead of overwriting, and
`test_io_type_does_not_collide` fails against the old keying.

Derived percentages are fixed too: each numerator now gets a denominator of
matching direction. On measured esxi01 rates `duplicateAckPct` moved from
0.097% to 0.122%.

**Review the 21 low-confidence metric kinds.** `tools/classify_metrics.py`
infers counter-vs-gauge from observed behavior, name suffix and HELP wording,
because the exposition carries no `# TYPE` lines. 178 counters and 207 gauges,
of which 21 fall to the safe default (gauge). Evidence and confidence per
metric are in `docs/metric-kinds.json`. A counter misfiled as a gauge shows an
obvious since-boot ramp; the reverse would be a plausible-looking wrong number,
which is why the default leans this way. Worth eyeballing the low-confidence
list against real graphs once data accumulates.

**Token invalidation: the mechanism is now understood, and it is overwriting
rather than expiry.** Corrects the earlier "rotation" framing.

Source: `vmware-archive/vsan-integration-for-prometheus`,
`vsan-prometheus-setup/vsanSetupToken.py`.

```python
def GenerateRandomToken():
   return str(uuid.uuid4())[:30]           # truncated UUID -- hence 30 chars

def SetupClusterMetricSpec(token):
   metricsConfig = vim.vsan.MetricsConfig(profiles=[])    # starts EMPTY
   metricsConfig.profiles.append(vim.vsan.MetricProfile(authToken=token))
   spec = vim.vsan.ReconfigSpec()
   spec.metricsConfig = metricsConfig
   return spec

clusterConfigSystem.ReconfigureEx(cluster, spec)          # vCenter, per cluster
```

What this establishes:

* A subscription is a `vim.vsan.MetricProfile` in the cluster's
  `MetricsConfig.profiles` **list**. Multiple profiles coexist and every
  token is valid simultaneously -- which is why `metric_subscriptions` had two
  entries.
* Registration happens **through vCenter**, per cluster, via
  `VsanClusterConfigSystem.ReconfigureEx`, requiring the
  `Host.Inventory.EditCluster` privilege. Not on the host.
* **The client generates the token**, so a consumer can register a
  subscription it owns rather than borrowing one.
* Tokens do **not** expire. Upstream documentation states a token is valid
  "unless it has been overwritten by a new one".

So the 403 on 2026-09-22 was our token being **overwritten**, not expiring. Note
the reference tool builds `profiles=[]` and appends a single token without ever
reading the existing profiles first -- so running it is at best ambiguous about
preserving other consumers' subscriptions, and is the likely cause.

**Working hypothesis: staggered rotation with overlap.** Two subscriptions may
exist deliberately so their lifetimes overlap - A valid 00:00-24:00, B valid
12:00-36:00 - giving any consumer that re-reads the token a window to pick up
the new one before its current one dies. Standard key-rotation practice, and it
would explain two subscriptions with no visible second consumer.

Falsifiable, and a monitor is running to test it:

| Observation | Conclusion |
|---|---|
| one token fails, the other survives | staggered rotation |
| both fail in the same poll | the profile list was replaced wholesale |

Counter-evidence so far: at 2026-09-22 03:00 there was **one** subscription, and
by 21:50 there were **two**. Steady-state overlap should show two at all times,
so either the scheme was still establishing or something else added the second.

**If the hypothesis holds, the token is meant to be re-read, not held** - and a
consumer pasting a static credential is using the mechanism wrong. That is
awkward for this pack specifically: the adapter runs in a container on a Cloud
Proxy and cannot reach the host's config store, so "just re-read it" is not
available to us. It would also turn occasional breakage into daily breakage,
which makes option 1 below insufficient on its own.

Two dead ends already ruled out, so nobody repeats them:

* `hostd.log` records ConfigStore Begin/Commit transactions but never the key
  contents, and they fire every 20-40 minutes for unrelated reasons.
* `generation_num` / `generation_time` under `host` do **not** track
  `metric_subscriptions`. Observed `generation_time` moving 20.76 hours while
  `generation_num` stayed at 5, across a period when the tokens definitely
  changed.

**What this pack should do about it**, in increasing order of effort:

1. *Minimum, and still required regardless:* when every host fails to scrape,
   surface a specific error rather than an empty successful collection. A 403
   should say the token may have been overwritten and name the fix. Today the
   adapter reports success with no objects, which is invisible in Operations.
2. *Better:* register our own `MetricProfile` at configuration time, so the
   pack owns its subscription instead of borrowing one. Costs a vCenter
   credential and the `Host.Inventory.EditCluster` privilege, which is a real
   escalation from the current read-only-against-a-host design and crosses
   `HANDOFF.md` fence #3. A deliberate decision, not a quiet one.
3. *Necessary if we ever do (2):* read existing profiles and append, never
   replace. Whatever overwrote our token did the wrong thing here and we should
   not repeat it -- it would break every other consumer on the cluster.

Open question for the vendor, now sharper: is there an append-only way to add a
subscription, or must every consumer read-modify-write a shared list and race
each other?

**`verify_certs: true` is untested, and the reasoning behind it may be wrong.**
See the note under Blocking, above -- accepted certs land in Operations' trust
store while `scrape()` runs inside the container with its own CA bundle.

## Completeness

**Eleven zDOM families the service returns but never advertises.** The
Performance Service advertises 69 entity types; the ESA zDOM catalogue
(`docs/assets/zdom-metrics-catalogue.csv`, 361 rows) lists 18 sections, and
querying the 11 it has that the schema does not (`zdom-io:*` etc.) returns
live data on the lab ESA cluster (2026-09-25):

| Family | Objects | Metrics | Note |
|---|---|---|---|
| `zdom-io` | 4 | 82 | per host; IOPS/throughput/latency by zDOM stage (bank, durable log, flush, btree) |
| `zdom-overview` | 4 | 50 | per host; bank/flush in-flight, bypass, errors |
| `zdom-seg-cleaning` | 48 | 35 | per disk?; segment-cleaner goodness |
| `zdom-seg-check` | 48 | 19 | per disk?; lookup timing |
| `zdom-btree` | 4 | 16 | logical/middle tree insert/remove |
| `zdom-llp` | 4 | 9 | VAT write-back |
| `zdom-snapshot` | 4 | 9 | snapshot create/delete log sizes |
| `vsan-zdom-gsc` | 7 | 9 | global segment cleaner, capacity goodness |
| `zdom-compression` | 4 | 8 | LZ4 / ZSTD throughput |
| `cluster-zdom-io-cost` | 1 | 1 | `ioCostEMA` |
| `zdom-world-cpu` | 201 | 3 | per world — the per-thread noise already ruled out; skip |

**What in those families is worth collecting** (reviewed 2026-09-25 against
live values; ranked by operator value, not by count):

| Family | Collect | Why |
|---|---|---|
| `zdom-overview` (per host) | `bankFlushError`, `lookupError`, `bypassWritePercent`, `bypassWriteFallbackPercent`, `bypassWriteIneligiblePercent`, `numZdomObjects` | the only **error counters** in the zDOM path. `lookupError` reads a constant 20 on one lab host (cumulative, from boot) — a read-path lookup failing is a grey-state signal. Bypass-write is the 9.0 fast path; its fallback rate says whether hosts are getting it |
| `vsan-zdom-gsc` (per capacity disk, 7 objects) | `physDiskFullnessPctCapacity`, `rawDiskFullnessPctCapacity`, `reactiveCleaningRateCapacity`, `proactiveCleaningRateCapacity`, `currentWriteRateCapacity` | **per-disk fullness** and whether the segment cleaner is running *reactively* — the ESA equivalent of "disk full and the cleaner is behind". Nothing else in the pack gives fullness per disk |
| `zdom-io` (per host) | `latencyAvgDurableLog` / `latencyMaxDurableLog` (write commit path), `latencyAvgBankFlushFSW` / max, `latencyAvgLookup` / max (read path), `iops`, `oioDLog`, `oioBankWriter`, `oioLookupDOM` | splits a slow write into log-commit vs bank-flush and a slow read into lookup vs backend; the stage latencies a rapid dashboard needs to say *where* in the host the time goes |
| `zdom-compression` (per host) | all 8 | `CompressTput` ÷ `CompressedTput` is the **compression ratio** per host (lab ZSTD: 3.2 MB/s in, 0.77 MB/s out, 4.1×). Also proves compression is actually active |
| `cluster-zdom-top-stats` | `ioCount`, `readCount`, `writeCount`, `unmapCount` (catalogue-only, verify live) | complete the family already collected |
| `zdom-vtx` | `rateBankFlushCacheMiss`, `rateLookUpCacheMiss`, `ratePrefetchCacheMiss`, `rateSegCleaningCtxDataCacheMiss` (catalogue-only, verify live) | cache-miss rate by transaction type; misses on the lookup path are read latency |
| `cluster-zdom-io-cost` | `ioCostEMA` | one number, reads 0 in the lab; unknown semantics, cheap to keep |
| **Skip** | `zdom-world-cpu` (201 per-world objects), `zdom-btree`, `zdom-snapshot`, `zdom-llp`, `zdom-seg-check` (48), `zdom-seg-cleaning` (48) | engineering counters with no operator action; the two 48-object families are per-disk-per-something and would add ~100 objects per host for cleaner internals. `numSegsFreed` / `latAvgPassRuntime` are the only two worth reconsidering |

**The catalogue's unit column, checked against live values.** It is inferred
from naming (`ends in Pct`, `starts with iops`), and two of its rules are wrong
for this service:

| Catalogue says | Live says | Evidence |
|---|---|---|
| `latencyAvg*` / `latencyStddev*` / `latAvg*` are **milliseconds** (69 rows) | **microseconds** | `cluster-zdom-top-stats.latencyAvgRead` 593 beside `readLatencyMaxUs` 565,482; `cluster-domclient.latencyAvgRead` 808; `zdom-io.latencyAvgBankWrite` 13–46 with max 6,938. Same conclusion as the `time_ms` adjudication in *Unit conflicts* below |
| `tput*` / throughput "likely KB/s" (41 rows) | **bytes/s** | `currentWriteRateCapacity` 664,576 on an idle lab disk is 650 KB/s, not 650 MB/s; `ZSTD_CompressTput` 3,197,256 is 3 MB/s |
| `bypassWriteFallbackPercent` percent | not a bounded percent | reads 285 on one host; a ratio of fallbacks to attempts can exceed 100 only if the denominator is something else. Unknown until documented |
| `missesPerIO` count/sec | count per IO (ratio) | the name; a per-IO figure is not a rate |
| `checkpointWorkerWakeupMs` (ours: µs) | **ms** — fixed | constant 20000: a 20 s wakeup |
| `iopsCacheMissRate` / `tputCacheMissRate` (ours: IOPS / rate) | **percent** — fixed | official name "Cache Miss Per IOPS" and schema unit `percentage` agree it is a ratio |

Where it is right and we were empty: `oio*`, `*Count`, `num*` → count;
`rate*` → per second; `*Us` / `*USec` → microseconds (three were missing —
fixed by the camel-case suffix rule); `*Pct` → percent; `avgGoodness*` → a
score. Those fills are the same rules already proposed for the 182
undocumented metrics, so the catalogue corroborates rather than changes them.
The Confluence descriptions (115 rows) are the durable value and should feed
`docs/METRICS-GUIDE.md` when these families are modelled.

240 metrics excluding world-cpu. Identity (entityRefId shape) is not yet
captured; `tools/model_from_perfsvc.py` only walks advertised types, so it
needs an explicit extra list. The catalogue carries the Confluence
descriptions for 115 of them — the rest are name-decomposition. **Its unit
column is inferred from naming conventions** (the "Unit Inference Basis"
column says so: `name starts with 'iops'`, `ends in 'Pct'`), so it corroborates
the same rules held for the 182 undocumented metrics but is not an authority.

**No relationship to the vCenter adapter's `HostSystem`.** Without it these
objects are an island nobody can navigate to from the rest of Operations. See
the TODO in `collect()`.

**No `content/`.** Metrics with no symptoms attached are just storage. The
Broadcom thresholds are staged in `constants.py` ready to become symptom
definitions. Note this is a schema change, so it needs a full pak reinstall.

**One host only.** Beta scope was `esxi01.example.com`. Now that tokens are known
to be cluster-wide, the `hosts` parameter should be exercised against the whole
cluster.

## Scale

**Per-family collection toggles.** 494 objects per host: at 100 hosts that is
~49,400 objects, at 500 hosts ~247,000. Five families are 89% of the count --
`vmware_esx_world` alone is 267 objects per host of per-process detail that
churns as worlds come and go, plus `host_cpu` (65), `slab` (62) and the two
heap families (31 each). Everything else totals 38 objects per host.

A site running this fleet-wide probably wants the network and vSAN families
everywhere and per-world detail only where something is being investigated.
That argues for per-family enable/disable in the adapter instance config, with
dashboards degrading gracefully when a family is off.

**Object churn from `vmware_esx_world`.** Worlds are processes: they appear and
vanish between collections, so Operations will see constant object creation and
deletion. Worth measuring what that does to the analytics cluster before this
goes to many sites.

## Housekeeping

- Delete the duplicate Harbor artifact `sha256:9d2b6784...` (left over from a
  redundant `--push-registry` retry) and run garbage collection to reclaim the
  blobs.
- Record the workload-network probe NIC (`ens224` / `<workload-net-ip>`), the Harbor
  coordinates, and the Cloud Proxy SSH key in `TAKEOVER.md` §A, so a future
  session does not find an unexplained second NIC, a policy route, a
  `~/harbor.env` and an SSH key with no context.
- Consider turning SSH back off on the Cloud Proxy once validation is done; it
  is disabled by default as deliberate hardening.

## Standby uplinks are invisible, and they are the ones that matter

The pack creates a `VsanPnic` object only for NICs the Performance Service
reports, and it reports only NICs carrying vSAN traffic. A standby or unused
uplink produces no data, so no object exists, so nothing monitors it.

Measured on the lab cluster 2026-09-29:

| Host | Physical vmnics | On the vSAN DVS | Collected |
|---|---|---|---|
| esxi01 | vmnic0-3 | vmnic0, **vmnic1**, vmnic2 | vmnic0, vmnic2 |
| esxi03 | vmnic0-3 | vmnic0, **vmnic1**, vmnic2 | vmnic0, vmnic2 |
| esxi04 | vmnic0-3 | vmnic0, **vmnic1**, vmnic2 | vmnic0, vmnic2 |
| esxi02 | vmnic2-3 | vmnic2 | vmnic2 |

`vmnic1` is attached to the vSAN DVS on three of four hosts and is not
monitored. (`vmnic3` is correctly excluded -- it is not on that DVS.)

**Why this matters more here than it would elsewhere.** The Physical Network
screen exists to catch a failing NIC before it causes an outage. The standby
uplink is precisely the NIC that will be relied on during a failover and
precisely the one nobody has looked at. A green screen today means *every
active NIC is fine*, which is not the same claim and will be read as the
stronger one.

**Options, none free:**

1. **Say so on the screen.** Cheapest, and needed regardless: the text panel
   should state that only vSAN-carrying uplinks appear, so an absent NIC is
   not a healthy one. Belongs in `content/DASHBOARD-MOCKUPS.md`.
2. **Create objects for DVS-attached uplinks with no perfsvc data**, from the
   vCenter side, so the operator can at least see the NIC exists and is
   unmonitored rather than being silently absent. Objects with no metrics are
   their own kind of clutter, so this wants thought.
3. **Surface the count instead** -- a supermetric comparing uplinks attached
   to the vSAN DVS against `VsanPnic` objects present, alerting when they
   diverge. Answers "is something unmonitored" without inventing empty objects.

Needs confirming on a cluster where the standby uplink is known-good, to be
sure the absence is teaming policy rather than a collection fault. The
distinction matters: if perfsvc omits a NIC that *is* carrying traffic, that
is a defect rather than a design limit.

## Pause frames are undirected, and the direction is the diagnosis

The Performance Service offers `pauseCount` ("pNic 802.3x Pause Rate"), its
`Raw` and `Actual` twins, and the same three for `pfcCount`. **None carries a
direction.** Confirmed against the full advertised schema, not merely what is
modelled: there is no `pauseRx`/`pauseTx` anywhere in it, and the dormant
host-scrape model has nothing either.

The two directions mean opposite things:

| Direction | Meaning | Who fixes it |
|---|---|---|
| Pause **sent** by the host | our receive path cannot keep up | us -- ring buffers, interrupt coalescing |
| Pause **received** from the switch | the fabric is congested | the network team |

A combined counter cannot separate "this host is drowning" from "the switch is
overloaded", which is precisely the call the Physical Network screen exists to
make. It also leaves `pauseCount` unable to corroborate a finding like the
`rxMissErr` burst on esxi03 vmnic2: pause frames *sent* would confirm the host
was overwhelmed, pause frames *received* would point elsewhere entirely.

Available below both collection paths, at the driver:

    vsish -e get /net/pNics/vmnic2/stats     # rx_pause / tx_pause on some drivers
    esxcli network nic stats get -n vmnic2
    esxcli network nic get -n vmnic2         # whether flow control is enabled at all

Needs an ESXi credential, the same blocker as the ring-buffer size check, and
worth doing on the same host. Note the third command first: if flow control is
disabled on the uplink, `pauseCount` reading zero says nothing at all, and the
screen should not imply otherwise.

## Open question: halfopen drop rate reads 7-9% on a healthy cluster

`tcpHalfopenDropRate` (`VsanTcpIp`) is the only non-zero error signal in the
entire TCP family on the lab cluster, and it is not small. Sampled 2026-09-29
across 45 minutes:

| Host | Rate after per-mille conversion |
|---|---|
| ...db86 | 8.8% |
| ...db5d | 8.8% |
| ...db54 | 9.4% |
| ...db57 | 7.1% |

Every other TCP metric on those hosts reads 0 -- `tcpErrs`, `tcpRxErrRate`,
`tcpTxRexmitRate`, all three SACK rates, `tcpSndZeroWin`,
`tcpTimeoutDropRate` -- against 983 RX / 1,160 TX packets and 1,427 IP total
per sample.

**What it measures:** connections dropped in `SYN_RCVD` -- a SYN arrived, the
reply went out, the handshake never completed, the entry was evicted.

**Why it is not yet actionable.** The denominator is undocumented; the
official description is circular ("half open drop rate") and the schema says
only `permille`. If the base is connection *attempts*, and RDT holds
persistent connections so attempts are rare, a handful of drops yields a large
percentage from a tiny base. This is the perspective problem already noted for
error counters, except here the denominator is not merely absent from the
dashboard but unknown entirely.

**Reasons to suspect benign:** the rate is stable over time and near-identical
across all four hosts. Genuine handshake trouble is usually lumpy and
host-specific; a flat uniform rate on a healthy cluster reads more like
routine background churn.

**To settle it:** `esxcli network ip connection list`, or the absolute
counters from `vsish`, would give drops *and* attempts on one host and convert
the percentage into a real number. Worth doing once. If it is normal it should
be excluded from the network screen, since a permanently amber tile trains
operators to ignore the panel; if it is not, it is the most interesting signal
in the TCP family and belongs on the Physical Network screen.

Needs an ESXi credential, which is also blocking the `vsish` ring-buffer test.

## Two low-value families dominate the object count

`VsanDomWorld` (78.8 objects per host) and `VsanHostCpu` (61.0 per host, **one
per CPU thread**) are **87% of everything the pack creates per host** -- 140 of
161. Neither appears in any screen in `content/DASHBOARD-STORYBOARD.md`, and
`VsanHostCpu` carries three metrics of generic per-thread CPU that the
built-in vCenter adapter already collects.

Projected from measured per-host rates:

| Hosts | Host-scoped objects | With both families off |
|---|---|---|
| 4 (lab) | 644 | 85 |
| 16 | 2,576 | 340 |
| **32** | **5,152** | **680** |
| 64 | 10,304 | 1,360 |

Plus VM-scoped objects scaling with VM count, and cluster-scoped (7 flat). A
32-host cluster is roughly **6,700 objects from this pack on one cluster**.

**The lab understates it.** `VsanHostCpu` is per CPU thread and the lab hosts
have 61. On production silicon, 32 hosts gives 4,096 objects at 128
threads/host, or 6,144 at 192 -- from that one family.

This is a sizing, storage and collection-load argument: object count drives
Operations' own capacity planning, the analytics tier and the per-cycle
collection cost. **It is not evidence about dashboard behaviour** -- see the
retraction below.

### Retracted: the claim that this caused the widget load failures

An earlier version of this entry argued that depth-2 widgets fail because a
resolve "walks 658 objects", and that cutting these families would fix it.
**That was inference presented as mechanism and should not be relied on.**

The 658 figure came from walking `CHILD` through the API one node at a time --
that is how *this repository* measured the graph, not how Operations resolves a
widget. Operations holds an indexed inventory; "descendants of X of kind Y" is
a bounded query against a relationship table, not an enumeration of everything
beneath the cluster. A widget asking for four metrics on `VsanPnic` has no
reason to touch a `VsanDomWorld` object.

What survives is the observation, not the explanation: **depth-1 widgets have
never failed and depth-2 widgets fail intermittently.** Hop count is a more
plausible variable than object count, since a two-hop join costs more than a
one-hop one irrespective of how many rows sit at either end. The cause remains
unknown and is with Broadcom -- see `docs/WIDGET-LOAD-BEHAVIOUR.md`.

Turning these families off is still worth doing. It is worth doing for the
object counts above, which stand on their own.

## Relationships: the VM tier is a third orphaned

**64 of 848 objects have no parent, and every one of them belongs to a
vSphere Pod VM.** Measured against the live instance 2026-09-28.

| Our kind | Objects | Parented | Orphaned | Parent when it works |
|---|---|---|---|---|
| `VsanVirtualMachine` | 30 | 20 | **10** | `VMWARE/VirtualMachine` |
| `VsanVirtualDisk` | 60 | 33 | **27** | `VMWARE/VirtualMachine` |
| `VsanVscsi` | 106 | 79 | **27** | `VMWARE/VirtualMachine` |

Everything else is correctly attached: the six cluster-scoped kinds to
`ClusterComputeResource` at depth 1, and all 21 host-scoped kinds -- including
`VsanPnic` -- to `HostSystem` at depth 2. Confirmed by walking CHILD from the
cluster: depth 1 yields 7 of our kinds, depth 2 yields 21, depth 3 the VM tier.

### Cause: the join target does not exist in Operations

Not our bug, but ours to work around. The chain:

| Where | What it holds |
|---|---|
| vCenter | **35** `vim.VirtualMachine` objects, including all 10 pod VMs, each with a valid `uuid`, `instanceUuid` and MoRef (`vm-8043`, ...) |
| vSAN Performance Service | reports all 30 VMs it has storage for, pod VMs included |
| **Operations' VMWARE adapter** | **28** `VirtualMachine` objects -- **the 10 pod VMs are absent** |

`build_parent_map` resolves those MoRefs correctly; the relationship then
points at a `VMWARE/VirtualMachine` object that Operations never created, and
fails silently. The pod VMs (`harbor-*`, `cci-ns-controller-manager-*`,
`metrics-aggregator-*`) are Supervisor-managed and the vCenter adapter does
not model them as virtual machines.

### Consequences

- A cluster-scoped selector reaches **20 of 30** vSAN VM objects and **79 of
  106** vSCSI objects. `content/DASHBOARD-MOCKUPS.md` screen 7 silently shows
  two thirds of the estate, with no indication the rest exist.
- Orphans roll up nowhere -- no contribution to cluster or host health, and
  invisible to anything scoped by relationship.
- This will be **worse on customer sites running Supervisor/TKG at scale**,
  where pod VMs can outnumber conventional ones.

### Fix: attach VM-scoped objects to the host as well

`vm.runtime.host` is already readable in the same container view -- the pod
VMs above all return `host-12` -- and Operations *does* hold every
`HostSystem`. Operations supports multiple parents (a lab HostSystem has 3),
so record `vm_moid -> host_moid` in `build_parent_map` and attach VM-scoped
objects to both the VirtualMachine and the HostSystem.

Where the VM object exists, the VM relationship stays and the host becomes a
second path. Where it does not, the host relationship still lands, so the
object is reachable at depth 2 and rolls up. No object is orphaned either way.

Worth a guard test asserting no collected object ships without at least one
parent, since this failed silently for as long as it has.

## Container CVEs: what is fixable here and what is not

### Resolved in 1.3.1 -- unused packages purged

Eight OS packages with **zero installed reverse-dependencies** are purged at
build time. Each was verified individually: the adapter imports and the swagger
server starts without it.

| Removed | Findings | Why it was there |
|---|---|---|
| `perl-base` | 19 (3 critical) | Debian Essential; only consumers are dpkg and debconf helper scripts |
| `libsqlite3-0` | 9 (1 critical) | backs Python's `sqlite3` stdlib module, which nothing here imports |
| `mount`, `bsdutils` | 22 (10 crit/high) | util-linux binaries a container never calls |
| `libncursesw6`, `ncurses-bin`, `ncurses-base`, `login` | 12 | terminal and login tooling |

Measured effect: **268 findings -> 225, criticals 2 -> 1, 119 unique CVEs ->
110.** Every finding removed was unfixable upstream, so they were otherwise
permanent.

**The trade, recorded so it is not rediscovered as a bug:** apt and dpkg stop
being reliable inside a running container, `import sqlite3` raises ImportError,
and there is no mount, login or curses tooling. Nothing shipped uses any of it.

**Deliberately kept:** the remaining util-linux siblings have real dependents,
and their 30 findings are 5 unique CVEs counted six times because one source
ships six binaries. `zlib1g` cannot go -- Python links it -- and its
CVE-2023-45853 is `will_not_fix`, which is the one critical that remains.

### Verified: the purge does not break collection

Purging eight packages was previously justified only by "the adapter imports
and the swagger server starts". That proves the image boots, not that it
works. It now has the stronger proof, measured 2026-10-01 against the live
3-host ESA cluster through the adapter's own HTTP endpoints -- the same ones
Operations calls:

| Endpoint | Result |
|---|---|
| `POST /test` | 200, no errors, 13.0 s |
| `POST /collect` | 200, no errors, 18.7 s |

739 objects, 5,203 metric values, 1,510 properties, 34 resource kinds, real
values on every sampled object. Identical counts from `isdk_vsanhostmetrics-test:1.3.1`
and from a direct `perfsvc` call in the same image, so nothing is being
swallowed between the collector and the server.

`import sqlite3` raising `ImportError` is confirmed harmless: every module in
`app/` and every `aria.ops.*` module the adapter touches imports cleanly, and
so does `swagger_server`, the container's actual entrypoint.

**Retraction.** The earlier claim that installing the pak was "the only true
manner to test" was wrong about the image half of the risk. `mp-test` is
interactive and hangs with stdin closed, which is what made this look
untestable, but the server it drives has a plain HTTP API. `tools/probe_adapter.py`
posts to it headless and exits non-zero on an empty or failed collection. Run
it before cutting any release that changes the base image or the package set.

What installing the pak *does* uniquely test is the **content import**:
whether the pak path preserves `viewDefinitionId`, `selfProvider` and the
provider's pinned `resource` on view widgets, where UI dashboard import strips
all three. That one genuinely cannot be answered without installing.

### Still not fixable here



The build now applies Debian security updates on top of the SDK's base image
(`Dockerfile`, `USER 0` / `apt-get upgrade` / `USER aria-ops-adapter-user`).
Measured on the base `base-adapter:python-1.2.0` (Debian 12 bookworm,
105 packages) 2026-09-28:

| Package | Base image | After the upgrade layer |
|---|---|---|
| `openssl` | 3.0.20-1~deb12u2 | **3.0.22-1~deb12u1** (security) |
| `libssl3` | 3.0.20-1~deb12u2 | **3.0.22-1~deb12u1** (security) |
| `tzdata` | 2026b-0+deb12u1 | **2026c-0+deb12u1** |

Nothing else was behind, and the rebuilt image reports zero upgradable
packages. Runtime user (uid 1000) and working directory are unchanged; the
adapter imports and `ssl.OPENSSL_VERSION` reports 3.0.22. Cost: ~81 MB of
image size, from apt's replacement copies.

**What this does not fix, and cannot from here:**

- **`perl-base` 5.36.0-7+deb12u3** -- the source of most scanner noise. It is
  Debian **Essential**, so it cannot be removed without breaking dpkg, and it
  is already at the newest version bookworm ships. Findings against it are
  unfixed upstream, not a missing patch. Not actionable in this repository.
- **Python 3.11.12**, pinned by the SDK's base image (3.11.16 exists). Changing
  it means changing `FROM base-adapter:python-1.2.0`, which the SDK generates
  and which Operations expects. Raise with the SDK team rather than forking.
- Python dependencies are current -- `pip list --outdated` is empty.

Re-run the upgrade check whenever a release is cut; the base image drifts
further behind with time, and this layer is the only thing closing the gap.

### Scanned with Harbor's own scanner, 2026-09-28

The Harbor robot account (`robot$vsan-mp+mpbuild`) can push and pull but has
**no Harbor API permissions** -- `/users/current/permissions` returns `[]` and
every project endpoint is `FORBIDDEN` -- so scan results cannot be read
programmatically with it. Reading them needs either a user account with
project read, or the UI. Reproduced locally instead with the same scanner
Harbor runs, **Trivy 0.74.0**:

| Severity | 1.2.3 as deployed | With the upgrade layer |
|---|---|---|
| CRITICAL | 5 | 5 |
| HIGH | 61 | 61 |
| MEDIUM | 105 | 101 |
| LOW | 104 | 96 |
| **Total** | **277** | **264** |

13 findings and 7 distinct CVEs cleared, none introduced.

**Of the 264 remaining, 255 have no published fix** (198 `affected`, 43
`fix_deferred`, 14 `will_not_fix`). All five CRITICALs are in that group:

| Package | CVE | Status |
|---|---|---|
| `perl-base` | CVE-2026-13221, CVE-2026-8376 | affected |
| `perl-base` | CVE-2026-42496 | **fix_deferred** by Debian |
| `libsqlite3-0` | CVE-2025-7458 | affected |
| `zlib1g` | CVE-2023-45853 | **will_not_fix** |

**The 9 that are fixable are all Python, and none are fixable here:**

| Package | Findings | Why not |
|---|---|---|
| `cryptography` 44.0.0 | 4 HIGH, 1 LOW | The SDK lib pins it exactly -- `Requires-Dist: cryptography==44.0.0`. Requesting `>=50.0.0` fails with `ResolutionImpossible`. Clearing all four needs 50.0.0, six major versions on, so forcing it past the pin risks breaking the SDK's own TLS at runtime. **SDK-team item.** |
| `setuptools` 70.3.0 | 1 HIGH, 1 MEDIUM | Not installed -- **vendored inside pip** (`pip/_vendor/vendor.txt`). Trivy reads that manifest. |
| `msgpack` 1.1.2 | 1 HIGH | Same: vendored inside pip. |

The adapter imports and runs without pip, so deleting pip from the final image
would clear those three. Not done: it is a change to the SDK's image for three
findings in code that only executes when pip itself runs, and it would have to
be re-justified on every SDK bump. Worth revisiting if a scan gate blocks a
release on them.

**For a Harbor policy exception**, the defensible line is that 255 of 264
findings have no upstream fix and the remaining 9 are pinned by the vendor's
own SDK or vendored inside pip. Re-scan each release rather than assuming this
holds -- Debian publishes fixes for `fix_deferred` items eventually, and the
apt layer picks them up automatically when it does.

## Object naming

**Fourteen resource kinds are not named `vSAN ...`, and all fourteen carry
data.** Verified against the live Operations instance 2026-09-28
(`/suite-api/api/adapterkinds/VsanHostMetrics/resourcekinds`, 70 kinds
registered). They fall into three groups in the object-type picker:

| Group | Count | Examples |
|---|---|---|
| No `vSAN` prefix at all | 10 | `Cluster Domclient`, `Cluster Domcompmgr`, `Cluster Domowner`, `Host Domclient`, `Host Domcompmgr`, `Host Domowner`, `Cmmds Net`, `Zdom Vtx`, `Host Vsansparse`, `Host Zdom Top Stats` |
| `Vsan` instead of `vSAN` | 4 | `Vsan Cluster Capacity`, `Vsan Esa Disk Layer`, `Vsan Esa Disk Scsifw`, `Vsan Dp Historical Stats` |
| Correct (`vSAN ...`) | 55 | `vSAN Physical NIC`, `vSAN Cluster RDT Latency` |

**Why this matters more than cosmetics.** Someone building a dashboard types
"vSAN" into the object-type picker to find our kinds. These fourteen do not
appear -- they sort into two separate alphabetical blocks, one above every
`vSAN` entry and one below. The affected set is not obscure: it is every DOM
family (client, owner, component manager, at both cluster and host scope),
cluster capacity, and both ESA disk kinds. **Eight of the seventeen object
types used by `content/DASHBOARD-MOCKUPS.md` are in this group.**

The cause is that `label` is derived per entity and the prefix rule was not
applied uniformly -- `build_model_extra.py:label_for()` appends `vSAN ` only
when the text does not already start with "vsan", which lets `Vsan Cluster
Capacity` through unchanged, and the live model's labels were never passed
through that rule at all.

Fix: normalise every label to `vSAN <Title Case>` at generation time, and add
a guard test asserting no label escapes without the prefix. Renaming a
**display name** should be safe -- the resource kind key is what identifies
the object and its history -- but confirm against a populated instance before
shipping it, since dashboards and views referencing a kind by name would need
re-pointing.


**~~`virtual-disk` objects still read as UUIDs.~~** Resolved 2026-09-23. All
60 now name themselves, e.g. `harbor-core-56d4957445-hp8cc [Hard disk 2]`.

Worth recording how, because the obvious route is a trap. These are CNS
volumes and an FCD's filename genuinely is a UUID, so the apparent answer is
`vStorageObjectManager.ListVStorageObject` -> `RetrieveVStorageObject` ->
`config.name`. That returns **NoPermission** for a read-only account, and
granting the privilege would raise this pack's requirement above read-only for
what is purely a cosmetic gain -- the wrong trade for a monitoring tool.

The route taken instead costs nothing: a `virtual-disk` ref is the datastore
path with the `[datastore] ` prefix stripped, and the attached VM's
`backing.fileName` is the same path. The VM walk already happening for VM names
resolves them, using access the pack already has. Name map went 83 -> 197
entries and 0.8s -> 1.1s.

One wrinkle: perfsvc emits the path both with and without a leading slash --
59 of 60 came back bare and one as `/<uuid>/name.vmdk`. Both forms are
registered rather than guessing.

**Unit coverage is 40%** (294 of 730). The resolved ones come from HCIBench's
dashboards plus conservative name heuristics; the remainder are either
genuinely dimensionless counts or unknown, and are deliberately left unitless.
A wrong unit is worse than none, because Operations will scale and render it
confidently. Improving this means finding a second authority, not loosening
the heuristics.

## Open question — retransmits and DOM world stalls

Hypothesis worth testing when a cluster is under real load: **do network
retransmits stall a DOM world while the stream is rebuilt?**

The data to test it is already collected. `dom-world-cpu` carries `readyPct`
per world -- ready to run, waiting for a scheduler slot -- and
`vsan-tcpip-stats` carries `tcpTxRexmitRate`. If the mechanism is real, the two
should rise together on the same host, and specific worlds should show it
rather than all of them.

Competing explanation to rule out: the stall may be RDT-level rather than CPU.
`txSbSpaceMin` reaching zero and `kaReset` incrementing would indicate the
transport is blocked without any world being CPU-starved. Those are different
remedies -- more CPU versus more socket buffer or a network fix -- so
distinguishing them matters.

**Unverified.** The lab is too idle to produce either signal. Needs a cluster
doing real work, ideally one with a known-marginal link.

## Known metric gaps

**No NIC ring buffer utilization.** Searched all 730 modeled metrics: zero
matches for ring/descriptor/buffer/watermark/occupancy. The Performance
Service exposes the *consequence* of the RX ring filling -- `rxMissErr`,
`rxOvErr`, `rxFifoErr` -- but not its depth, so there is no early warning,
only loss after the fact.

This is probably not routable around. ESXi exposes configured ring *size* via
`esxcli network nic ring current get -n vmnicX`, which is static config rather
than a series, and instantaneous occupancy does not appear to be exported at
all. Collecting it would also mean standing up a second gathering point for
NIC data that `vsan-pnic-net` already owns, which the collection rule forbids
(see docs/COLLECTION-DESIGN.md). If it is ever wanted, the right shape is a
config *property* on the existing pnic object, not a parallel collector.

Practical substitute for "is this link bad": `rxMissErr` rate over `rxPackets`
as a loss ratio, alongside `pauseCount`/`pfcCount` to separate a congested
fabric from a failing NIC.

**`rxMissErr` semantics are conventional, not documented.** The label reads
"RX missed errors (ring buffer full)", following the standard
`rx_missed_errors` driver convention. ESXi passes this through from the driver
and the precise meaning varies by vendor. It is the best available signal, but
it is an interpretation -- worth confirming against a driver that documents it
before an alert definition depends on the exact wording.

## Unit conflicts between the two authorities

The Performance Service schema carries a `unit` (`time_ms`, `rate_bytes`,
`permille`, `number`, ...). It disagrees with our HCIBench-derived units on
**34 of the 60 metrics where both have an opinion**. Checked against live
values 2026-09-23, and the schema is wrong in the cases that could be
adjudicated:

| Metric | Ours | Schema | Observed | Verdict |
|---|---|---|---|---|
| `latencyAvgRead` | microseconds | `time_ms` | 589 | ours -- 589 ms on an idle NVMe cluster is absurd; 0.59 ms is right |
| `rxSbSpaceMin` | bytes | `rate_bytes` | 8,286,980 | ours -- an 8 MB socket buffer, not 8 MB/s. The official *name* says "Bytes" and contradicts its own graph unit |
| `portRxDrops` | none | `permille` | 0,0,1,1 | schema doubtful -- small integers read as counts |

The cause is structural: **`unit` hangs off the graph, not the metric**, and a
graph mixes metric kinds. So it describes an axis, not a series, and bulk
applying it would have introduced a 1000x error across 20+ latency metrics.

But it is not uniformly wrong, which is why this is a backlog item and not a
closed question. `pauseCount` is officially "pNic 802.3x Pause Rate", described
as *"Percentage of Physical NIC 802.3x Pause Rate"* -- so the id says count,
the metric is a rate, and the schema's `permille` is probably right. Every
value observed was 0, so it could not be settled by measurement.

Resolving this properly means adjudicating per metric against non-zero observed
values, preferring the official *description* over the graph unit. Worth doing
before any alert definition depends on a threshold.

## Counter vs rate, and the per-mille problem

Two related questions settled by measurement 2026-09-23, and one left open
because it needs a decision rather than more data.

### `*Raw` is the only cumulative family

Classified 194 (entity, metric) series over an hour, 13 samples each, asking
which are monotonic non-decreasing *and* rising. Exactly three qualify, all
`*Raw`:

```
rxPktRaw        347,383,079 -> 351,537,162     strictly rising
txPktRaw        296,590,389 -> 300,723,244     strictly rising
pauseCountRaw           222 -> 224             steps, never falls
```

Everything else is per-interval. `portRxDrops` in particular is **not** a
counter -- one vmnic read `1,1,0,0,0,1,0,0,0,1,0,1`, which falls. It is
officially "Inbound Packet Drop Rate of vSwitch Port", described as a
percentage, so non-monotonic is exactly right.

Consequence: the `*Raw` metrics are cumulative since driver load and are
currently defined as plain gauges, so a dashboard plots an ever-rising line.
They need either a rate derivation or an explicit note. The rest of the model's
"everything is a gauge" assumption is confirmed correct.

Note also: **wildcard queries are capped at one hour.** A longer range raises
`com.vmware.vsan.perfsvc.fault.queryperf.wildcardqueryrange`. Collection uses a
15-minute window so it is unaffected, but any backfill or analysis tooling has
to page.

### Ratios are per-mille and the SDK has no unit for it

Confirmed independently, twice:

- `tcpRcvdupackRate` read 1-2 from perfsvc where the host `/vsanmetrics` scrape
  measured 0.122% for the same thing -- recorded in `app/constants.py`.
- The schema's graph unit says `permille` for these metrics, while their
  official *descriptions* say "Percentage of ...". The descriptions are loose;
  the values agree with per-mille.

**`aria.ops.definition.units.Units.RATIO` has only `PERCENT`.** There is no
per-mille unit, so there are three options and all have a cost:

1. Leave unitless -- a value of 1 means 0.1% and nothing says so. Current
   behavior.
2. Declare `RATIO.PERCENT` -- wrong by 10x, and Operations renders it
   confidently. Worst option.
3. Divide by 10 at collection and declare `RATIO.PERCENT` -- correct and
   unambiguous, but the adapter then reports a different number than the
   Performance Service does, which will confuse anyone cross-checking against
   the vSphere UI.

Option 3 is probably right, but it changes emitted values and directly affects
any threshold written against these metrics, so it is a deliberate decision
rather than a cleanup. `THRESHOLDS` in `app/constants.py` already carries the
"divide by 10" caveat and would be simplified by it.

Affected metrics are those whose official description begins "Percentage of"
-- `portRxDrops`, `portTxDrops`, `pauseCount`, `rxPacketsLossRate`,
`txPacketsLossRate`, `tcpRcvdupackRate` and the other `*Rate` ratios.

## Dashboard refinement, 2026-10-01

Full analysis in `content/DASHBOARD-REFINEMENT.md`. Summary of what changed and
what was learned.

### Confirmed: pak content import preserves view widget bindings

The last open question about the delivery path, and it is now answered by
installing. Importing a dashboard through the Operations **UI** strips
`viewDefinitionId`, `selfProvider` and the provider's pinned resource; the
**pak content path does not**. The 1.3.1 install populated with no manual
re-wiring. The manual-import fallback bundle shipped with 1.3.1 is therefore
insurance rather than a likely path.

### Two portability defects in the cloned dashboard template

Both were instance- or session-specific state copied verbatim from the export.

**The provider's pinned root carried a browser-session handle.**

```json
{"resourceId": "resource:id:0_::_", "resourceName": "VCF World",
 "resourceKindId": "002010VcfAdapterVCFWorld",
 "id": "Ext.vcops.chrome.model.Resource-592"}
```

`id` is an ExtJS client-side model reference: it names a JavaScript object
inside one page load. Stripped at build time. The rest is kept, and the
document's top-level `entries` table shows why that is safe -- it resolves
`resource:id:0_::_` by **kind key** (`VCFWorld` / `VcfAdapter`) with no
instance identifier anywhere, so the pin is portable.

**Every widget's `states` blob was keyed to the wrong widget.** The key is
`permTableView_widget_<tabId>_<widgetId>`, and cloning copied it verbatim, so
it named a dashboard and a widget absent from the output. Operations found no
saved state for the widget it was drawing and fell back to defaults, which is
why a cloned selector showed a column the hand-built original had hidden. Now
rewritten to the generated identities; 441 references verified self-consistent.

### mp-build cannot be run from a script without a pty

It draws progress spinners, so it probes the terminal and **blocks when stdin
is not one**, printing only `Warning: Input is not a terminal (fd=0).` Two
builds were lost to this, one after fifteen minutes, with an empty log both
times because the output was also sitting in a pipe buffer.
`tools/mp_build_pty.py` allocates a pty, strips the escape sequences and
returns the child's exit status.

### Still open, carried forward

- **`VsanDomWorld` is 243 of 739 objects and every one of its three metrics is
  always zero.** `VsanHostVsansparse` is 21 metrics, all zero.
  `VsanVirtualDisk` is 60 objects for one useful metric. A per-family toggle
  would cut the collection by about a third at no loss of signal. The toggle
  was already on this list; the measurement is new.
- **`VsanCpu` populates `maxRunPct` and `maxUsedPct` and leaves `avgRunPct`,
  `avgUsedPct`, `readyPct`, `runPct`, `usedPct` at zero.** Five of seven fields
  never move. Either upstream does not fill them or this pack reads them
  wrong, and that has not been determined.
- **zDOM maximum latency reads in whole seconds** -- 9.7 s read, 2.7 s write.
  Not credible as an interval maximum; very likely a since-boot high-water
  mark the Performance Service does not document as such. The help text says
  so and points at the averages.
- **Shared cluster scope across the Rapid dashboards** needs the
  `dashboardNavigations` block, which is empty in the only working export
  available to clone. One hand-built example exported from the UI would be
  enough to generate it for all seven. Until then each dashboard has its own
  selector with `selectFirstRow` enabled, which auto-populates on a
  single-cluster instance.

## CVE ownership: who can actually fix what

Asked during review: of the remaining findings, which are Broadcom's to fix?
Attributed from the image rather than from the scan report, because the scanner
names a package without saying who chose its version.

### Broadcom's, and only Broadcom's

| What | Evidence | Cost of them not fixing it |
|---|---|---|
| **Python 3.11.12** | `FROM python:3.11.12-slim-bookworm`, hard-coded in the SDK's own `images/base-python-adapter/Dockerfile` | **3.11.16 is published** -- four patch releases on. Any CPython fix after May 2025 is unreachable from here. Changing the `FROM` means forking the image the SDK generates and Operations expects. |
| **`cryptography==44.0.0`** | an **exact** pin in `vmware-aria-operations-integration-sdk-lib` 1.1.0 metadata, not a floor | 4 HIGH, 1 LOW. Clearing all four needs 50.0.0. Requesting it gives `ResolutionImpossible`, because this is `==` and not `>=`. |
| **`aenum==3.1.11`** | the same exact pin | currently clean; the same trap whenever it is not. |
| **Debian 12 bookworm as the base** | their choice of `python:3.11-slim-bookworm` | the ~225 remaining OS findings are bookworm's. Moving to trixie would clear a large share of them and is a base-image decision only they can take. |
| **`pip` present in the runtime image** | shipped by their base layer | pip *vendors* its own dependency copies and the scanner reads that manifest: `setuptools==70.3.0`, `msgpack==1.1.2`, `urllib3==2.7.0`. The adapter never calls pip at run time. |

### Debian's, which nobody downstream can fix

255 of 264 findings have no published fix -- 198 `affected`, 43 `fix_deferred`,
14 `will_not_fix`. `zlib1g` CVE-2023-45853 is the clearest case: Debian have
marked it will-not-fix, and Python links zlib so it cannot be removed. These
are not a missing patch anywhere; they are a package at the newest version its
distribution ships.

### Ours

**Nothing we pin is vulnerable.** `adapter_requirements.txt` declares two
things, `vmware-aria-operations-integration-sdk-lib~=1.1.0` and `pyvmomi~=8.0`,
and neither carries a finding. Everything flagged arrives through Broadcom's
pin or Debian's base.

What is ours is the mitigation, and both are already in place: the apt upgrade
layer, which carries openssl and libssl3 to 3.0.22, and the purge of eight
zero-dependency packages.

**One thing we could still take from the list above:** deleting `pip` from the
final image would clear the three vendored findings, and the adapter imports
and collects without it. Not done, because it is a change to the vendor's image
layer for three findings in code that only runs when pip itself runs, and it
would need re-justifying on every SDK bump.

### Two corrections to what this file said before

- **`urllib3` is not ours to fix.** It was listed here as "2.7.0 -> 2.8.0, the
  only possibly-fixable finding in our control". Wrong on both counts. The
  *installed* urllib3 is **already 2.8.0** -- the upgrade layer took it. The
  2.7.0 the scanner reports is the copy **vendored inside pip**, which is
  Broadcom's image layer, not our dependency.
- **`setuptools` installed is 84.0.0**, not 70.3.0. The 70.3.0 finding is also
  pip's vendored copy.

## Further removal candidates, tested 2026-10-01

Asked during review: besides pip, what else is worth removing? Tested rather
than reasoned about. Two variants were built on top of the real 1.4.0 image and
each was put through `tools/probe_adapter.py` against the live cluster.

**Both variants collected identically to the unmodified image: 739 objects,
5,203 metric values, 1,510 properties, 34 resource kinds, `/test` and
`/collect` both 200.**

### Variant A -- recommended

| Removed | Why it is safe |
|---|---|
| `pip`, `setuptools`, `wheel` | Nothing shipped imports them. Verified by grep for `pkg_resources`, `import setuptools` and `import pip` across `app/`, `swagger_server/` and `aria/`: the only hits are inside pip itself. `commands.cfg` invokes `/usr/local/bin/python app/adapter.py` directly. |
| `apt`, `gpgv` | Package management. `apt` is already unreliable here after the 1.3.1 purge, and `gpgv` exists only to verify apt's signatures. |
| `e2fsprogs` | Filesystem repair tools in a container that mounts nothing. |
| `libgdbm6` | Backs Python's `dbm.gnu`, which nothing imports. |
| `libnsl2` | NIS client library. |
| `libreadline8` | Line editing for an interactive interpreter that never runs. |

**The pip removal is the valuable one, and not for its own findings.** pip
*vendors* copies of its dependencies and the scanner reads that manifest rather
than what is installed. Removing pip deletes `pip/_vendor/vendor.txt` and with
it **18 packages** from the scan surface, including every one of the three
"fixable but not by us" findings recorded above: `setuptools==70.3.0`,
`msgpack==1.1.2` and `urllib3==2.7.0`.

### Variant B -- tested, collects, not recommended yet

Adds `mawk` and `util-linux`. Both are orphaned and the collection is clean
without them, but `util-linux` is Debian **Essential** and supplies `setpriv`,
`flock`, `logger` and `su`. Nothing in this pack calls them; whether the
Operations container runtime does on some code path has not been established,
and the payoff is one of the six binaries sharing util-linux's five CVEs. Not
worth that unknown.

### Scan surface, measured

| | 1.4.0 | Variant A | Variant B |
|---|---|---|---|
| OS packages in the dpkg database | 97 | 91 | 89 |
| Python dist-info directories | 4 | 1 | 1 |
| Packages in pip's vendor manifest | 18 | 0 | 0 |
| **Total entries a scanner enumerates** | **119** | **92** | **90** |

### Deliberately kept, though all three are orphaned

- **`ca-certificates`** -- `verify_certs` defaults to true, and QUICKSTART
  documents importing the VMCA root into the container trust store as a
  supported alternative to turning it off. That path needs the bundle and
  `update-ca-certificates`. A passing test here would prove nothing either way,
  because the probe runs with verification off.
- **`tzdata`** -- collection timestamps.
- **`netbase`** -- `/etc/services` and `/etc/protocols`.
- The essential floor (`bash`, `coreutils`, `dash`, `sed`, `grep`, `libc-bin`
  and siblings) shows as orphaned only because nothing declares a dependency on
  what it assumes is always present.

### One implementation note

The test variants are 450 MB against the original's 449 MB: **purging in a
later layer does not shrink the image**, because the files remain in the layers
beneath. Scanner findings still drop, since Trivy reads the flattened
filesystem. To recover the space as well, the purge has to go in the **same
`RUN` as the `pip3 install`** in the main Dockerfile rather than a layer after
it.

Variant A is a one-line addition to that `RUN`. Not applied yet -- it is a
change to how the shipped image is built and should be a deliberate decision
rather than a side effect of answering a question.

## What Debian 13 would remediate -- and a retraction

Measured 2026-10-01 by comparing the 97 packages in the shipped 1.4.0 image
against the trixie archive index. This is a **version comparison, not a CVE
scan**: it says which packages move, not which findings clear.

| | |
|---|---|
| Packages with a newer version in trixie | 86 of 97 |
| Packages absent from trixie | 11 |
| Packages at the same version | 0 |

**The 11 absent ones are not gone, they are renamed** by trixie's 64-bit
`time_t` transition, and every one has a newer version under the new name:

```
libssl3 3.0.22     -> libssl3t64 3.5.7        libgdbm6    -> libgdbm6t64 1.24
libgnutls30 3.7.9  -> libgnutls30t64 3.8.9    libreadline8 -> libreadline8t64 8.2-6
libapt-pkg6.0 2.6  -> libapt-pkg7.0 3.0.3     libext2fs2  -> libext2fs2t64 1.47.2
libunistring2 1.0  -> libunistring5 1.3        libdb5.3   -> libdb5.3t64 5.3.28-9
libtirpc3 1.3.3    -> libtirpc3t64 1.3.6
```

So effectively **97 of 97 packages move**, and openssl goes 3.0.22 to 3.5.7.

### Retraction: the remaining critical does not survive a trixie move

This file has said that `zlib1g` CVE-2023-45853 survives every remediation
because Debian marked it `will_not_fix` and Python links zlib so it cannot be
purged. Both halves are still true and the conclusion was still wrong.

The will-not-fix applies to **bookworm**, which ships zlib **1.2.13**. Trixie
ships **1.3.1**, and the CVE's affected range is zlib through 1.3. The version
bump carries it out of range, so a scanner stops reporting it without Debian
ever backporting anything. **A trixie base clears the last critical.**

### Why the finding count should fall a long way

Of the 264 findings measured before the purge, 255 had no published fix: 198
`affected`, 43 `fix_deferred`, 14 `will_not_fix`. `affected` means the version
bookworm ships sits in the vulnerable range and Debian does not intend to
backport -- which is **exactly the class a version bump clears**, for the same
reason zlib's does. The same largely holds for `fix_deferred`.

An exact number needs a trixie-based image built and scanned. What can be said
without that: the overwhelming majority of the ~225 remaining findings are of
the class that a distribution bump resolves, and the blocker is not whether it
would work but that the base image is Broadcom's to change.

**One caveat against over-selling it.** A new base is not zero findings, it is
a different and smaller set; trixie accumulates its own over time. And trixie's
Python is **3.13.5**, where the SDK pins 3.11, so moving the base is entangled
with an interpreter move that would have to be validated against the SDK
library, pyvmomi and the vendored vSAN bindings. It is not a one-line change
for them in the way the `cryptography` pin is.

## BIOS version: already collected, as a property

**Correction.** I said nothing in Operations carries BIOS version. Wrong. I
searched the 864 HostSystem *statkeys* and then misparsed the properties
response as empty. BIOS version is a **property**, not a metric, which is why a
statkey search missed it.

Present on every `VMWARE`/`HostSystem` object today, no configuration needed:

| Property | Value on esxi03 |
|---|---|
| `hardware|biosVersion` | `P3.30` |
| `hardware|vendor` | `To Be Filled By O.E.M.` |
| `hardware|vendorModel` | `To Be Filled By O.E.M. ROMED4ID-2T` |
| `hardware|confidential|hardwareCompatibility` | `Unsupported` |
| `hardware|serviceTag`, `serialNumberTag` | `To Be Filled By O.E.M.` |
| `sys|build` / `summary|version` | `25714478` / `9.1.1-25714478` |

The O.E.M. placeholders are this lab's whitebox board, not a collection fault;
vendor hardware populates them.

**This is vSAN-independent.** It arrives on the vCenter adapter's HostSystem
object, so it covers every host vCenter manages whether or not it runs vSAN.
There is nothing to configure and no second adapter involved.

### What the vSphere API has that Operations does not surface

`vim.host.BIOSInfo`, reached as `HostSystem.hardware.biosInfo`, carries eight
fields. Operations exposes **one** of them:

```
biosVersion            <- the only one Operations surfaces
releaseDate            <- the one that answers "is this BIOS old"
vendor
majorRelease, minorRelease
firmwareMajorRelease, firmwareMinorRelease
firmwareType           <- BIOS or UEFI
```

So Operations gives the version string without its age. Judging staleness from
a vendor-specific string like `P3.30` is guesswork; `releaseDate` makes it a
date comparison. Getting it means reading `hardware.biosInfo` from the vSphere
API directly, which this pack's existing vCenter connection could already do --
it is one property fetch on objects it already walks.

### The built-in vSAN adapter is not the route, and barely configurable anyway

`VirtualAndPhysicalSANAdapter` reports `adapterKindType: GENERAL` with
`identifiers: []` and no credential kinds, and **zero adapter instances exist**
on this instance. It takes no connection parameters of its own because current
Operations drives vSAN collection from the vCenter adapter instance rather than
a separately credentialed one. It is also the wrong place to look for BIOS: its
firmware surface is the vSAN HCL types (`VsanCompliantFirmware`,
`VsanHclFirmwareFile`, `VsanHclFirmwareUpdateSpec`) which are about storage
controller and drive firmware against the compatibility list, not host BIOS.

### Candidate work

A `vSphere Host BIOS and Hardware` view, cross-adapter on
`VMWARE`/`HostSystem`, using the same mechanism as the two `vSphere ...` views
already shipping. Properties rather than metrics, so the column `isProperty`
flag needs setting -- which no view in this pack does yet, so it is unverified.
Would answer "which hosts are on which BIOS" with no new collection at all.

## The vCenter rename bug is fixed, but its fallback still re-arms it

Raised 2026-10-02 by the memory-tiering session, which had logged host naming
instability on the shared lab as an Operations quirk and then traced it to this
pack.

**The original defect.** `_vc_parent` builds an Object keyed exactly as the
VMWARE adapter keys its own, so Operations matches the existing object instead
of creating a second one. The `name` passed with that key is **authoritative**:
supplying anything other than the object's real vCenter name RENAMES it. An
early version passed the managed object reference, which turned every host in
the shared lab into `host-27` and the cluster into `domain-c9` -- for every
other consumer of that vCenter, not just for us.

Fixed in a124ecd and present in every released version: v1.2.3, v1.3.1 and
v1.4.1 all carry it.

**What is still wrong.** `app/adapter.py:198` reads

```python
name=parents.get("names", {}).get(moid) or moid,
```

so a name-resolution miss falls back to the MoRef and renames the object again.
The fix removed the systematic case and left the intermittent one. On this lab
every name resolves -- 308 of them -- so it never fires, which is exactly why it
would go unnoticed on a slower or larger vCenter where a lookup can fail.

**The correct behaviour is to drop the relationship, not rename the object.**
An object that loses its parent for one cycle is a gap in traversal and is
caught by the no-orphan guard. An object renamed to `host-27` is damage to
someone else's inventory that persists until that adapter corrects it. Return
None when the name is unresolvable.

Worth noting for anyone building a pack that attaches to VMWARE objects: the
identifiers decide WHICH object you match, and the name decides what it is
CALLED. Getting the identifiers right and the name wrong does not create a
duplicate, it overwrites a real one.

## Design gap: every view reports depth and none reports breadth

Surfaced 2026-10-02 by the memory-tiering session reading the practitioner
guide directly. The guide uses "depth" and "breadth" for a problem's severity
and its spread (p90, p114), and the point it makes is one this pack does not
act on:

> A problem that impacts 1-2 VMs requires a different troubleshooting process
> than a problem that impacts all VMs in the cluster. The depth is shown by
> reporting the worst among any VM counter ... If the worst number is good,
> then you do not need to look at the rest.

**Every column in all 30 views is depth.** The transformations are `MAX`,
`CURRENT` and `MIN`. A panel says the worst host write latency is 14.9 ms and
has no way to say whether that is one host or all four. On a three-host lab the
table itself supplies the breadth, because every row fits on screen. At forty
hosts, paginated at fifty, it does not -- and that is exactly where the
operator most needs to know whether to drain one host or stop the rollout.

Depth alone is the right default: a good worst case means stop looking, which
is cheap and conclusive. Breadth is what depth cannot answer when the worst
case is bad.

Candidate without new collection, since the data is already there: a cluster
row carrying "hosts above threshold" counts beside the existing worst-case
columns. That is a super metric or a computed column, neither of which this
pack has ever shipped, so it is real work rather than a layout change. Worth
scoping before adding more views -- adding breadth to the panels that exist
beats adding more depth.

## An invented column key, and how it hid for so long

The cluster selector showed two columns both headed "Name": the built-in
object-name column with the real value, and a second reading `-` forever.

`Configuration|Name` **does not exist**. Not a statkey on
`ClusterComputeResource`, not a property on the object. I took it from the
label the Operations UI shows in its metric picker tree -- *Configuration >
Name* -- and wrote that as the key. The real key is `config|name`, and it is a
**property**, not a metric.

**Why the existing validation missed it.** `tools/build_view.py`'s column check
validates against `perfsvc_model.py`, which only describes **this pack's own**
kinds. The three borrowed `VMWARE` views have no model to check against, so
their columns were never validated at all. All 13 columns on
`vSphere Host Uplinks and Load` have since been confirmed against the live
statkey list and are real; this was the only invented one.

**Follow-on:** validating borrowed columns needs a live Operations API call, so
it cannot sit in the build the way the model check does. It belongs in a
pre-release step. Until that exists, any column added to a `VMWARE`-subject
view should be confirmed by hand against
`/suite-api/api/adapterkinds/VMWARE/resourcekinds/<kind>/statkeys` and the
object's `/properties`.

**First use of `isProperty`.** Operations stores properties and metrics
separately: a property has a current value and no time series, so a column left
marked as a metric queries a time range and finds nothing -- the same mechanism
that killed the host services view. `config|name` is the first column in this
pack declared with `isProperty=true`, and **that flag is unverified**. The
object-name column is deliberately left visible, so if the flag is wrong too,
the selector still shows the cluster name and still works. Worst case is the
behaviour being replaced, not worse.

**The general shape, worth remembering:** a UI picker shows you a *label*, and
a view needs a *key*. They are not the same string, and an invented key fails
silently as an empty column rather than as an error.

## Requested: NVMe drive driver and firmware versions

Asked for 2026-10-02, explicitly for later rather than now. Recording the
feasibility work already done so it is not repeated.

**The data exists and this pack cannot currently reach it.** The Performance
Service returns performance counters only, so nothing in the 1,035 metrics
carries a firmware or driver level.

**Three routes, in order of how much they cost:**

1. **The vSAN HCL API**, which is the purpose-built one. The vSphere type
   registry carries `VsanCompliantFirmware`, `VsanHclFirmwareFile` and
   `VsanHclFirmwareUpdateSpec`, confirmed present in the vendored bindings.
   That is the machinery behind Skyline Health's hardware compatibility check,
   which compares controller and drive firmware against the compatibility list.
   It answers not just "what firmware" but "is it the right firmware", which is
   the question actually worth asking.
2. **`vim.host.HostStorageDeviceInfo`** via the same vCenter connection this
   pack already holds, for per-device model, revision and driver. Cheaper than
   route 1 and gives versions without compliance.
3. **The built-in vSAN adapter**, whose `Vsan2Disk` kind defines 25
   `ScsiSmartStatistics` keys. That is SMART data rather than firmware, so it
   does not answer the question, but the adapter is installed and not
   collecting on this instance -- worth checking what else it exposes before
   building anything.

**Not available where you might look first.** vCenter's `HostSystem` carries
`hardware|biosVersion` as a property, so host BIOS is free, but there is no
equivalent for drives. All 864 host statkeys were searched for firmware,
driver, hcl and version: five matched and none was a drive.

**The shape this would take:** per-device properties rather than metrics, on
the existing `VsanEsaDiskLayer` or `VsanEsaDiskScsifw` objects, which already
exist per drive and already parent correctly. So it is a collection change, not
a modelling one. Wait until `isProperty=true` is confirmed working on the
cluster selector before building property columns for it.

## Host-scoped panels flap because vCenter's own cluster membership flaps

Measured 2026-10-02. Symptom: host-level panels render or fail to render in
alternation every few minutes, all of them together, while cluster-level panels
on the same dashboard never fail. Refreshing sometimes fixes it and sometimes
does not.

**Not this pack.** Sampling the relationship graph every 25 seconds for ten
minutes, our numbers never moved: 706 objects throughout, and 168 children of
a HostSystem throughout, including both ESA disk objects.

**The VMWARE adapter's relationships do move.** The cluster's direct children
oscillate between 12 and 7, and the five that disappear are the **four
HostSystem objects and a ResourcePool**. Measured directly:

```
20:35:53   12 total   HostSystem=4
20:36:33   12 total   HostSystem=4
20:37:13    7 total   HostSystem=0
```

The host's own children move the same way, 184 to 168, losing 7 Pods, 7 VMs
and 2 Datastores.

**Why that produces exactly this symptom.** Our cluster-scoped objects are
*direct* children of `ClusterComputeResource`, so they resolve whatever else is
happening. Our host-scoped objects are reached as
`cluster -> HostSystem -> object`. When `HostSystem` is not a child of the
cluster, that path does not exist and every host-scoped view fails together
with "The view cannot be rendered for the specified Object". When it comes
back, they all work. One hop versus two is the whole explanation.

**Two hypotheses ruled out.** It is not the time range: all 30 views request
7 DAYS, not 5 minutes. It is not the browser: this was observed through the
REST API with no browser involved.

**Possibly related, unconfirmed:** three of the four hosts report
`resourceStatus=NONE` rather than `DATA_RECEIVING`, and `esxi02` returned
`connection_state: NOT_RESPONDING` from vCenter's own REST API earlier the same
day.

### What we could do about it, since we cannot fix vCenter

Give host-scoped objects the **cluster as an additional parent**, alongside the
host. Operations supports multiple parents, and our cluster-scoped objects
already prove a direct cluster link resolves reliably. Every view would then be
one hop from the selected object and immune to the host link disappearing. The
host relationship stays, so an operator still finds the metrics under the host.

Cost: a second relationship per host-scoped object, roughly 60 extra links
here, and a hierarchy that is a graph rather than a tree. Worth it if the
flapping turns out to be normal rather than a fault in this environment --
which is the thing to establish first, because designing around someone else's
intermittent bug is a poor trade if the bug is fixable.

## CRITICAL: this pack strips vCenter's own relationships every collection

Found 2026-10-02 after Nick asked whether the pack was contending with the
default vCenter collection. It is, and worse than contention: **we overwrite
vCenter's object relationships every five minutes.**

### The mechanism

`adapter.py:377` adds the vCenter parent objects into our own result:

```python
for parent in vc_cache.values():
    result.add_object(parent)
```

The SDK serialises relationships **parent-centric**, one entry per object in
the result:

```python
"relationships": [
    {"parent": obj.get_key().get_json(),
     "children": [k.get_json() for k in obj.get_children()]}
    for obj in self.objects.values() ...
]
```

So for each vCenter object we touch we emit a complete `children` list
containing **only our children**. Operations takes that as the authoritative
child set and discards everything else. The SDK's own docstring on
`add_children` confirms the semantics are replace rather than merge: *"We want
to set this even in the case where the list is empty, as the user could be
intentionally calling with no children to remove."*

### The measurement that proves it

Sampling the relationship graph every 25 seconds:

| Object | Normal | After our collection | Difference |
|---|---|---|---|
| Cluster children | 12 | **7** | the 4 HostSystems and a ResourcePool |
| Host children | 184 | **168** | 7 Pods, 7 VMs, 2 Datastores |

7 is exactly our cluster-scoped object count. 168 is exactly our host-scoped
count. We do not damage the sets at random -- we **replace** them with ours.
The VMWARE adapter's next cycle restores its own, and the two adapters
alternate on their five-minute cycles, which is the oscillation observed.

### Consequences beyond our own dashboards

- Hosts vanish from inventory views for other users of the same instance.
- Any view, dashboard or report traversing cluster to host breaks while we hold
  the relationship.
- VMs, pods and datastores detach from their host for the same window.
- This affects **everything on the instance**, not just this pack's content.

Our host-scoped panels failing intermittently is the *least* of it, and is a
symptom of damage we are doing to someone else's data.

### Why `PER_OBJECT` does not save us

`add_parent(p)` is implemented as `p.add_child(self)`, which sets
`p._updated_children = True`. So the vCenter object always counts as updated
and is always emitted, whatever the mode. There is no child-side declaration in
this API: relationships can only be stated from the parent.

### Options, none free

1. **`RelationshipUpdateModes.NONE`.** We emit no relationships. Our objects
   become orphans with no parent, losing the traversal every view depends on
   and the whole "appears under the host you are already looking at" design.
   Safe immediately, costs the integration.
2. **Declare the union.** Query the object's existing children through the
   suite-api client and emit ours *plus* theirs. Preserves the integration but
   is racy by construction -- we would be asserting a set we read a moment ago
   -- and adds an API dependency the adapter does not currently have.
3. **Build our own hierarchy.** A vSAN World of our own kinds, parented among
   themselves, touching nothing of vCenter's. Safe and self-contained; loses
   the co-location with vCenter objects that was a deliberate design goal.

Option 1 is the correct immediate action if this has to stop today. Option 3 is
probably the right end state. Option 2 is the only one that keeps what we built
and it needs care.

### Retraction

`_vc_parent`'s docstring says attaching this way means "Operations matches the
existing object rather than creating a second one". True, and incomplete: it
matches the object and then overwrites its relationships. The earlier rename
bug was the same root cause showing in a different field -- we are writing to
objects we do not own, and the name was simply the first symptom noticed.

## Identity: the TCP/IP stack should probably be a property, not a key

Raised 2026-10-06 by the netstats pack, which models the same kernel ports from
the host command surface and made the opposite choice.

Two kinds here put the TCP/IP stack **inside object identity**:

```
vsan-vnic-net      identity: ['host_uuid', 'stack', 'vmknic']
vsan-tcpip-stats   identity: ['host_uuid', 'stack']
```

That is faithful to the source -- the Performance Service reports the stack as a
component of `entityRefId`, so it falls out of parsing. It is not obviously
right for Operations.

**The consequence: a vmknic moved between TCP/IP stacks becomes a different
object and loses its history.** netstats keeps `netstack` as a *property*, so
identity is host plus vmk and the interface keeps its history across a move.
Theirs follows what the interface *is*; this pack follows how perfsvc *reports*
it.

A vmk name is unique per host regardless of stack, so `host_uuid + vmknic` is a
sufficient key. The stack adds nothing to uniqueness and costs history on the
one occasion it changes. On that reading netstats has it right and this pack
does not.

**Not changed, because changing identity is a schema change**: existing objects
would be abandoned and recreated, which means a real uninstall rather than an
install over the top, and it discards the history it is meant to protect. Worth
doing at the next release that breaks schema anyway, not before.

**Cross-pack consequence, worth knowing before anyone writes a comparison:** the
two packs' object keys for the same kernel port do not match. A comparison must
join on **host plus vmk**, never on the object key.

### Correction: the upgrade check was blind to identity

Found 2026-10-06 while verifying a netstats claim. The schema comparison used to
decide "install over the top" versus "uninstall first" matched on
`<ResourceKind key="` -- anchoring `key` as the **first** attribute. It is not:

```xml
<ResourceIdentifier default="" key="vcenter_host" nameKey="5" required="true"
                    dispOrder="0" enum="false" type="string" identType="1"/>
```

So the identifier comparison found **zero of 90** and silently compared two
empty sets. Every upgrade verdict given so far rested on kinds, attributes and
credential kinds only, and never checked identity -- which is precisely the
dimension that forces an uninstall.

The verdicts were right anyway, because no identity has changed since 1.3.1. Right
by luck, not by checking.

Corrected in QUICKSTART, and the comparison now includes the **key and identType
pair** rather than the key alone. netstats established that `identType` 1 means
part of uniqueness and 2 means informational, and that demoting 1 to 2 leaves
the field in the schema while still changing every computed identity. Comparing
names alone would miss a demotion, which is the exact change contemplated for
`stack`.

Re-verified across every build: 1.3.1 through 1.4.3 to 1.4.4, all still over the
top, now on 70 kinds, 971 attributes and 20 identifier pairs.

## suite-api 401 orphans every object at VCF-managed sites (2026-10-06)

Observed at vc.vcf.gillaspy.org, VCF Operations 9.0.2. Collector log:

    mapped 3 hosts, 28 VMs, 1 clusters to vCenter objects
    post https://172.17.0.1/suite-api/api/resources/query: ERROR(401)   [x13]
    linked 474 objects to 0 vCenter parents (13 parents skipped)

Metrics collect correctly. Nothing attaches. Views report the selected object
as not applicable; Topology is a single node.

### Verified

- vCenter side is healthy. instanceUuid 95bc97f2-e78d-45bd-b6c7-b9a77beb0529,
  cluster vSAN uuid present, 3 of 3 host node UUIDs readable, checked directly
  with PowerCLI as administrator@vsphere.local.
- The lab works with the IDENTICAL architecture. VsanHostMetrics runs on
  collector 3 (vsan-mp-test01, local=False) -- a REMOTE collector -- and
  esxi03.denick.lab carries 168 VsanHostMetrics children alongside 13 VMWARE
  children. The merge works when suite-api answers.
- The suite-api host and credential are injected by Operations via
  cluster_connection_info (aria/ops/adapter_instance.py:48-56). We do not
  choose or see them.

### Refuted

- "Adapter runs on the master in the lab" -- it does not, it runs on a remote
  collector.
- "suite-api fails from remote collectors" -- it succeeds from one in the lab.
- "authSource: LOCAL is wrong" -- the SDK does hardcode it
  (suite_api_client.py:111) but the lab authenticates with LOCAL and works.
- The configured vCenter credential is unrelated; it is a different connection.

### RESOLVED 2026-10-06: the adapter never acquired a token

SuiteApiClient acquires its token in __enter__ and NOWHERE else
(suite_api_client.py:79), and _to_vrops_request sets the Authorization header
only `if self.token`. _preserve_existing_children called the client without a
`with`, so every suite-api request since 1.4.3 went out unauthenticated.

Reproduced directly against the lab with the same credentials:

    no 'with':  token='' -> POST api/resources/query -> HTTP 401
    with:       token acquired -> HTTP 200, 4 HostSystem objects

Confirmed in the field. The LAB adapter log shows the identical failure:

    post https://10.20.0.129/suite-api/api/resources/query: ERROR(401)
    linked 848 objects to 0 vCenter parents (35 parents skipped)

So the lab was never working. Its visible relationships were written by 1.4.2
or earlier and survived only because 1.4.3 stopped claiming those parents, so
nothing overwrote them. Sites that installed fresh at 1.4.3+ had no such
history and reported the bug. There was no environmental difference between
the lab and any failing site.

Fixed in two parts. 84ebf45 (1.4.5) acquired the token, which removed the 401
and revealed a second defect it had been hiding: the suite API does not filter
on identifiers at all, so every lookup returned the whole resource kind and
every parent was rejected as ambiguous. 1.4.6 resolves parents from a per-kind
index matched client-side.

CONFIRMED IN THE FIELD 2026-10-06: relationships attach in two environments on
1.4.6. The three-release orphaning is closed.

### The two measurements that would end it

1. Raise that adapter's log level to DEBUG. suite_api_client.py:351 is
   `logger.debug(result.text)` -- Operations' own reason string, suppressed at
   INFO.
2. Search the same log for `acquire`. `auth/token/acquire: OK(200)` means
   authentication succeeded and this is permissions; `Could not acquire
   SuiteAPI token` means it is the credential.

Also unexamined: gillaspy has THREE adapter instance log directories (1253,
1725, 2170). Stale registrations have not been ruled out.

### Standing decision

BACKLOG's earlier three-option analysis already concluded that building our own
hierarchy is the right end state and that the suite-api union "adds an API
dependency the adapter does not currently have". That dependency is what fails
here. Do not design the replacement until the 401 cause is known -- a cause
that also affects object identity or instance registration would be inherited
by any new hierarchy.
