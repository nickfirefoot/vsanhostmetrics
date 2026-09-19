# vSAN Host Metrics — beta scaffold

Direct-from-host vSAN telemetry for VCF Operations. Beta scope: the nine
`vmware_esx_tcppkt_*` counters off `https://<esxi>/vsanmetrics`, as one
resource kind.

## What's here

| File | SDK dependency | Notes |
|---|---|---|
| `app/vsanmetrics.py` | none | Scrape, Prometheus parse, counter→rate cache, derived percentages. The logic. |
| `app/adapter.py` | yes | `get_adapter_definition()` / `test()` / `get_endpoints()` / `collect()`. Thin glue. |
| `app/constants.py` | none | Keys, and the Broadcom thresholds for symptom definitions. |
| `test_vsanmetrics.py` | none | Offline tests. 6/6 passing. Run these first. |

The split is deliberate: everything that can be wrong about the data is in
`vsanmetrics.py`, which has no SDK imports and runs anywhere.

## Build host

A throwaway Linux VM on a lab segment. 2 vCPU / 4 GB / 40 GB.

```sh
# Ubuntu 24.04
sudo apt update && sudo apt install -y python3-venv python3-pip docker.io
sudo usermod -aG docker "$USER" && newgrp docker

python3 -m venv ~/.mp && source ~/.mp/bin/activate
pip install vmware-vcf-operations-integration-sdk
```

Check the SDK's Requirements page for the exact minimum Docker and Python
versions rather than assuming these are enough.

Verify reachability to a host before anything else — `mp-test` doing a real
scrape is the whole point of building here rather than on your desktop:

```sh
curl -sk -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOK" https://esxi01.example.com/vsanmetrics
```

## Run the offline tests first

```sh
cd vsan-net-mp && python3 test_vsanmetrics.py
```

If the rate math is wrong here it will be wrong in Operations, and this costs
no infrastructure to find out.

## Wire into a project

```sh
mp-init          # name: vsan-host-metrics, language: Python, adapter kind: VsanHostMetrics
```

Then, into the generated project:

1. Copy `app/vsanmetrics.py` and `app/constants.py` in as-is.
2. Open the **generated** `app/adapter.py`, copy its import block over the one
   at the top of this `adapter.py`, and keep its `main()` dispatch block.
   The SDK was renamed from `aria` to `vcf` in 9.0 and the package path may
   have moved; the generated file is ground truth.
3. Merge the rest of this `adapter.py` in.
4. Nothing to add to `adapter_requirements.txt` — stdlib only.

```sh
mp-test          # prompts for hosts + token, then prints objects and metrics
```

`mp-test` never touches a container registry, so you can get all the way to
correct objects and plausible rates before dealing with Harbor.

**Run `mp-test` at least twice.** The first collection emits no rates by
design — there's no baseline yet. If you only run it once and see empty
metrics, that is the code working.

## Getting the token

Per host, on the host:

```sh
configstorecli config current get -c vsan -g system -k vsan
# -> metric_subscriptions[0].auth_token
```

**This is the weak point of the beta.** The adapter runs in a container on a
Cloud Proxy and cannot run `configstorecli` on each host, so the token is a
config field you paste in. Two things to settle before this is more than a lab
pak:

- Are the tokens identical across hosts in the cluster, or per-host? Compare
  them. Per-host means one credential per host, which the current single
  credential field doesn't model.
- What rotates them, and how does the adapter notice? A 401 should be
  distinguishable from a network failure and surfaced as a specific error, not
  a silent non-collecting object.

## Known gaps, in priority order

1. **The OOO denominator is wrong-ish.** `tcpPacketsTotal` is rx+tx; the
   Broadcom thresholds are relative to received packets, so the percentages
   understate by roughly 2×. See the caveat in `derive_percentages()`. Fix
   before trusting the alerting.
2. **No relationship to the vCenter adapter's `HostSystem`.** Without it these
   objects are an island nobody can navigate to. See the TODO in `collect()`.
3. **No `content/`.** Metrics with no symptoms attached are just storage. The
   thresholds are in `constants.py` ready to become symptom definitions.
4. Token handling, above.

## Deploy, when you get there

`mp-build` → push image to registry → set registry FQDN, repo path and
**image digest** in the adapter `.conf` on the cluster nodes → install the
`.pak` → restart the Cloud Proxy service → create the adapter instance and
assign it to that proxy.
