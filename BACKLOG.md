# BACKLOG

## Pending next release — batched, do not ship individually

Changes committed to source but **not yet in a published pak**. Batch these
into one release rather than cutting a version per fix.

| Item | Status | Needs |
|---|---|---|
| Real EULA (`eula.txt`) | committed | rebuild — the scaffold placeholder left the install form's agreement box empty |
| Network rapid dashboard | generated, imports, panels error | `colorBy` binding confirmed against a working example |
| `TextDisplay` inline body | does not render | a configured example; `description` was assumed to be the body field |
| `TextDisplay` `locationUrl` | "URL is not available" | lab egress is fine (Cloud Proxy reaches raw.githubusercontent 200/56ms), so the suspect is `text/plain` + `nosniff` being rejected in HTML view mode. GitHub Pages would serve `text/html` and settle it |
| Backpressure + disk rapid dashboards | designed, not built | the same `colorBy` fix; then ~20 min each |

| Cluster selector on rapid dashboards | requested | a populated `dashboardNavigations` — wire any two widgets in the UI and export. Heatmaps become `selfProvider: false` and receive the selected cluster; works because 1.2.0 parents every object to its `ClusterComputeResource` |

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

### Out of scope — separate packs

Same `Rapid <domain> <subject>` convention, different repositories, so the
families stay distinct in an operator's search box.

- **Network statistics pack.** Will contribute `Rapid Network ...` dashboards.
  Shares this pack's naming and the rapid-dashboard principle (error, loss and
  congestion signals; never throughput as the primary), but is its own
  adapter and its own repo.
- **Memory tiering.** Wanted, and explicitly another repository. Note that
  `VsanMemory` (50 metrics) and `VsanSystemMemory` in *this* pack cover vSAN's
  own heap and slab consumption, which is a different thing from memory
  tiering and should not be confused with it when that work starts.

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

## Object naming

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
