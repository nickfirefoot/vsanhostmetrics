# BACKLOG

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
infers counter-vs-gauge from observed behaviour, name suffix and HELP wording,
because the exposition carries no `# TYPE` lines. 178 counters and 207 gauges,
of which 21 fall to the safe default (gauge). Evidence and confidence per
metric are in `docs/metric-kinds.json`. A counter misfiled as a gauge shows an
obvious since-boot ramp; the reverse would be a plausible-looking wrong number,
which is why the default leans this way. Worth eyeballing the low-confidence
list against real graphs once data accumulates.

**Token rotation detection. OBSERVED 2026-09-22, no longer theoretical.**
A token that worked at 03:16 and again around 12:30 returned 403 by 21:41 the
same day. Both the token in `~/esxi.env` and the older one stored in
`connections.json` failed simultaneously, so this was rotation at the host, not
a stale copy.

What the adapter did, and why it is not good enough:

```
ERROR scrape failed for esxi01.example.com: HTTP Error 403: Forbidden
INFO  Finished 'Collection' in 0.05s
{"nonExistingObjects": [], "relationships": [], "result": []}
```

The error handling worked as designed -- the host was skipped rather than
failing the whole collection -- but the collection then returned **empty and
successful**. In Operations that is a silently non-collecting adapter: no
error surfaced, no alert, objects simply stop receiving data. Someone would
notice days later from a flat graph.

Made worse by the host answering 403 for every authentication failure and never
401 (`BUGS-UPSTREAM.md` item 4), so a rotated token is indistinguishable from a
permissions problem without out-of-band knowledge.

Minimum fix: when **every** configured host fails to scrape, the collection
should surface a specific error rather than returning an empty success. A 403
specifically should say "credential rejected -- the bearer token may have
rotated; re-read it with `configstorecli ... -n`", because that is the actual
cause far more often than a genuine permissions change.

Still unknown and worth finding out: **what rotates these tokens and on what
schedule.** A ~9-hour lifetime would make manual credential entry unworkable
at any scale, and would change the design -- the adapter might need to read the
token itself rather than take it as configuration.

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
