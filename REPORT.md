# REPORT — vSAN host metrics beta, `mp-test` bring-up

Branch `agent/beta-vsan-host-metrics`. Scope per `HANDOFF.md`: get `mp-test` to
collect the nine TCP counters from `esxi01.example.com` and emit correctly
identified objects with plausible rates, then stop. No `mp-build`, no deploy.

**Outcome: all success criteria met.** One `VsanHostTcpIp` object, real
identifiers, 9 rate metrics + 4 derived percentages, validation clean. Getting
there required fixing a defect that would have prevented the adapter from ever
emitting a single rate metric, in test or in production — see §3b.

---

## 1. Prereq versions found

| Component | Version |
|---|---|
| Docker | 29.1.3 (build 29.1.3-0ubuntu3~24.04.2) |
| Python | 3.12.3 |
| SDK CLI (`mp-init`/`mp-test`/`mp-build`) | 1.3.1 |
| Adapter lib (`...-sdk-lib`, in-container) | 1.1.0 |
| Container base image | `base-adapter:python-1.2.0` |
| Host | `esxi01.example.com` → <vcenter-ip> |

`docker ps` works as `vsanmp` (the `docker` group is active). The locally
installed lib 1.1.0 matches the generated `adapter_requirements.txt` pin
(`~=1.1.0`), so local introspection was valid ground truth for the container's
API surface.

### Deviation: `mp-init` could not be used
`mp-init` cannot complete on this build host. Its final step calls
`venv.create(..., with_pip=True)`; this host has no `ensurepip`
(`python3.12-venv` is not installed and installing it needs sudo). That raises
`SystemExit`, which `mp-init` catches in a broad
`except (KeyboardInterrupt, Exception, SystemExit)` and responds to by
`shutil.rmtree`-ing the project it just generated — so a plain run leaves
nothing behind.

Blast radius verified as bounded: `NewProjectDirectoryValidator` rejects any
path that already exists and is non-empty, so the deleted path is only ever the
scaffold `mp-init` itself just created. `~/vsan-net-mp` could not be targeted.

`scaffold_project.py` (this branch) replaces it: same `PythonAdapter` generator,
same answers, `create_project()` + `_build_requirements_file()`, skipping only
`create_virtual_environment()`. That venv is an IDE convenience; `mp-test` runs
the adapter in a container built from `adapter_requirements.txt`. Project lives
at `~/vsan-host-metrics` and is registered in the SDK config.

## 2. Offline test result

**8/8 passed** (was 6/6; two tests added for the §3b fix).

```
ok    test_baseline_survives_a_fresh_process
ok    test_corrupt_cache_costs_one_interval_not_a_crash
ok    test_first_interval_emits_nothing
ok    test_hosts_do_not_collide
ok    test_parse_filters_and_labels
ok    test_reboot_discards_whole_host
ok    test_second_interval_gives_rates
ok    test_zero_denominator_is_safe
```

## 3a. SDK API names that differed, old → new

The anticipated `aria`→`vcf` import rewrite is a **NO-OP**. The generated
`adapter.py` imports `aria.ops.*` at unchanged paths; there is no `vcf`
namespace in lib 1.1.0. Three real mismatches were found:

| # | Assumed by `adapter.py` | Actual in lib 1.1.0 |
|---|---|---|
| 1 | `Units.RATIO.PER_SECOND` | **`Units.RATE.PER_SECOND`** — the `Ratio` group defines only `PERCENT`; per-second units live in `Rate`. Emitted attributes now carry `unit=per_second, is_rate=True`. |
| 2 | `define_bool_parameter(...)` | **`define_enum_parameter(key, values=["true","false"], default="true")`** — no bool parameter type exists. `_verify()` already parsed the string form, so no logic change. |
| 3 | `cred.define_password_parameter(..., description=...)` | **no `description` kwarg** — credential parameters accept only `key`, `label`, `required`. The `configstorecli` hint moved into the label and a comment. |

Confirmed as correct and unchanged: `define_string_parameter`,
`define_credential_type`, `define_object_type`, `define_string_identifier`,
`define_string_property`, `define_metric`, `Identifier`, `result.object`,
`obj.with_metric`, `obj.with_property`, `TestResult.with_error`,
`EndpointResult.with_endpoint`.

Also adopted from the generated template, and worth recording:

- **The `adapter_definition` dispatch branch in `main()`.** The previous
  `main()` was a `...` stub and lacked it entirely; `mp-test` and `mp-build`
  both require it.
- **`container_memory_limit`** advanced int parameter, without which container
  memory cannot be tuned at configuration time.
- `aria.ops.adapter_logging` in place of stdlib `logging`; `Timer` around the
  four entry points; dropped the unused `Key, Object` imports.

### Watch item explained
Importing `aria.ops.adapter_instance` outside the container raises
`IndexError`: `AdapterInstance.from_input`'s default argument is `sys.argv[-2]`,
evaluated at class-definition time, so it needs ≥2 argv entries. Not a fault,
and it does **not** recur inside `mp-test`. To exercise the module offline, pad
`sys.argv` first.

## 3b. Defect found: no rate metric could ever be emitted

**This is the most important finding in this report.**

`commands.cfg` (generated, not ours) invokes:

```
collect=/usr/local/bin/python app/adapter.py collect
```

Every collection starts a **fresh Python interpreter**. `_RATES` was a
module-level `vm.RateCache()`, so it was re-initialized on every single
collect and the baseline was always empty. `RateCache`'s docstring claim —
"State lives for the container's lifetime" — does not hold under this execution
model. The adapter would have emitted **zero** rate metrics forever, in
`mp-test` and on a Cloud Proxy alike.

This is worth dwelling on, because `HANDOFF.md` warns twice that empty metrics
on run 1 are "the code working correctly, not a bug… do not fix it." That is
true of run 1, and it also perfectly camouflages a defect that makes *every*
run empty. Observed directly: two separate `mp-test collect` invocations, then a
3-collection `long-run` inside a single container, all returned `"result": []`.

**Fix applied** (deliberate design change, flagged for review):
`RateCache` gained an optional `path`. When set, the baseline is persisted as
JSON and reloaded on construction, so it survives across processes. Defaults to
`/tmp/vsan_rate_cache.json` inside the container, overridable via
`VSAN_RATE_CACHE`.

- `time.monotonic()` retained as the clock: it is `CLOCK_MONOTONIC` on Linux,
  which is kernel-wide, so timestamps stay comparable across those separate
  processes and are immune to NTP steps.
- Writes are atomic (`os.replace`); a missing or corrupt cache costs one
  interval rather than raising.
- Persistence is **opt-in**, so the default `RateCache()` stays purely
  in-memory and the original tests are unaffected.

### Secondary defect found while debugging this: `/var/log` is not writable
`mp-test` bind-mounts the project's `logs/` onto the container's `/var/log`
(`docker_wrapper.py`). Host `vsanmp` is **uid 1001**; the container's
`aria-ops-adapter-user` is **uid 1000**; `logs/` is mode 755. The adapter
therefore cannot write to `/var/log`, which silently defeated
`setup_logging("adapter.log")` — there was no adapter log at all until `logs/`
was opened up, which is why this took a while to see. This is why the rate cache
defaults to `/tmp` (container-local, always writable, correct
container-lifetime scope) rather than `/var/log`.

**For deployment this needs a decision**: on a real Cloud Proxy the uid mapping
and log volume differ, so confirm where the adapter may persist state before
trusting `/tmp` there. `/tmp` also means a container restart costs one interval,
which is the originally intended behavior.

## 4. `mp-test` run 1 and run 2 output

Both runs are separate `mp-test ... collect` invocations, i.e. separate
containers and separate processes, with the cache persisted between them.

### Run 1 — cold, no baseline (correct, by design)
```json
{
    "nonExistingObjects": [],
    "relationships": [],
    "result": []
}
```
Cache file written: 3753 bytes.

### Run 2 — baseline present
```json
"result": [
  {
    "key": {
      "adapterKind": "VsanHostMetrics",
      "objectKind": "VsanHostTcpIp",
      "name": "esxi01.example.com [defaultTcpipStack]",
      "identifiers": [
        {"key": "host_uuid", "value": "6a46db86-350f-f7e5-653d-9c6b00c512b6", "isPartOfUniqueness": true},
        {"key": "stack",     "value": "defaultTcpipStack",                    "isPartOfUniqueness": true}
      ]
    },
    "metrics": [
      {"key": "tcpPacketsTotal",      "numberValue": 477.72951316972006},
      {"key": "tcpBytesTotal",        "numberValue": 2600449.5658124643},
      {"key": "rcvDuplicatePackets",  "numberValue": 0.09846032835319869},
      {"key": "rcvDuplicateAcks",     "numberValue": 0.39384131341279477},
      {"key": "sackRcvBlocks",        "numberValue": 0.0},
      {"key": "sackSendBlocks",       "numberValue": 0.0},
      {"key": "sackRetransmits",      "numberValue": 0.0},
      {"key": "sndRetransmitPackets", "numberValue": 0.0},
      {"key": "rcvOutOfOrderPackets", "numberValue": 0.0},
      {"key": "outOfOrderPct",        "numberValue": 0.0},
      {"key": "retransmitPct",        "numberValue": 0.0},
      {"key": "duplicateAckPct",      "numberValue": 0.08244023083264633},
      {"key": "duplicatePacketPct",   "numberValue": 0.020610057708161583}
    ],
    "properties": [
      {"key": "hostname",          "stringValue": "esxi01.example.com"},
      {"key": "vsan_cluster_uuid", "stringValue": "5deb636e-91b5-11f1-aef5-000c296fd50e"}
    ]
  }
]
```

```
Object Type                    | Count | Metrics | Properties | Events | Parents | Children
-------------------------------+-------+---------+------------+--------+---------+---------
VsanHostMetrics::VsanHostTcpIp | 1     | 13      | 2          | 0      | 0       | 0
Validation passed with no errors
```

Success criteria check:

- ≥1 `VsanHostTcpIp` object — **yes**, 1.
- Real `host_uuid` and `defaultTcpipStack`, not `unknown`, not the hostname
  fallback — **yes**, both from host labels.
- `hostname` and `vsan_cluster_uuid` populated — **yes**.
- Nine rate metrics, non-negative — **yes** (9 rates + 4 percentages = 13).
- Container cost per collection: ~0.6 s, ~6–12 % avg CPU, ~4 % of a 1 GiB limit.

## 5. Actual percentages, and whether they are plausible

From run 2 (interval ≈ 65 s):

| Metric | Value |
|---|---|
| `outOfOrderPct` | 0.0 % |
| `retransmitPct` | 0.0 % |
| `duplicateAckPct` | 0.0824 % |
| `duplicatePacketPct` | 0.0206 % |

**Plausible.** `rcvOutOfOrderPackets` and `sndRetransmitPackets` were both
flat-zero over the interval, so 0.0 % is arithmetically right rather than
suspicious: a quiet fabric simply had no out-of-order or retransmitted packets
in ~65 s. `duplicateAckPct` at 0.08 % is comfortably inside Broadcom's healthy
band.

Cross-checked against since-boot counters, which also gives a sanity figure
independent of the interval:

```
rcvoopack_total        =     44,810
tcppkt_total{io_type=rx} = 63,065,904
since-boot OOO vs rx   = 0.0711 %     (Broadcom healthy: < 0.1 %)
```

**`HANDOFF.md`'s stated expectation is stale.** It says "`rcvoopack` was 2 since
boot, so anything above a few tenths of a percent means the math/denominator is
off." The actual counter is 44,810, not 2 — the host has clearly been up far
longer or under different load since that note was written. The 0.0711 %
since-boot ratio is still well under a tenth of a percent, so the conclusion
("small, and anything large means broken") holds even though the number behind
it does not.

### Related defect found, NOT fixed (per instruction): `io_type` label collision

`HANDOFF.md` says to leave the out-of-order denominator alone this pass. I did.
But investigating it surfaced a **separate, undocumented bug** that I am
reporting rather than fixing, because the fix requires a semantic decision:

`vmware_esx_tcppkt_total` and `vmware_esx_tcppkt_bytes_total` are **split by an
`io_type` label into `rx` and `tx` series** — 11 series from 9 counter names.
All samples also carry `sink_type="cold"`. `collect()` groups by
`(host_uuid, stack)` and assigns `grouped[ident][TCP_COUNTERS[name]] = rate`, so
the `rx` and `tx` series map to the *same* metric key and **silently overwrite
each other**. Measured on live data:

```
tcp packets/s   rx=454.82   tx=529.25   rx+tx=984.06
  -> shipped tcpPacketsTotal = 529.25   (tx only; last writer wins)
tcp bytes/s     rx=550,003  tx=2,800,120
  -> shipped tcpBytesTotal   = 2,800,120 (tx only)
```

This is worse than the documented "rx+tx understates by ~2×" caveat. The
denominator is not rx+tx at all — it is **tx-only**, while every numerator
(`rcvoopack`, `rcvdupack`, `rcvduppack`) is receive-side. The percentages are
therefore receive-side events over transmit-side packets, which is a category
error, not a scaling factor. It is also order-dependent: `tx` wins only because
the host emits `rx` first. The bug is invisible in the output because the object
still ends up with exactly 9 metric keys, matching the definition.

**Silver lining:** `HANDOFF.md` lists the rx-only denominator as blocked because
"it needs an rx-only counter that has not been identified yet." It has now been
identified — it is simply `vmware_esx_tcppkt_total{io_type="rx"}`, already in
every scrape. With that, `outOfOrderPct` would read 0.0711 % since boot against
a correct rx-only denominator.

Recommended fix, for a human to approve: key the grouping on `io_type` and emit
`tcpPacketsRx`/`tcpPacketsTx` (and the byte equivalents) as distinct metrics,
then use the rx series as the denominator in `derive_percentages()`. That
resolves the collision and the rx-only denominator in one change.

## 6. What could not be completed, and why

- **`mp-test connect` was never run interactively.** `mp-test` always prompts
  `Choose a connection:` and `prompt_toolkit` requires a TTY, so it cannot run
  from a non-interactive agent session. Worked around by writing
  `connections.json` directly (verified the SDK parses it: the connection loads
  as `esxi01` with the expected identifiers and credential keys) and by running
  `mp-test` under `script` to provide a pty. Both are test-harness workarounds
  and change nothing about the adapter.
- **`mp-test` hangs without a TTY**, even with `-c` supplying the connection.
  Under a pty the same command finishes in ~14 s. Anyone scripting `mp-test` in
  CI will need `script` or equivalent.
- **Only one host**, per fence #7. No fan-out to other cluster members.
- **No `mp-build`, no deploy, no `.pak`, no registry push**, per fence #4.
- **The `io_type` collision and the rx-only denominator are left unfixed**, per
  the explicit instruction not to change the denominator this pass. Both are
  documented above with measured numbers.
- **No `content/`** — no symptom definitions or dashboards. Thresholds remain
  staged in `constants.py`.
- **No relationship to the vCenter adapter's `HostSystem`.** The `TODO` in
  `collect()` stands; these objects are still an island.

## Open questions — one resolved

- **Token scope: RESOLVED.** Confirmed by the operator: the token is **the same
  across the cluster**, not per-host. The adapter's single credential field is
  therefore the right model, and the concern in `README.md` about needing one
  credential per host does not apply. Worth correcting there.
- **Token retrieval:** `configstorecli` masks secrets by default; the reveal
  flag on this build is **`-n`**:
  `configstorecli config current get -c vsan -g system -k vsan -n`.
  Note the host has **two** `metric_subscriptions` entries, not the single one
  the docs assume; **both tokens authenticated successfully (HTTP 200)**.
- **401 vs network failure:** this endpoint returns **403**, not 401, and
  returns it identically for a missing header, a junk token and literal
  asterisks. A 403 therefore cannot distinguish "no credential" from "bad
  credential", which weakens the plan to surface auth failures distinctly.
  Confirmed by direct test.
- **What rotates the tokens:** still unknown.
- **The rx-only denominator:** no longer an open question — see §5.

## Deferred to an off-cycle (operator's direction, not this pass)

- Expand from 9 counters to the full ~153–155 metrics the schema exposes, once
  these counters are validated against what Operations expects.
- Collect on 5-minute intervals aligned to the `:00/:05/:10` pattern past the
  hour, to gauge the load this puts on ESXi host CPU and network.
- Dashboard layout: with that many metrics, likely separate tabs; the idiomatic
  way Operations organizes this still needs research.
