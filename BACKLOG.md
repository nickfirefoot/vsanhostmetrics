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

**This is structural, not a two-metric mapping error.** Surveyed the full
exposition (1926 series) on 2026-09-22:

- `io_type` is a general-purpose label here, not a TCP concept:
  `write` 67, `read` 67, `unmap` 17, `recoveryWrite` 12, `resyncRead` 10,
  `rx` 8, `tx` 8. Only 2 of the 8 `rx` series are ours. **Any future metric
  added from this exposition that carries `io_type` will collide identically.**
- `sink_type` is `cold` on all 11 of our samples, but takes `cold` (1731) and
  `hot` (195) elsewhere in the exposition. Safe today by luck, not design; a
  hot variant of a TCP counter would reproduce the bug with no change on our
  side.
- `stack` appears only as `defaultTcpipStack` in this lab today, but **do not
  treat that as fixed**. An ENS/EDP stack (NSX Enhanced Datapath) can appear on
  hosts configured for it. This is already handled correctly: `stack` is an
  `Identifier`, so a new stack value produces a new object
  (`<host> [<stack>]`) rather than colliding. No change needed -- but any fix
  must preserve `stack` in the object identity.

So the fix should address the keying scheme rather than special-casing two
metrics. The principle to apply, which `stack` already follows and `io_type`
does not:

- A label that distinguishes **different entities** belongs in the object
  **identity**. `stack` is one of these -- `defaultTcpipStack` and an ENS/EDP
  stack are genuinely different things to monitor, and each should be its own
  object.
- A label that distinguishes **different measurements of the same entity**
  belongs in the **metric key**. `io_type` is one of these -- rx and tx are two
  facts about one TCP/IP stack, not two stacks, so they should become
  `tcpPacketsRx` / `tcpPacketsTx` rather than separate objects.

And `collect()` should **fail loudly on an unexpected collision** rather than
silently overwriting, so the next label like this is found by an error rather
than by someone noticing the numbers look odd months later.

**Token rotation detection.** Scope is settled — tokens are cluster-wide — but
the adapter cannot currently tell a rotated token from a network failure. Made
harder by the host returning 403 for every authentication failure and never 401
(`BUGS-UPSTREAM.md` item 4). Whatever the handling, the failure must surface as
a specific error, not a silently non-collecting object.

**`verify_certs: true` is untested, and the reasoning behind it may be wrong.**
`get_endpoints()` hands each host's URL to Operations, which fetches the cert
and prompts the user to accept it -- confirmed working on 2026-09-22 when
adding a third host. The docstring on `scrape()` then claims you can leave
`verify=True` with `cafile=None`.

That inference has a gap. The accepted cert lands in **Operations'** trust
store, but `scrape()` runs **inside the adapter container**, where
`ssl.create_default_context(cafile=None)` reads the *container's* CA bundle
from the base image. Whether the SDK propagates Operations-accepted certs into
the container is unverified.

ESXi certs here are VMCA-signed by `vcenter.example.com`, so they will not chain
against any public root.

To test: accept the certs, flip `verify_certs` to `true`, and watch whether
collection continues or every host starts failing in `collect()`'s exception
handler. If it fails, the options are to pass the VMCA root via `cafile`, or to
keep `verify_certs: false` and document why. Either way the current docstring
should stop asserting something untested.

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
