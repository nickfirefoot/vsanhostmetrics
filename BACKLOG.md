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

**Finish steps 9-10.** Pak installed, adapter instance created, objects
appearing with real identifiers. Until then the deploy half of the pipeline is
documented but unproven.

## Automation, once the above is proven

**`post-receive` hook on a bare repo on the build host.** Push over SSH, hook
runs tests, bumps `Implementation-Version`, runs `mp-build`, and either swaps
the digest (fast path) or uploads the pak. Deliberately deferred: automating a
sequence whose last steps have never been executed would give repeatability of
the wrong thing. Design notes are in the session history; the shape is a bare
repo plus hook rather than a webhook receiver, because no inbound listener is
needed beyond SSH.

## Correctness

**`io_type` label collision silently discards half the traffic.** Confirmed
against a live scrape of `esxi01.example.com` on 2026-09-22.

`vmware_esx_tcppkt_total` and `vmware_esx_tcppkt_bytes_total` are each emitted
**twice** per (host_uuid, stack), distinguished only by an `io_type` label of
`rx` or `tx`. The other seven counters carry no `io_type`. In `collect()`:

```python
grouped.setdefault(ident, {})[vm.TCP_COUNTERS[name]] = rate
```

both samples map to the same friendly key under the same ident, so the second
overwrites the first. `tcpPacketsTotal` and `tcpBytesTotal` therefore report
**rx or tx arbitrarily, depending on iteration order** -- not the sum. Nothing
in `vsanmetrics.py` references `io_type` at all.

**Measured 2026-09-22 on esxi01, same-window controlled test: `tx` wins.**
The exposition emits `rx` before `tx`, so the `tx` sample is written last and
survives. Deterministic, not random.

```
tcpPacketsTotal   rx  1,039.823   tx  1,306.462   rx+tx  2,346.285
                  EMITTED 1,306.432   <- tx
tcpBytesTotal     rx    942,276   tx  7,422,002   rx+tx  8,364,278
                  EMITTED 7,421,833   <- tx
```

So the adapter reports **transmit-only** and discards all receive traffic --
roughly 44% of packets and 11% of bytes on that host.

This makes three of the four percentages **dimensionally wrong**, not merely
mis-scaled: they divide a receive-side event count by a transmit-side packet
count.

| Metric | Numerator | Denominator | Verdict |
|---|---|---|---|
| `outOfOrderPct` | rcv out-of-order | tx packets | wrong |
| `duplicateAckPct` | rcv duplicate ACKs | tx packets | wrong |
| `duplicatePacketPct` | rcv duplicate packets | tx packets | wrong |
| `retransmitPct` | snd retransmits | tx packets | **correct** -- both tx |

`retransmitPct` is right by accident, since retransmits are transmit-side.

This supersedes the previously recorded caveat. `derive_percentages()` still
says the denominator is "almost certainly rx+tx" and that an rx-only count
must be found elsewhere -- "another name from getVsanNetworkStats or rxPackets
from the vsan-vnic-net entity via /vsanperf". Both claims are wrong: it is not
the sum, and the rx-only value is right there under `io_type="rx"`. The 2x
magnitude in that caveat happened to be about right, for the wrong reason.

**Consequences:** `tcpPacketsTotal` and `tcpBytesTotal` are wrong and
non-deterministic, and all four derived percentages divide by an arbitrary
denominator. **Do not build alerting on these until fixed.**

Two fix shapes:

- *Minimal, code-only:* keep the existing metric keys, make the collision
  deterministic, and use the `io_type="rx"` sample as the percentage
  denominator. No `describe.xml` change, so no pak reinstall -- which makes it
  a good first exercise of the unverified fast path.
- *Correct, schema change:* emit `tcpPacketsRx`/`tcpPacketsTx` and
  `tcpBytesRx`/`tcpBytesTx` as distinct metrics and derive percentages from rx.
  Changes `describe.xml`, so it needs a full pak reinstall.

Also worth checking whether `sink_type` (observed constant at `cold`) can ever
vary, since it would collide the same way.

**Token rotation detection.** Scope is settled — tokens are cluster-wide — but
the adapter cannot currently tell a rotated token from a network failure. Made
harder by the host returning 403 for every authentication failure and never 401
(`BUGS-UPSTREAM.md` item 4). Whatever the handling, the failure must surface as
a specific error, not a silently non-collecting object.

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
