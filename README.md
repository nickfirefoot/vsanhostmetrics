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
| `test_vsanmetrics.py` | none | Offline tests. 8/8 passing. Run these first. |

The split is deliberate: everything that can be wrong about the data is in
`vsanmetrics.py`, which has no SDK imports and runs anywhere.

### Which document to read

**Current truth — read these:**

| File | Purpose |
|---|---|
| `REQUIREMENTS.md` | Everything needed to build, stage and deploy. Versions, network prerequisites, credentials, and a repeatability checklist. **Start here for a rebuild.** |
| `README.md` | This file. What the code is, how to build it, how to deploy it. |
| `BUGS-UPSTREAM.md` | Defects in the ESXi `/vsanmetrics` exposition itself, with reproductions. Read before trusting a metric that looks wrong. |
| `BACKLOG.md` | What is not done, and why, in rough priority order. |

**Historical — accurate when written, not maintained:**

| File | Purpose |
|---|---|
| `HANDOFF.md` | The original brief: scope, fences, what "done" meant. Deliberately not rewritten as questions got answered — it records what was known at the start. |
| `REPORT.md` | Findings from the `mp-test` bring-up, including the `RateCache` defect (§3b) that would have prevented any rate metric ever being emitted. |
| `RESUME.md` | Agent session handoff: environment state and SDK API reconciliation. |
| `TAKEOVER.md` | Session takeover context, plus lab infrastructure and networking findings (§E). |

If those disagree with `REQUIREMENTS.md` or this file, these two win.

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

On **any ESXi host in the cluster** -- tokens are cluster-wide, so it does not
matter which:

```sh
configstorecli config current get -c vsan -g system -k vsan -n
# -> metric_subscriptions[].auth_token
```

**The `-n` is required and easy to miss.** Without it the token is returned
**masked**, and the masked value looks plausible enough to paste into a
credential field, where it will fail authentication. Worse, the host answers
every authentication failure with **403, never 401** (`BUGS-UPSTREAM.md` item
4), so the error does not say "bad credential" -- it looks like an
authorization or connectivity problem.

Verify the token before pasting it anywhere:

```sh
curl -sk -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOK" https://<esxi>/vsanmetrics
# 200 = good.  403 = masked, wrong, or rotated token.
```

The adapter runs in a container on a Cloud Proxy and cannot run
`configstorecli` on each host, so the token is a config field you paste in.

**Tokens are cluster-wide, not per-host** (confirmed on `example.com`,
2026-09-22). The single credential field in `get_adapter_definition()` is
therefore the right model, not a simplification -- one credential covers every
host in the cluster, and the `hosts` parameter can list them all against it.

Still open: what rotates them, and how the adapter notices. Note that this is
harder than it looks here, because the host returns **403 for every
authentication failure and never 401** -- see `BUGS-UPSTREAM.md` item 4. A
rotated token is thus not trivially distinguishable from an authorization
problem, and neither should be mistaken for a network failure. Whatever the
handling, it must surface as a specific error rather than a silently
non-collecting object.

## Known gaps, in priority order

1. **The OOO denominator is wrong-ish.** `tcpPacketsTotal` is rx+tx; the
   Broadcom thresholds are relative to received packets, so the percentages
   understate by roughly 2×. See the caveat in `derive_percentages()`. Fix
   before trusting the alerting.
2. **No relationship to the vCenter adapter's `HostSystem`.** Without it these
   objects are an island nobody can navigate to. See the TODO in `collect()`.
3. **No `content/`.** Metrics with no symptoms attached are just storage. The
   thresholds are in `constants.py` ready to become symptom definitions.

   Management Pack Builder (Developer Center -> Management Pack Builder) is not
   an alternative to this adapter, despite advertising Prometheus support. Its
   Prometheus connector needs a query backend (PromQL over `/api/v1/query`);
   `/vsanmetrics` is a raw exposition endpoint with no query API and no
   storage. Using it would mean running a Prometheus server that scrapes every
   host, then pointing Operations at that -- an extra service for a pack whose
   purpose is reading hosts directly.
4. **Token rotation handling**, above. The per-host-vs-cluster-wide question
   is settled (cluster-wide); detecting rotation is not.

## Deploy

Steps 1-4 below were performed and verified against `example.com` on
2026-09-22. Steps 5-7 are the remaining human steps.

### 1. Build and push

`mp-build` needs a TTY unless you pass `--no-ttl`, which takes every argument
as a command-line option instead of prompting:

```sh
source ~/.mp/bin/activate
set -a; . ~/harbor.env; set +a          # HARBOR_USER / HARBOR_PASS, mode 600, outside this repo
mp-build -p ~/vsan-host-metrics --no-ttl \
  -r "registry.example.com/nickfirefoot/vsanhostmetrics" \
  --registry-username "$HARBOR_USER" \
  --registry-password "$HARBOR_PASS"
```

`-r/--registry-tag` both records the target in the pak *and* pushes. A separate
`--push-registry` is only needed when the pull location differs from the push
location.

Quote the robot username. Harbor robots are named `robot$project+name`, and an
unquoted `$project` is eaten by shell expansion, producing a username like
`robot-mp+mpbuild` and a confusing `unauthorized` from `docker login`.

Output lands in `build/VsanHostMetrics_<version>.pak`, with the image digest baked
into `adapter.zip!VsanHostMetrics.conf`:

```
REGISTRY=registry.example.com
REPOSITORY=/nickfirefoot/vsanhostmetrics
DIGEST=sha256:<digest>
```

### 2. DNS for the registry

The Harbor cert's SAN is the hostname only -- there is no IP SAN -- so the
registry must be reached by name. Add an A record for the Harbor FQDN pointing
at its LoadBalancer address before anything tries to pull. An `/etc/hosts`
entry works for a build host but not for the Cloud Proxy.

### 3. Trust the Harbor CA on the Cloud Proxy

**This is the step that silently blocks everything else.** Harbor as a
Supervisor Service signs its certificate with its own `Harbor CA`, which
nothing trusts by default. Without this the Cloud Proxy fails the image pull on
certificate verification.

Extract the CA from the Supervisor:

```sh
kubectl -n svc-harbor-<id> get secret harbor-tls -o jsonpath='{.data.ca\.crt}' | base64 -d
```

Install it on the Cloud Proxy (Photon OS, Docker):

```sh
mkdir -p /etc/docker/certs.d/<harbor-fqdn>
cp harbor-ca.crt /etc/docker/certs.d/<harbor-fqdn>/ca.crt
chmod 644 /etc/docker/certs.d/<harbor-fqdn>/ca.crt
```

No daemon restart -- Docker reads that path per pull. Reverse with
`rm -rf /etc/docker/certs.d/<harbor-fqdn>`.

SSH is disabled by default on the Cloud Proxy appliance; enable it from the VM
console with `systemctl enable --now sshd`, and consider turning it back off
afterwards.

Verify trust before moving on. `Verify return code: 0 (ok)` is what you want;
`21 (unable to verify the first certificate)` means the CA is not installed:

```sh
echo | openssl s_client -connect <harbor-fqdn>:443 2>/dev/null | grep 'Verify return code'
```

### 4. Prove the pull works

Do this before installing the pak -- it isolates registry problems from
management-pack problems:

```sh
printf '%s' "$HARBOR_PASS" | docker login <harbor-fqdn> -u "$HARBOR_USER" --password-stdin
docker pull <harbor-fqdn>/<project>/vsan-host-metrics@sha256:<digest>
```

The reported digest must match the `DIGEST` line in the pak's `.conf`.

### 5. Install the pak

**Replacing an existing install?** Remove the old pack first
(Administration -> Integrations -> Repository, select it, Uninstall) and delete
its adapter instances. A schema change means the old `describe.xml` is already
in the Operations database; uninstalling clears it rather than leaving orphaned
resource kinds and objects behind. Skipping this is how you end up with two
generations of metric definitions and objects that never collect again.

Install `build/VsanHostMetrics_<version>.pak` through the VCF Operations UI:
**Administration -> Integrations -> Repository -> Add**. (Broadcom's docs say
Data Sources -> Integrations; Administration -> Integrations is the path
actually present in 9.x. Not "Software Depot", which configures the VCF
software depot and is unrelated.)

Tick **both** checkboxes in that dialog:

- *Install the PAK file even if it is already installed* -- needed for every
  reinstall iteration
- *Ignore the PAK file signature checking* -- **required**, this pak is
  unsigned (`pak_validation_script` is empty and nothing signs it) This writes the adapter's `describe.xml` schema
-- resource kinds, identifiers, attributes -- into the Operations database, and
drops a plugin directory alongside the existing ones in
`/usr/lib/vmware-vcops/user/plugins/inbound/`.

**Bump `version` in `manifest.txt` for every reinstall.**
Operations uses it for upgrade detection and handles same-version reinstalls
badly.

### 6. Restart the collector, create the adapter instance

The pak distributes to collectors on install -- a `VsanHostMetrics` directory
appears under `/usr/lib/vmware-vcops/user/plugins/inbound/` on the Cloud Proxy
within a minute, without any restart. Confirm the digest there matches the pak:

```sh
cat /usr/lib/vmware-vcops/user/plugins/inbound/VsanHostMetrics.conf
```

Then **Administration -> Integrations -> Accounts -> Add Account**.

**The collector selection is the step that decides whether any of this works.**
Pick your Cloud Proxy explicitly in *Cloud Proxy / Group*. Leave it on a default
collector group and Operations will try to run the container on an analytics
node, which has neither the image nor the registry CA -- and the resulting
failure looks like a registry problem rather than a placement one.

Fields, as generated by `get_adapter_definition()` (verified 2026-09-23):

| Field | Value |
|---|---|
| vCenter Server | **FQDN** of vCenter. One entry -- not a host list |
| vCenter username | e.g. `vsanmon@vsphere.local` |
| Credential (password) | that account's password |
| Verify vCenter certificate | **set to false for bring-up** -- the default is `true` and does not work unmodified; see below |
| Cloud Proxy / Group | **your Cloud Proxy**, not a default group |
| container_memory_limit | 1024, under Advanced Settings |

**The `Verify vCenter certificate` default is `true` and will fail.** Verified
2026-09-23: vCenter presents a certificate issued by the VMCA
(`CN=CA, DC=vsphere, DC=local`), which nothing in the adapter's base image
trusts, so a stock install accepting the defaults cannot connect. Two ways
forward:

- set it to **false** (what bring-up on `example.com` uses), or
- import the VMCA root from `https://<vcenter>/certs/download.zip` into the
  container trust store and leave it `true`.

If you leave it `true`, the *vCenter Server* field must hold the **FQDN**. An
IP address fails hostname matching even once the root is trusted, and that
failure is indistinguishable from an untrusted chain. The adapter's error
message names both causes.

**Expect one certificate prompt.** `get_endpoints()` hands the single vCenter
URL to Operations, which fetches the cert and asks you to accept it. One
prompt, not one per ESXi host -- the pack no longer talks to hosts at all.

Hit **Validate Connection** before saving. That runs `test()`, a real
Performance Service query, so a green result proves the credential, the
privilege and the Cloud Proxy -> vCenter network path in one go.

**The first collection emits data.** This changed with the move to the
Performance Service and the older instructions said the opposite. perfsvc
returns metrics already reduced into 5-minute buckets, so there is no counter
baseline to establish and nothing is withheld on cycle one. If the first cycle
is empty, that is a fault, not the design.

### 7. What needs a full reinstall, and what does not

Most iteration does not need step 5 at all:

| Changed | Needed |
|---|---|
| `perfsvc.py`, `collect()` logic, labels/units | rebuild, update `DIGEST` in the `.conf`, restart collector |
| `get_adapter_definition()`, `content/`, display names | full pak reinstall (regenerates `describe.xml`) |

The container is disposable; the schema written into the Operations database is
not. Snapshot the Operations cluster before schema changes -- not the Cloud
Proxy, which holds little beyond cached images and the `.conf`. Prune cached
images there periodically; each digest is roughly 265 MB on disk.

Note the fast path in row one is claimed but not yet verified -- confirm it on
the first code-only iteration before relying on it.

<!-- METRIC-REFERENCE-START -->

## Metric reference

Every metric this pack collects: **1035 attributes** (730 distinct ids) across **31 resource kinds**. Generated by `tools/build_metric_reference.py` -- do not edit by hand.

**Definition** is Broadcom's own wording from the Performance Service schema where it exists (309 of 1035 attributes). The service documents far fewer metrics than it returns, so the remainder show a derived label only, marked *(derived)*. A derived entry describes what the metric is called, not what it measures -- treat it as a starting point, not an authority.

Units are ours, not the schema's: the schema's unit hangs off the *graph* rather than the metric and disagrees with observed values by 1000x on latency. See the tool's docstring.

### Cluster Domclient — `VsanClusterDomclient`

perfsvc entity `cluster-domclient` · identified by `cluster_uuid` · 1 objects observed · 14 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `readCongestion` | Read Congestions |  | Read congestions of IOs generated by DOM owner. |
| `readCount` | Read count |  | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `unmapCongestion` | Unmap congestion |  | *(derived)* |
| `writeCongestion` | Write Congestions |  | Write congestions of IOs generated by DOM owner. |
| `writeCount` | Write count |  | *(derived)* |

### Cluster Domcompmgr — `VsanClusterDomcompmgr`

perfsvc entity `cluster-domcompmgr` · identified by `cluster_uuid` · 1 objects observed · 15 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsRecWrite` | Recovery Write IOPS | `io_operations_per_second` | vSAN cluster recovery write IOPS in the perspective of vSAN backend. |
| `iopsResyncRead` | Resync Read IOPS | `io_operations_per_second` | vSAN cluster read IOPS of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latAvgResyncRead` | Resync Read Latency | `microseconds` | vSAN cluster read average latency of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgRecWrite` | Recovery Write Latency | `microseconds` | vSAN cluster recovery write average latency in the perspective of vSAN backend. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputRecWrite` | Recovery Write Throughput | `bibyte_per_second` | vSAN cluster recovery write throughput in the perspective of vSAN backend. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `tputResyncRead` | Resync Read Throughput | `bibyte_per_second` | vSAN cluster read throughput of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |

### Cluster Domowner — `VsanClusterDomowner`

perfsvc entity `cluster-domowner` · identified by `cluster_uuid` · 1 objects observed · 46 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgDeltaCreationDomActiveLatency` | Delta creation DOM active latency (average) | `seconds` | *(derived)* |
| `avgDeltaCreationDomCreationLatency` | Delta creation DOM creation latency (average) | `seconds` | *(derived)* |
| `avgResyncParallelism` | Resync parallelism (average) |  | *(derived)* |
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsRecWrite` | Recovery Write IOPS | `io_operations_per_second` | vSAN cluster recovery write IOPS in the perspective of vSAN backend. |
| `iopsResyncRead` | Resync Read IOPS | `io_operations_per_second` | vSAN cluster read IOPS of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgRecWrite` | Recovery Write Latency | `microseconds` | vSAN cluster recovery write average latency in the perspective of vSAN backend. |
| `latencyAvgResyncRead` | Resync Read Latency | `microseconds` | Resync read latency of DOM owner. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `numCompleteDeltaToBaseResyncOps` | Num complete delta to base resync ops |  | *(derived)* |
| `numCompleteFullResyncOps` | Num complete full resync ops |  | *(derived)* |
| `numCompleteResyncOps` | Num complete resync ops |  | *(derived)* |
| `numCompleteResyncRwrBatches` | Num complete resync rwr batches |  | *(derived)* |
| `numCompleteRwrOps` | Num complete rwr ops |  | *(derived)* |
| `numCompleteSiblingToDeltaResyncOps` | Num complete sibling to delta resync ops |  | *(derived)* |
| `numInflightPriorityResyncJobs` | Num inflight priority resync jobs |  | *(derived)* |
| `numInflightSharedResyncJobs` | Num inflight shared resync jobs |  | *(derived)* |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `numPendingDecomResyncJobs` | Num pending decom resync jobs |  | *(derived)* |
| `numPendingDeltaToBaseResyncJobs` | Num pending delta to base resync jobs |  | *(derived)* |
| `numPendingFullResyncJobs` | Num pending full resync jobs |  | *(derived)* |
| `numPendingResyncJobs` | Num pending resync jobs |  | *(derived)* |
| `numPendingSiblingToDeltaResyncJobs` | Num pending sibling to delta resync jobs |  | *(derived)* |
| `numRunningDeltaToBaseResyncJobs` | Num running delta to base resync jobs |  | *(derived)* |
| `numRunningFullResyncJobs` | Num running full resync jobs |  | *(derived)* |
| `numRunningResyncJobs` | Num running resync jobs |  | *(derived)* |
| `numRunningSiblingToDeltaResyncJobs` | Num running sibling to delta resync jobs |  | *(derived)* |
| `numSuspendedDeltaToBaseResyncJobs` | Num suspended delta to base resync jobs |  | *(derived)* |
| `numSuspendedFullResyncJobs` | Num suspended full resync jobs |  | *(derived)* |
| `numSuspendedPriorityResyncJobs` | Num suspended priority resync jobs |  | *(derived)* |
| `numSuspendedResyncChangemaps` | Num suspended resync changemaps |  | *(derived)* |
| `numSuspendedResyncJobs` | Num suspended resync jobs |  | *(derived)* |
| `numSuspendedSharedResyncJobs` | Num suspended shared resync jobs |  | *(derived)* |
| `numSuspendedSiblingToDeltaResyncJobs` | Num suspended sibling to delta resync jobs |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `readCongestion` | Read Congestions |  | Read congestions of IOs generated by DOM owner. |
| `totalDeltasCreatedCount` | Deltas created count (total) |  | *(derived)* |
| `tputRead` | Read Throughput | `bibyte_per_second` | vSAN host read throughput without resync traffic in the perspective of DOM owner. |
| `tputRecWrite` | Recovery Write Throughput | `bibyte_per_second` | vSAN host recovery write throughput in the perspective of DOM owner. |
| `tputResyncRead` | Resync Read Throughput | `bibyte_per_second` | vSAN cluster read throughput of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `tputWrite` | Write Throughput | `bibyte_per_second` | vSAN host write throughput in the perspective of DOM owner. |
| `unmapCongestion` | Unmap congestion |  | *(derived)* |
| `writeCongestion` | Write Congestions |  | Write congestions of IOs generated by DOM owner. |

### vSAN Cluster RDT Latency — `VsanClusterRdtLatency`

perfsvc entity `cluster-rdt-network-latency` · identified by `cluster_uuid` · 1 objects observed · 17 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgLatency` | RDT Network VNIC Average Latency | `microseconds` | RDT network vnic average latency for last 5 seconds. |
| `kaReset` | Keepalive reset |  | *(derived)* |
| `maxLatency` | RDT Network Cluster Max Latency | `microseconds` | RDT network cluster max latency for last 5 seconds. |
| `minLatency` | RDT Network Cluster Min Latency | `microseconds` | RDT network cluster min latency for last 5 seconds. |
| `numReadyDelay` | Num ready delay |  | *(derived)* |
| `rxSbSpaceAvg` | RDT Network Socket Average Inbound Bytes | `byte` | RDT network socket average inbound bytes for last 5 seconds. |
| `rxSbSpaceMax` | RDT Network Socket Max Inbound Bytes | `byte` | RDT network socket max inbound bytes for last 5 seconds. |
| `rxSbSpaceMin` | RDT Network Socket Min Inbound Bytes | `byte` | RDT network socket min inbound bytes for last 5 seconds. |
| `txCtxQAvg` | RDT Network Average Outbound Context Bytes | `byte` | RDT network average outbound context bytes for last 5 seconds. |
| `txCtxQMax` | RDT Network Max Outbound Context Bytes | `byte` | RDT network max outbound context bytes for last 5 seconds. |
| `txCtxQMin` | RDT Network Min Outbound Context Bytes | `byte` | RDT network min outbound context bytes for last 5 seconds. |
| `txQLatAvg` | RDT Network Average Outbound Queueing Latency | `microseconds` | RDT network average outbound queueing latency for last 5 seconds. |
| `txQLatMax` | RDT Network Max Outbound Queueing Latency | `microseconds` | RDT Network Max outbound queueing latency for last 5 seconds. |
| `txQLatMin` | RDT Network Min Outbound Queueing Latency | `microseconds` | RDT network min outbound queueing latency for last 5 seconds. |
| `txSbSpaceAvg` | RDT Network Socket Average Outbound Bytes | `byte` | RDT network socket average outbound bytes for last 5 seconds. |
| `txSbSpaceMax` | RDT Network Socket Max Outbound Bytes | `byte` | RDT network socket max outbound bytes for last 5 seconds. |
| `txSbSpaceMin` | RDT Network Socket Min Outbound Bytes | `byte` | RDT network socket min outbound bytes for last 5 seconds. |

### Cluster Zdom Top Stats — `VsanClusterZdomTopStats`

perfsvc entity `cluster-zdom-top-stats` · identified by `cluster_uuid` · 1 objects observed · 12 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsUnmap` | Unmap IOPS | `io_operations_per_second` | vSAN host IOPS of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgUnmap` | Unmap Latency | `microseconds` | vSAN host average latency of trim/unmap commands generated by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oioRead` | Outstanding IO (read) |  | *(derived)* |
| `oioWrite` | Outstanding IO (write) |  | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputUnmap` | Unmap Throughput | `bibyte_per_second` | vSAN host throughput of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |

### Cmmds Net — `VsanCmmdsNet`

perfsvc entity `cmmds-net` · identified by `host_uuid` · 4 objects observed · 10 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `groupRx` | Group Inbound |  | CMMDS network group inbound. |
| `groupRxThroughput` | Group Inbound Throughput | `bibyte_per_second` | CMMDS network group inbound throughput. |
| `groupTxMcast` | Group Outbound Multicast |  | CMMDS network group outbound multicast. |
| `groupTxMcastThroughput` | Group Outbound Multicast Throughput | `bibyte_per_second` | CMMDS network group outbound multicast throughput. |
| `groupTxUcast` | Group Outbound Unicast |  | CMMDS network group outbound unicast. |
| `groupTxUcastThroughput` | Group Outbound Unicast Throughput | `bibyte_per_second` | CMMDS network group outbound unicast throughput. |
| `rdtRx` | Read Inbound |  | CMMDS network read inbound. |
| `rdtRxThroughput` | Read Inbound Throughput | `bibyte_per_second` | CMMDS network read inbound throughput. |
| `rdtTx` | Read Outbound |  | CMMDS network read outbound. |
| `rdtTxThroughput` | Read Outbound Throughput | `bibyte_per_second` | CMMDS network read outbound throughput. |

### vSAN DOM World — `VsanDomWorld`

perfsvc entity `dom-world-cpu` · identified by `host_uuid`, `world_name`, `world_id` · 315 objects observed · 3 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `readyPct` | Percentage of Ready CPU Time | `percent` | Percentage of ready CPU time. |
| `runPct` | Percentage of Running CPU Time | `percent` | Percentage of running CPU time. |
| `usedPct` | Percentage of Used CPU Time | `percent` | Percentage of used CPU time |

### vSAN Host CPU — `VsanHostCpu`

perfsvc entity `host-cpu` · identified by `host_uuid`, `cpu` · 244 objects observed · 3 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `coreUtilPct` | Percentage of CPU core uitilization | `percent` | Percentage of CPU core uitilization. |
| `pcpuUsedPct` | Percentage of Used Physical CPU Time | `percent` | Percentage of Used Physical CPU time. |
| `pcpuUtilPct` | Percentage of Physical CPU Utilization | `percent` | Percentage of physical CPU utilization. |

### Host Domclient — `VsanHostDomclient`

perfsvc entity `host-domclient` · identified by `host_uuid` · 4 objects observed · 78 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `IOPSWithinBursts` | IOPS within bursts | `io_operations_per_second` | *(derived)* |
| `IOPSWithinBurstsExclFirstObj` | IOPS within bursts excl first obj | `io_operations_per_second` | *(derived)* |
| `IOPSWithinBurstsMultiObj` | IOPS within bursts multi obj | `io_operations_per_second` | *(derived)* |
| `avgBurstArrivalTime` | Burst arrival time (average) | `microseconds` | *(derived)* |
| `avgBurstArrivalTimeMultiObj` | Burst arrival time multi obj (average) |  | *(derived)* |
| `avgBurstCompletionTime` | Burst completion time (average) | `microseconds` | *(derived)* |
| `avgBurstCompletionTimeMultiObj` | Burst completion time multi obj (average) |  | *(derived)* |
| `avgBurstPeakOIO` | Burst peak outstanding IO (average) |  | *(derived)* |
| `avgBurstPeakOIOMultiObj` | Burst peak outstanding IO multi obj (average) |  | *(derived)* |
| `avgBurstPeakOutstandingKb` | Burst peak outstanding kb (average) |  | *(derived)* |
| `avgBurstPeakOutstandingKbMultiObj` | Burst peak outstanding kb multi obj (average) |  | *(derived)* |
| `avgBurstTotalTime` | Burst total time (average) | `microseconds` | *(derived)* |
| `avgBurstTotalTimeMultiObj` | Burst total time multi obj (average) |  | *(derived)* |
| `avgPctTimeToPeak` | Percent time to peak (average) |  | *(derived)* |
| `avgPctTimeToPeakMultiObj` | Percent time to peak multi obj (average) |  | *(derived)* |
| `bandwidthWithinBursts` | Bandwidth within bursts |  | *(derived)* |
| `bandwidthWithinBurstsExclFirstObj` | Bandwidth within bursts excl first obj |  | *(derived)* |
| `bandwidthWithinBurstsMultiObj` | Bandwidth within bursts multi obj |  | *(derived)* |
| `burstsPerSecond` | Bursts per second |  | *(derived)* |
| `burstsPerSecondMultiObj` | Bursts per second multi obj |  | *(derived)* |
| `clientCacheHitRate` | Local Client Cache Hit Rate |  | Percentage of read IOs which could be satisfied by the local client cache. |
| `clientCacheHits` | Local Client Cache Hit IOPS | `io_operations_per_second` | Average local client cache read IOPS. |
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `ioCount` | IO count |  | *(derived)* |
| `iops` | IOPS | `io_operations_per_second` | *(derived)* |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsSegCleanerUnmap` | IOPS seg cleaner unmap | `io_operations_per_second` | *(derived)* |
| `iopsUnmap` | Unmap IOPS | `io_operations_per_second` | vSAN host IOPS of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvg` | Latency (average) | `microseconds` | *(derived)* |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgSegCleanerUnmap` | Latency avg seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyAvgUnmap` | Unmap Latency | `microseconds` | vSAN host average latency of trim/unmap commands generated by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyMaxRead` | Latency (max, read) | `microseconds` | *(derived)* |
| `latencyMaxSegCleanerUnmap` | Latency max seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyMaxUnmap` | Latency max unmap | `microseconds` | *(derived)* |
| `latencyMaxWrite` | Latency (max, write) | `microseconds` | *(derived)* |
| `latencyStddev` | Latency Std Dev | `microseconds` | Latency standard deviation of DOM owner. |
| `latencyStddevRead` | Latency standard deviation (read) | `microseconds` | *(derived)* |
| `latencyStddevSegCleanerUnmap` | Latency standard deviation seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyStddevUnmap` | Unmap Latency Std Dev | `microseconds` | Unmap latency standard deviation of DOM owner. |
| `latencyStddevWrite` | Latency standard deviation (write) | `microseconds` | *(derived)* |
| `lessSkewedMultiBurstsPerSecond` | Less skewed multi bursts per second |  | *(derived)* |
| `numBurstStatsSkipped` | Num burst stats skipped |  | *(derived)* |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oioRead` | Outstanding IO (read) |  | *(derived)* |
| `oioRecoveryWrite` | Outstanding IO recovery (write) |  | *(derived)* |
| `oioResyncRead` | Outstanding IO resync (read) |  | *(derived)* |
| `oioWrite` | Outstanding IO (write) |  | *(derived)* |
| `rateClientOpsBadParam` | Client ops bad param (rate) |  | *(derived)* |
| `rateClientOpsChecksumMismatch` | Client ops checksum mismatch (rate) |  | *(derived)* |
| `rateClientOpsIoError` | Client ops IO error (rate) |  | *(derived)* |
| `rateClientOpsLimitExceed` | Client ops limit exceed (rate) |  | *(derived)* |
| `rateClientOpsNoConnect` | Client ops no connect (rate) |  | *(derived)* |
| `rateClientOpsNoMem` | Client ops no mem (rate) |  | *(derived)* |
| `rateClientOpsNoSpace` | Client ops no space (rate) |  | *(derived)* |
| `rateClientOpsNotSupported` | Client ops not supported (rate) |  | *(derived)* |
| `rateClientOpsRetry` | Client ops retry (rate) |  | *(derived)* |
| `rateOtherClientOpsFailure` | Other client ops failure (rate) |  | *(derived)* |
| `readCongestion` | Read Congestions |  | Read congestions of IOs generated by DOM owner. |
| `readCount` | Read count |  | *(derived)* |
| `segCleanerUnmapCongestion` | Seg cleaner unmap congestion |  | *(derived)* |
| `segCleanerUnmapLeafOwnerLatency` | Seg cleaner unmap leaf owner latency | `microseconds` | *(derived)* |
| `segCleanerUnmapLeafOwnerMaxLatencyAvgUs` | Seg cleaner unmap leaf owner max latency avg us | `microseconds` | *(derived)* |
| `serverSwitchAvglatency` | Server switch average latency | `microseconds` | *(derived)* |
| `serverSwitchCount` | Server switch count |  | *(derived)* |
| `serverSwitchLatencyMaxUs` | Server switch latency max us | `microseconds` | *(derived)* |
| `throughput` | Throughput | `bibyte_per_second` | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputSegCleanerUnmap` | Throughput seg cleaner unmap | `bibyte_per_second` | *(derived)* |
| `throughputUnmap` | Unmap Throughput | `bibyte_per_second` | vSAN host throughput of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `unmapCongestion` | Unmap congestion |  | *(derived)* |
| `unmapCount` | Unmap count |  | *(derived)* |
| `writeCongestion` | Write Congestions |  | Write congestions of IOs generated by DOM owner. |
| `writeCount` | Write count |  | *(derived)* |

### Host Domcompmgr — `VsanHostDomcompmgr`

perfsvc entity `host-domcompmgr` · identified by `host_uuid` · 4 objects observed · 82 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `componentCongestion` | Component congestion |  | *(derived)* |
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `ioCount` | IO count |  | *(derived)* |
| `iops` | IOPS | `io_operations_per_second` | *(derived)* |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsRecUnmap` | Recovery Unmap IOPS | `io_operations_per_second` | IOPS of Recovery trim/unmap command going to disk groups on this host. |
| `iopsRecWrite` | Recovery Write IOPS | `io_operations_per_second` | vSAN cluster recovery write IOPS in the perspective of vSAN backend. |
| `iopsResyncRead` | Resync Read IOPS | `io_operations_per_second` | vSAN cluster read IOPS of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `iopsUnmap` | Unmap IOPS | `io_operations_per_second` | vSAN host IOPS of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latAvgResyncRead` | Resync Read Latency | `microseconds` | vSAN cluster read average latency of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `latencyAvg` | Latency (average) | `microseconds` | *(derived)* |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgRecUnmap` | Recovery Unmap Latency | `microseconds` | Average trim/unmap latency going to disk groups on this host. |
| `latencyAvgRecWrite` | Recovery Write Latency | `microseconds` | vSAN cluster recovery write average latency in the perspective of vSAN backend. |
| `latencyAvgServiceVMRead` | Latency avg service VM (read) | `microseconds` | *(derived)* |
| `latencyAvgServiceVMWrite` | Latency avg service VM (write) | `microseconds` | *(derived)* |
| `latencyAvgUnmap` | Unmap Latency | `microseconds` | vSAN host average latency of trim/unmap commands generated by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyMaxRead` | Latency (max, read) | `microseconds` | *(derived)* |
| `latencyMaxUnmap` | Latency max unmap | `microseconds` | *(derived)* |
| `latencyMaxWrite` | Latency (max, write) | `microseconds` | *(derived)* |
| `latencyStddev` | Latency Std Dev | `microseconds` | Latency standard deviation of DOM owner. |
| `latencyStddevRead` | Latency standard deviation (read) | `microseconds` | *(derived)* |
| `latencyStddevUnmap` | Unmap Latency Std Dev | `microseconds` | Unmap latency standard deviation of DOM owner. |
| `latencyStddevWrite` | Latency standard deviation (write) | `microseconds` | *(derived)* |
| `metadataDispatchedCostRead` | Metadata dispatched cost (read) | `bibyte_per_second` | *(derived)* |
| `metadataDispatchedCostWrite` | Metadata dispatched cost (write) | `bibyte_per_second` | *(derived)* |
| `metadataQueueDepthRead` | Metadata queue depth (read) |  | *(derived)* |
| `metadataQueueDepthWrite` | Metadata queue depth (write) |  | *(derived)* |
| `namespaceDispatchedCostRead` | Namespace dispatched cost (read) | `bibyte_per_second` | *(derived)* |
| `namespaceDispatchedCostWrite` | Namespace dispatched cost (write) | `bibyte_per_second` | *(derived)* |
| `namespaceQueueDepthRead` | Namespace queue depth (read) |  | *(derived)* |
| `namespaceQueueDepthWrite` | Namespace queue depth (write) |  | *(derived)* |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oioRead` | Outstanding IO (read) |  | *(derived)* |
| `oioRecoveryWrite` | Outstanding IO recovery (write) |  | *(derived)* |
| `oioResyncRead` | Outstanding IO resync (read) |  | *(derived)* |
| `oioWrite` | Outstanding IO (write) |  | *(derived)* |
| `rateCompmgrOpsBadParam` | Compmgr ops bad param (rate) |  | *(derived)* |
| `rateCompmgrOpsChecksumMismatch` | Compmgr ops checksum mismatch (rate) |  | *(derived)* |
| `rateCompmgrOpsIoError` | Compmgr ops IO error (rate) |  | *(derived)* |
| `rateCompmgrOpsLimitExceed` | Compmgr ops limit exceed (rate) |  | *(derived)* |
| `rateCompmgrOpsNoConnect` | Compmgr ops no connect (rate) |  | *(derived)* |
| `rateCompmgrOpsNoMem` | Compmgr ops no mem (rate) |  | *(derived)* |
| `rateCompmgrOpsNoSpace` | Compmgr ops no space (rate) |  | *(derived)* |
| `rateCompmgrOpsNotSupported` | Compmgr ops not supported (rate) |  | *(derived)* |
| `rateCompmgrOpsRetry` | Compmgr ops retry (rate) |  | *(derived)* |
| `rateOtherCompmgrOpsFailure` | Other compmgr ops failure (rate) |  | *(derived)* |
| `readCongestion` | Read Congestions |  | Read congestions of IOs generated by DOM owner. |
| `readCount` | Read count |  | *(derived)* |
| `recUnmapCongestion` | Recovery unmap congestion |  | *(derived)* |
| `recUnmapCount` | Recovery unmap count |  | *(derived)* |
| `recWriteCongestion` | Recovery write congestion |  | *(derived)* |
| `recWriteCount` | Recovery write count |  | *(derived)* |
| `regulatorIopsRead` | Regulator IOPS (read) | `io_operations_per_second` | *(derived)* |
| `regulatorIopsWrite` | Regulator IOPS (write) | `io_operations_per_second` | *(derived)* |
| `resyncDispatchedCostRead` | Resync dispatched cost (read) | `bibyte_per_second` | *(derived)* |
| `resyncDispatchedCostWrite` | Resync dispatched cost (write) | `bibyte_per_second` | *(derived)* |
| `resyncQueueDepthRead` | Resync queue depth (read) |  | *(derived)* |
| `resyncQueueDepthWrite` | Resync queue depth (write) |  | *(derived)* |
| `resyncReadCongestion` | Resync read congestion |  | *(derived)* |
| `resyncReadCount` | Resync read count |  | *(derived)* |
| `sharedCongestion` | Shared congestion |  | *(derived)* |
| `throughput` | Throughput | `bibyte_per_second` | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputRecUnmap` | Recovery Unmap Throughput | `bibyte_per_second` | Total recovery trim/unmap throughput going to disk groups on this host. |
| `throughputRecWrite` | Recovery Write Throughput | `bibyte_per_second` | vSAN cluster recovery write throughput in the perspective of vSAN backend. |
| `throughputUnmap` | Unmap Throughput | `bibyte_per_second` | vSAN host throughput of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `tputResyncRead` | Resync Read Throughput | `bibyte_per_second` | vSAN cluster read throughput of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `tputServiceVMRead` | Throughput service VM (read) | `bibyte_per_second` | *(derived)* |
| `tputServiceVMWrite` | Throughput service VM (write) | `bibyte_per_second` | *(derived)* |
| `unmapCongestion` | Unmap congestion |  | *(derived)* |
| `unmapCount` | Unmap count |  | *(derived)* |
| `vmdiskDispatchedCostRead` | VM disk dispatched cost (read) | `bibyte_per_second` | *(derived)* |
| `vmdiskDispatchedCostWrite` | VM disk dispatched cost (write) | `bibyte_per_second` | *(derived)* |
| `vmdiskQueueDepthRead` | VM disk queue depth (read) |  | *(derived)* |
| `vmdiskQueueDepthWrite` | VM disk queue depth (write) |  | *(derived)* |
| `writeCongestion` | Write Congestions |  | Write congestions of IOs generated by DOM owner. |
| `writeCount` | Write count |  | *(derived)* |

### Host Domowner — `VsanHostDomowner`

perfsvc entity `host-domowner` · identified by `host_uuid` · 4 objects observed · 288 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgDeltaCreationDomActiveLatency` | Delta creation DOM active latency (average) | `seconds` | *(derived)* |
| `avgDeltaCreationDomCreationLatency` | Delta creation DOM creation latency (average) | `seconds` | *(derived)* |
| `avgResyncParallelism` | Resync parallelism (average) |  | *(derived)* |
| `congestion` | Congestions |  | Congestions of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `deltaLeafGTEs` | Delta leaf gt es |  | *(derived)* |
| `deltaSourceChanges` | Delta source changes |  | *(derived)* |
| `ecCachedWriteCount` | Ec cached write count |  | *(derived)* |
| `ecCachedWriteHits` | Ec cached write hits |  | *(derived)* |
| `ecFswCount` | Ec fsw count |  | *(derived)* |
| `ecStridedWriteCount` | Ec strided write count |  | *(derived)* |
| `ecStridedWriteHits` | Ec strided write hits |  | *(derived)* |
| `ecWriteCount` | Ec write count |  | *(derived)* |
| `highOIOAvgDurationMs` | High outstanding IO avg duration ms | `milliseconds` | *(derived)* |
| `highOIOAvgDurationMsRead` | High outstanding IO avg duration ms (read) | `milliseconds` | *(derived)* |
| `highOIOAvgDurationMsWrite` | High outstanding IO avg duration ms (write) | `milliseconds` | *(derived)* |
| `highOIOAvgIOCount` | High outstanding IO avg IO count |  | *(derived)* |
| `highOIOAvgIOCountRead` | High outstanding IO avg IO count (read) |  | *(derived)* |
| `highOIOAvgIOCountWrite` | High outstanding IO avg IO count (write) |  | *(derived)* |
| `highOIOAvgOIO` | High outstanding IO avg outstanding IO |  | *(derived)* |
| `highOIOAvgOIORead` | High outstanding IO avg outstanding IO (read) |  | *(derived)* |
| `highOIOAvgOIOWrite` | High outstanding IO avg outstanding IO (write) |  | *(derived)* |
| `highOIOBytes` | High outstanding IO bytes | `byte` | *(derived)* |
| `highOIOBytesRead` | High outstanding IO bytes (read) | `byte` | *(derived)* |
| `highOIOBytesWrite` | High outstanding IO bytes (write) | `byte` | *(derived)* |
| `highOIOCount` | High outstanding IO count |  | *(derived)* |
| `highOIOCountPercent` | High outstanding IO count percent | `percent` | *(derived)* |
| `highOIOCountPercentRead` | High outstanding IO count percent (read) |  | *(derived)* |
| `highOIOCountPercentWrite` | High outstanding IO count percent (write) |  | *(derived)* |
| `highOIOCountRead` | High outstanding IO count (read) |  | *(derived)* |
| `highOIOCountWrite` | High outstanding IO count (write) |  | *(derived)* |
| `highOIODurationMs` | High outstanding IO duration ms | `milliseconds` | *(derived)* |
| `highOIODurationMsRead` | High outstanding IO duration ms (read) | `milliseconds` | *(derived)* |
| `highOIODurationMsWrite` | High outstanding IO duration ms (write) | `milliseconds` | *(derived)* |
| `highOIODurationPercent` | High outstanding IO duration percent | `percent` | *(derived)* |
| `highOIODurationPercentRead` | High outstanding IO duration percent (read) |  | *(derived)* |
| `highOIODurationPercentWrite` | High outstanding IO duration percent (write) |  | *(derived)* |
| `highOIONumTimes` | High outstanding IO num times |  | *(derived)* |
| `highOIONumTimesRead` | High outstanding IO num times (read) |  | *(derived)* |
| `highOIONumTimesWrite` | High outstanding IO num times (write) |  | *(derived)* |
| `highOIOThroughput` | High outstanding IO throughput | `bibyte_per_second` | *(derived)* |
| `highOIOThroughputRead` | High outstanding IO throughput (read) | `bibyte_per_second` | *(derived)* |
| `highOIOThroughputWrite` | High outstanding IO throughput (write) | `bibyte_per_second` | *(derived)* |
| `ioCount` | IO count |  | *(derived)* |
| `iops` | IOPS | `io_operations_per_second` | *(derived)* |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsRecUnmap` | Recovery Unmap IOPS | `io_operations_per_second` | IOPS of Recovery trim/unmap command going to disk groups on this host. |
| `iopsRecWrite` | Recovery Write IOPS | `io_operations_per_second` | vSAN cluster recovery write IOPS in the perspective of vSAN backend. |
| `iopsResyncRead` | Resync Read IOPS | `io_operations_per_second` | vSAN cluster read IOPS of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `iopsSegCleanerUnmap` | IOPS seg cleaner unmap | `io_operations_per_second` | *(derived)* |
| `iopsUnmap` | Unmap IOPS | `io_operations_per_second` | vSAN host IOPS of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvg` | Latency (average) | `microseconds` | *(derived)* |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgRecUnmap` | Recovery Unmap Latency | `microseconds` | Average trim/unmap latency going to disk groups on this host. |
| `latencyAvgRecWrite` | Recovery Write Latency | `microseconds` | vSAN cluster recovery write average latency in the perspective of vSAN backend. |
| `latencyAvgResyncRead` | Resync Read Latency | `microseconds` | Resync read latency of DOM owner. |
| `latencyAvgSegCleanerUnmap` | Latency avg seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyAvgServiceVMRead` | Latency avg service VM (read) | `microseconds` | *(derived)* |
| `latencyAvgServiceVMWrite` | Latency avg service VM (write) | `microseconds` | *(derived)* |
| `latencyAvgUnmap` | Unmap Latency | `microseconds` | vSAN host average latency of trim/unmap commands generated by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyMaxRead` | Latency (max, read) | `microseconds` | *(derived)* |
| `latencyMaxSegCleanerUnmap` | Latency max seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyMaxUnmap` | Latency max unmap | `microseconds` | *(derived)* |
| `latencyMaxWrite` | Latency (max, write) | `microseconds` | *(derived)* |
| `latencyStddev` | Latency Std Dev | `microseconds` | Latency standard deviation of DOM owner. |
| `latencyStddevRead` | Latency standard deviation (read) | `microseconds` | *(derived)* |
| `latencyStddevRecoveryWrite` | Latency standard deviation recovery (write) | `microseconds` | *(derived)* |
| `latencyStddevResyncRead` | Latency standard deviation resync (read) | `microseconds` | *(derived)* |
| `latencyStddevSegCleanerUnmap` | Latency standard deviation seg cleaner unmap | `microseconds` | *(derived)* |
| `latencyStddevUnmap` | Unmap Latency Std Dev | `microseconds` | Unmap latency standard deviation of DOM owner. |
| `latencyStddevWrite` | Latency standard deviation (write) | `microseconds` | *(derived)* |
| `leafGTEs` | Leaf gt es |  | *(derived)* |
| `netSchedAvgCompRecoveryWriteDelayMs` | Net sched avg comp recovery write delay ms | `milliseconds` | *(derived)* |
| `netSchedAvgCompResyncReadDelayMs` | Net sched avg comp resync read delay ms | `milliseconds` | *(derived)* |
| `netSchedAvgOwnerRecoveryWriteDelayMs` | Net sched avg owner recovery write delay ms | `milliseconds` | *(derived)* |
| `netSchedAvgOwnerResyncReadDelayMs` | Net sched avg owner resync read delay ms | `milliseconds` | *(derived)* |
| `netSchedBWDiscoveredPerDiscoverySession` | Net sched bw discovered per discovery session | `bibyte_per_second` | *(derived)* |
| `netSchedBWDiscoveryActions` | Net sched bw discovery actions |  | *(derived)* |
| `netSchedBWDiscoveryAvgIntervalsUs` | Net sched bw discovery avg intervals us | `microseconds` | *(derived)* |
| `netSchedBWDiscoverySessions` | Net sched bw discovery sessions |  | *(derived)* |
| `netSchedBWDiscoveryStopsDueToGainsFromGuestPct` | Net sched bw discovery stops due to gains from guest percent | `percent` | *(derived)* |
| `netSchedBWDiscoveryStopsDueToHighLatencyPct` | Net sched bw discovery stops due to high latency percent | `percent` | *(derived)* |
| `netSchedBWDiscoveryStopsDueToLowUtilizationPct` | Net sched bw discovery stops due to low utilization percent | `percent` | *(derived)* |
| `netSchedBWDiscoveryUtilizationPct` | Net sched bw discovery utilization percent | `percent` | *(derived)* |
| `netSchedBWReallocatedPerReallocationSession` | Net sched bw reallocated per reallocation session | `bibyte_per_second` | *(derived)* |
| `netSchedBWReallocationActions` | Net sched bw reallocation actions |  | *(derived)* |
| `netSchedBWReallocationAvgIntervalsUs` | Net sched bw reallocation avg intervals us | `microseconds` | *(derived)* |
| `netSchedBWReallocationSessions` | Net sched bw reallocation sessions |  | *(derived)* |
| `netSchedBWReallocationStopsDueToHighSharePct` | Net sched bw reallocation stops due to high share percent | `percent` | *(derived)* |
| `netSchedBWReallocationStopsDueToLowUtilizationPct` | Net sched bw reallocation stops due to low utilization percent | `percent` | *(derived)* |
| `netSchedBWReallocationUtilizationRatio` | Net sched bw reallocation utilization ratio | `percent` | *(derived)* |
| `netSchedBWReallocationUtilizationRatioAbove` | Net sched bw reallocation utilization ratio above |  | *(derived)* |
| `netSchedBWReallocationUtilizationRatioBelow` | Net sched bw reallocation utilization ratio below |  | *(derived)* |
| `netSchedBandwidthDiscoveryBps` | Net sched bandwidth discovery bps |  | *(derived)* |
| `netSchedGuestIopsDecreasePerDiscoverySession` | Net sched guest IOPS decrease per discovery session | `io_operations_per_second` | *(derived)* |
| `netSchedGuestIopsIncreasePerReallocationSession` | Net sched guest IOPS increase per reallocation session | `io_operations_per_second` | *(derived)* |
| `netSchedLatencyIncreaseFromResyncPerDiscoverySessionPct` | Net sched latency increase from resync per discovery session percent | `percent` | *(derived)* |
| `netSchedResyncGainsFromGuestCount` | Net sched resync gains from guest count |  | *(derived)* |
| `netSchedResyncIopsDecreasePerReallocationSession` | Net sched resync IOPS decrease per reallocation session | `io_operations_per_second` | *(derived)* |
| `netSchedResyncIopsIncreasePerDiscoverySession` | Net sched resync IOPS increase per discovery session | `io_operations_per_second` | *(derived)* |
| `netSchedUnderUtilCount` | Net sched under utilization count |  | *(derived)* |
| `netSchedUnderUtilGuestBps` | Net sched under utilization guest bps |  | *(derived)* |
| `netSchedUnderUtilTtlBps` | Net sched under utilization ttl bps |  | *(derived)* |
| `numBlockedDeltaToBaseResyncJobs` | Num blocked delta to base resync jobs |  | *(derived)* |
| `numBlockedFullResyncJobs` | Num blocked full resync jobs |  | *(derived)* |
| `numBlockedPriorityResyncJobs` | Num blocked priority resync jobs |  | *(derived)* |
| `numBlockedResyncJobs` | Num blocked resync jobs |  | *(derived)* |
| `numBlockedSharedResyncJobs` | Num blocked shared resync jobs |  | *(derived)* |
| `numBlockedSiblingToDeltaResyncJobs` | Num blocked sibling to delta resync jobs |  | *(derived)* |
| `numCompleteDeltaToBaseResyncOps` | Num complete delta to base resync ops |  | *(derived)* |
| `numCompleteFullResyncOps` | Num complete full resync ops |  | *(derived)* |
| `numCompleteResyncOps` | Num complete resync ops |  | *(derived)* |
| `numCompleteResyncRwrBatches` | Num complete resync rwr batches |  | *(derived)* |
| `numCompleteRwrOps` | Num complete rwr ops |  | *(derived)* |
| `numCompleteSiblingToDeltaResyncOps` | Num complete sibling to delta resync ops |  | *(derived)* |
| `numInflightDedupResyncJobs` | Num inflight dedup resync jobs |  | *(derived)* |
| `numInflightPriorityResyncJobs` | Num inflight priority resync jobs |  | *(derived)* |
| `numInflightSharedResyncJobs` | Num inflight shared resync jobs |  | *(derived)* |
| `numNetSchedCompIops` | Num net sched comp IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompIopsLimit` | Num net sched comp IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompRecoveryWriteIops` | Num net sched comp recovery write IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompRecoveryWriteIopsLimit` | Num net sched comp recovery write IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompRecoveryWriteTpThrottled` | Num net sched comp recovery write tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedCompResyncReadIops` | Num net sched comp resync read IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompResyncReadIopsLimit` | Num net sched comp resync read IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedCompResyncReadTpThrottled` | Num net sched comp resync read tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedCompTpThrottled` | Num net sched comp tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedControllerActivations` | Num net sched controller activations |  | *(derived)* |
| `numNetSchedControllerIopsLimit` | Num net sched controller IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedGuestLTLatUs` | Num net sched guest lt latency us |  | *(derived)* |
| `numNetSchedHighBand` | Num net sched high band |  | *(derived)* |
| `numNetSchedHighBandHighShare` | Num net sched high band high share |  | *(derived)* |
| `numNetSchedHighBandLowLimit` | Num net sched high band low limit |  | *(derived)* |
| `numNetSchedHighBandSec` | Num net sched high band sec | `seconds` | *(derived)* |
| `numNetSchedHighToLowBand` | Num net sched high to low band |  | *(derived)* |
| `numNetSchedHighToMidBand` | Num net sched high to mid band |  | *(derived)* |
| `numNetSchedLowBand` | Num net sched low band |  | *(derived)* |
| `numNetSchedLowBandHighLimit` | Num net sched low band high limit |  | *(derived)* |
| `numNetSchedLowBandSec` | Num net sched low band sec | `seconds` | *(derived)* |
| `numNetSchedLowBandThreshUs` | Num net sched low band thresh us |  | *(derived)* |
| `numNetSchedLowToHighBand` | Num net sched low to high band |  | *(derived)* |
| `numNetSchedLowToMidBand` | Num net sched low to mid band |  | *(derived)* |
| `numNetSchedMidBand` | Num net sched mid band |  | *(derived)* |
| `numNetSchedMidBandHighLimit` | Num net sched mid band high limit |  | *(derived)* |
| `numNetSchedMidBandLowShare` | Num net sched mid band low share |  | *(derived)* |
| `numNetSchedMidBandSec` | Num net sched mid band sec | `seconds` | *(derived)* |
| `numNetSchedMidToHighBand` | Num net sched mid to high band |  | *(derived)* |
| `numNetSchedMidToLowBand` | Num net sched mid to low band |  | *(derived)* |
| `numNetSchedOwnerIops` | Num net sched owner IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerIopsLimit` | Num net sched owner IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerRecoveryWriteIops` | Num net sched owner recovery write IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerRecoveryWriteIopsLimit` | Num net sched owner recovery write IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerRecoveryWriteTpThrottled` | Num net sched owner recovery write tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedOwnerResyncReadIops` | Num net sched owner resync read IOPS | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerResyncReadIopsLimit` | Num net sched owner resync read IOPS limit | `io_operations_per_second` | *(derived)* |
| `numNetSchedOwnerResyncReadTpThrottled` | Num net sched owner resync read tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedOwnerTpThrottled` | Num net sched owner tp throttled | `bibyte_per_second` | *(derived)* |
| `numNetSchedRecoveryWriteTpThrottled` | Num net sched recovery write tp throttled |  | *(derived)* |
| `numNetSchedResyncReadTpThrottled` | Num net sched resync read tp throttled |  | *(derived)* |
| `numNetSchedResyncTotalSharePercent` | Num net sched resync total share percent | `percent` | *(derived)* |
| `numNetSchedRollingAvgLatUs` | Num net sched rolling avg latency us | `microseconds` | *(derived)* |
| `numNetSchedSeenNonResyncTpBps` | Num net sched seen non resync tp bps | `bibyte_per_second` | *(derived)* |
| `numNetSchedSeenResyncTpBps` | Num net sched seen resync tp bps | `bibyte_per_second` | *(derived)* |
| `numNetSchedSeenTotalTpBps` | Num net sched seen total tp bps | `bibyte_per_second` | *(derived)* |
| `numOio` | Num outstanding IO |  | *(derived)* |
| `numPendingDecomResyncJobs` | Num pending decom resync jobs |  | *(derived)* |
| `numPendingDedupResyncJobs` | Num pending dedup resync jobs |  | *(derived)* |
| `numPendingDeltaToBaseResyncJobs` | Num pending delta to base resync jobs |  | *(derived)* |
| `numPendingFullResyncJobs` | Num pending full resync jobs |  | *(derived)* |
| `numPendingResyncJobs` | Num pending resync jobs |  | *(derived)* |
| `numPendingSiblingToDeltaResyncJobs` | Num pending sibling to delta resync jobs |  | *(derived)* |
| `numRunningDeltaToBaseResyncJobs` | Num running delta to base resync jobs |  | *(derived)* |
| `numRunningFullResyncJobs` | Num running full resync jobs |  | *(derived)* |
| `numRunningResyncJobs` | Num running resync jobs |  | *(derived)* |
| `numRunningSiblingToDeltaResyncJobs` | Num running sibling to delta resync jobs |  | *(derived)* |
| `numSuspendedDedupResyncJobs` | Num suspended dedup resync jobs |  | *(derived)* |
| `numSuspendedDeltaToBaseResyncJobs` | Num suspended delta to base resync jobs |  | *(derived)* |
| `numSuspendedFullResyncJobs` | Num suspended full resync jobs |  | *(derived)* |
| `numSuspendedPriorityResyncJobs` | Num suspended priority resync jobs |  | *(derived)* |
| `numSuspendedResyncChangemaps` | Num suspended resync changemaps |  | *(derived)* |
| `numSuspendedResyncJobs` | Num suspended resync jobs |  | *(derived)* |
| `numSuspendedSharedResyncJobs` | Num suspended shared resync jobs |  | *(derived)* |
| `numSuspendedSiblingToDeltaResyncJobs` | Num suspended sibling to delta resync jobs |  | *(derived)* |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oioRead` | Outstanding IO (read) |  | *(derived)* |
| `oioRecoveryWrite` | Outstanding IO recovery (write) |  | *(derived)* |
| `oioResyncRead` | Outstanding IO resync (read) |  | *(derived)* |
| `oioWrite` | Outstanding IO (write) |  | *(derived)* |
| `owner2PCCommitLatencyAvgUs` | Owner2 pc commit latency avg us | `microseconds` | *(derived)* |
| `ownerECCacheHitMissRatio` | Owner ec cache hit miss ratio | `percent` | *(derived)* |
| `ownerECCacheNumCachedObjects` | Owner ec cache num cached objects |  | *(derived)* |
| `ownerECCacheNumFailedAllocs` | Owner ec cache num failed allocs |  | *(derived)* |
| `ownerECCacheNumSuccessAllocs` | Owner ec cache num success allocs |  | *(derived)* |
| `rateOtherOwnerOpsFailure` | Other owner ops failure (rate) |  | *(derived)* |
| `rateOwnerOpsBadParam` | Owner ops bad param (rate) |  | *(derived)* |
| `rateOwnerOpsChecksumMismatch` | Owner ops checksum mismatch (rate) |  | *(derived)* |
| `rateOwnerOpsIoError` | Owner ops IO error (rate) |  | *(derived)* |
| `rateOwnerOpsLimitExceed` | Owner ops limit exceed (rate) |  | *(derived)* |
| `rateOwnerOpsNoConnect` | Owner ops no connect (rate) |  | *(derived)* |
| `rateOwnerOpsNoMem` | Owner ops no mem (rate) |  | *(derived)* |
| `rateOwnerOpsNoSpace` | Owner ops no space (rate) |  | *(derived)* |
| `rateOwnerOpsNotSupported` | Owner ops not supported (rate) |  | *(derived)* |
| `rateOwnerOpsRetry` | Owner ops retry (rate) |  | *(derived)* |
| `readCongestion` | Read Congestions |  | Read congestions of IOs generated by DOM owner. |
| `readCount` | Read count |  | *(derived)* |
| `readECLeafOwnerMaxLatencyAvgUs` | Read ec leaf owner max latency avg us | `microseconds` | *(derived)* |
| `readECLeafOwnerMaxLatencyUs` | Read ec leaf owner max latency us | `microseconds` | *(derived)* |
| `readLeafOwnerIops` | Read leaf owner IOPS | `io_operations_per_second` | *(derived)* |
| `readLeafOwnerLatency` | Read leaf owner latency | `microseconds` | *(derived)* |
| `readLeafOwnerLatencyLocal` | Read leaf owner latency local | `microseconds` | *(derived)* |
| `readLeafOwnerLatencyRemote` | Read leaf owner latency remote | `microseconds` | *(derived)* |
| `readLeafOwnerMaxLatencyAvgUs` | Read leaf owner max latency avg us | `microseconds` | *(derived)* |
| `readLeafOwnerRetriesPerOp` | Read leaf owner retries per op |  | *(derived)* |
| `readLeafOwnerThroughput` | Read leaf owner throughput | `bibyte_per_second` | *(derived)* |
| `readOwnerRetriesPerOp` | Read owner retries per op |  | *(derived)* |
| `recUnmapCount` | Recovery unmap count |  | *(derived)* |
| `recWriteCount` | Recovery write count |  | *(derived)* |
| `recoveryUnmapCongestion` | Recovery unmap congestion |  | *(derived)* |
| `recoveryUnmapLeafOwnerLatency` | Recovery unmap leaf owner latency | `microseconds` | *(derived)* |
| `recoveryWriteCongestion` | Resync Read Congestions |  | Resync read congestions of IOs generated by DOM owner. |
| `recoveryWriteLeafOwnerLatency` | Recovery write leaf owner latency | `microseconds` | *(derived)* |
| `recoveryWriteLeafOwnerLatencyLocal` | Recovery write leaf owner latency local | `microseconds` | *(derived)* |
| `recoveryWriteLeafOwnerLatencyRemote` | Recovery write leaf owner latency remote | `microseconds` | *(derived)* |
| `resyncReadCount` | Resync read count |  | *(derived)* |
| `resyncReadLeafOwnerLatency` | Resync read leaf owner latency | `microseconds` | *(derived)* |
| `resyncReadLeafOwnerLatencyLocal` | Resync read leaf owner latency local | `microseconds` | *(derived)* |
| `resyncReadLeafOwnerLatencyRemote` | Resync read leaf owner latency remote | `microseconds` | *(derived)* |
| `resyncsEndedAsDeltaToBase` | Resyncs ended as delta to base |  | *(derived)* |
| `resyncsStartedAsDeltaToBase` | Resyncs started as delta to base |  | *(derived)* |
| `segCleanerUnmapCongestion` | Seg cleaner unmap congestion |  | *(derived)* |
| `segCleanerUnmapLeafOwnerLatency` | Seg cleaner unmap leaf owner latency | `microseconds` | *(derived)* |
| `segCleanerUnmapLeafOwnerMaxLatencyAvgUs` | Seg cleaner unmap leaf owner max latency avg us | `microseconds` | *(derived)* |
| `serverSwitchAvglatency` | Server switch average latency | `microseconds` | *(derived)* |
| `serverSwitchCount` | Server switch count |  | *(derived)* |
| `serverSwitchLatencyMaxUs` | Server switch latency max us | `microseconds` | *(derived)* |
| `serverSwitchlatencyStddev` | Server switchlatency standard deviation | `microseconds` | *(derived)* |
| `throughput` | Throughput | `bibyte_per_second` | *(derived)* |
| `throughputSegCleanerUnmap` | Throughput seg cleaner unmap | `bibyte_per_second` | *(derived)* |
| `totalDeltaCreationDomActiveLatency` | Delta creation DOM active latency (total) | `microseconds` | *(derived)* |
| `totalDeltaCreationDomCreationLatency` | Delta creation DOM creation latency (total) | `microseconds` | *(derived)* |
| `totalDeltasCreatedCount` | Deltas created count (total) |  | *(derived)* |
| `tputRead` | Read Throughput | `bibyte_per_second` | vSAN host read throughput without resync traffic in the perspective of DOM owner. |
| `tputRecUnmap` | Throughput recovery unmap | `bibyte_per_second` | *(derived)* |
| `tputRecWrite` | Recovery Write Throughput | `bibyte_per_second` | vSAN host recovery write throughput in the perspective of DOM owner. |
| `tputResyncRead` | Resync Read Throughput | `bibyte_per_second` | vSAN cluster read throughput of resync traffic, including policy change, repair, maintenance mode / evacuation and rebalance from resyncing objects in the perspective of vSAN backend. |
| `tputServiceVMRead` | Throughput service VM (read) | `bibyte_per_second` | *(derived)* |
| `tputServiceVMWrite` | Throughput service VM (write) | `bibyte_per_second` | *(derived)* |
| `tputUnmap` | Throughput unmap | `bibyte_per_second` | *(derived)* |
| `tputWrite` | Write Throughput | `bibyte_per_second` | vSAN host write throughput in the perspective of DOM owner. |
| `twoPCBatchCommitBlockedByGuestIOPS` | Two pc batch commit blocked by guest IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitBlockedByOtherIOPS` | Two pc batch commit blocked by other IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitBlockedByResyncIOPS` | Two pc batch commit blocked by resync IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitBlockedBySyncIOPS` | Two pc batch commit blocked by sync IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitGuestIOPS` | Two pc batch commit guest IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitOtherIOPS` | Two pc batch commit other IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitResyncIOPS` | Two pc batch commit resync IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCBatchCommitSyncIOPS` | Two pc batch commit sync IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCCommitCount` | Two pc commit count |  | *(derived)* |
| `twoPCCommitSize` | Two pc commit size |  | *(derived)* |
| `twoPCPrepareLimitRetryGuestAvgTimeMs` | Two pc prepare limit retry guest avg time ms | `milliseconds` | *(derived)* |
| `twoPCPrepareLimitRetryGuestIOPS` | Two pc prepare limit retry guest IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCPrepareLimitRetryOtherAvgTimeMs` | Two pc prepare limit retry other avg time ms | `milliseconds` | *(derived)* |
| `twoPCPrepareLimitRetryOtherIOPS` | Two pc prepare limit retry other IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCPrepareLimitRetryResyncAvgTimeMs` | Two pc prepare limit retry resync avg time ms | `milliseconds` | *(derived)* |
| `twoPCPrepareLimitRetryResyncIOPS` | Two pc prepare limit retry resync IOPS | `io_operations_per_second` | *(derived)* |
| `twoPCPrepareRetryCount` | Two pc prepare retry count |  | *(derived)* |
| `twoPCReservedLSNExhaustedCount` | Two pc reserved lsn exhausted count |  | *(derived)* |
| `twoPCReservedLSNUnusedCount` | Two pc reserved lsn unused count |  | *(derived)* |
| `twoPCReservedLSNUsedCount` | Two pc reserved lsn used count |  | *(derived)* |
| `unmapCongestion` | Unmap congestion |  | *(derived)* |
| `unmapCount` | Unmap count |  | *(derived)* |
| `unmapECLeafOwnerMaxLatencyAvgUs` | Unmap ec leaf owner max latency avg us | `microseconds` | *(derived)* |
| `unmapECLeafOwnerMaxLatencyUs` | Unmap ec leaf owner max latency us | `microseconds` | *(derived)* |
| `unmapLeafOwnerLatency` | Unmap leaf owner latency | `microseconds` | *(derived)* |
| `unmapLeafOwnerMaxLatencyAvgUs` | Unmap leaf owner max latency avg us | `microseconds` | *(derived)* |
| `writeCongestion` | Write Congestions |  | Write congestions of IOs generated by DOM owner. |
| `writeCount` | Write count |  | *(derived)* |
| `writeECLeafOwnerMaxLatencyAvgUs` | Write ec leaf owner max latency avg us | `microseconds` | *(derived)* |
| `writeECLeafOwnerMaxLatencyUs` | Write ec leaf owner max latency us | `microseconds` | *(derived)* |
| `writeLeafOwnerIops` | Write leaf owner IOPS | `io_operations_per_second` | *(derived)* |
| `writeLeafOwnerLatency` | Write leaf owner latency | `microseconds` | *(derived)* |
| `writeLeafOwnerLatencyLocal` | Write leaf owner latency local | `microseconds` | *(derived)* |
| `writeLeafOwnerLatencyRemote` | Write leaf owner latency remote | `microseconds` | *(derived)* |
| `writeLeafOwnerMaxLatencyAvgUs` | Write leaf owner max latency avg us | `microseconds` | *(derived)* |
| `writeLeafOwnerRetriesPerOp` | Write leaf owner retries per op |  | *(derived)* |
| `writeLeafOwnerThroughput` | Write leaf owner throughput | `bibyte_per_second` | *(derived)* |
| `writeOwnerRetriesPerOp` | Write owner retries per op |  | *(derived)* |

### Host Vsansparse — `VsanHostVsansparse`

perfsvc entity `host-vsansparse` · identified by `host_uuid` · 4 objects observed · 21 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `cacheAllocFails` | Cache alloc fails |  | *(derived)* |
| `cacheEntries` | Cache entries |  | *(derived)* |
| `cacheEvictAttempts` | Cache evict attempts |  | *(derived)* |
| `cacheHitRate` | Cache Hit Rate |  | vSAN sparse host cache hit rate. |
| `cacheInserts` | Cache inserts |  | *(derived)* |
| `cacheLockContentions` | Cache lock contentions |  | *(derived)* |
| `cacheRemoves` | Cache removes |  | *(derived)* |
| `cacheUpdateLatency` | Cache update latency | `microseconds` | *(derived)* |
| `iopsGwe` | GWE IOPS | `io_operations_per_second` | vSAN sparse host GWE iops. |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsRmw` | RMW IOPS | `io_operations_per_second` | vSAN sparse host RMW iops. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `iopsWriteConflicts` | Write Conficts IOPS | `io_operations_per_second` | vSAN sparse host write conficts iops. |
| `latencyCacheLookup` | Cache Lookup Latency | `microseconds` | vSAN sparse host cache lookup latency. |
| `latencyGwe` | GWE Latency | `microseconds` | vSAN sparse host GWE latency. |
| `latencyRead` | vSAN Layer Read Latency | `microseconds` | Disk vSAN layer read latency. |
| `latencyWrite` | vSAN Layer Write Latency | `microseconds` | Disk vSAN layer write latency. |
| `lruLockContentions` | Lru lock contentions |  | *(derived)* |
| `readsToLayer` | Reads to layer |  | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |

### Host Zdom Top Stats — `VsanHostZdomTopStats`

perfsvc entity `host-zdom-top-stats` · identified by `host_uuid` · 4 objects observed · 19 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `ioCount` | IO count |  | *(derived)* |
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsUnmap` | Unmap IOPS | `io_operations_per_second` | vSAN host IOPS of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyAvgRead` | Read Latency | `microseconds` | Average read latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `latencyAvgUnmap` | Unmap Latency | `microseconds` | vSAN host average latency of trim/unmap commands generated by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `latencyAvgWrite` | Write Latency | `microseconds` | Average write latency of IOs generated by all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oio` | Outstanding IO |  | Outstanding IO from all vSAN clients in the cluster, such as virtual machines, stats object, etc. |
| `oioRead` | Outstanding IO (read) |  | *(derived)* |
| `oioWrite` | Outstanding IO (write) |  | *(derived)* |
| `readCount` | Read count |  | *(derived)* |
| `readLatencyMaxUs` | Read latency max us | `microseconds` | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputUnmap` | Unmap Throughput | `bibyte_per_second` | vSAN host throughput of trim/unmap commands consumed by all vSAN clients in the host, such as virtual machines, stats object, etc. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `unmapCount` | Unmap count |  | *(derived)* |
| `unmapLatencyMaxUs` | Unmap latency max us | `microseconds` | *(derived)* |
| `writeCount` | Write count |  | *(derived)* |
| `writeLatencyMaxUs` | Write latency max us | `microseconds` | *(derived)* |

### vSAN RDT Network — `VsanRdtNet`

perfsvc entity `rdt-net` · identified by `host_uuid` · 4 objects observed · 1 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `checksumMismatchCount` | RDT Net Checksum Mismatch Count |  | RDT net checksum mismatch count. |

### vSAN RDT Latency — `VsanRdtLatency`

perfsvc entity `rdt-network-latency` · identified by `host_uuid` · 4 objects observed · 17 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgLatency` | RDT Network VNIC Average Latency | `microseconds` | RDT network vnic average latency for last 5 seconds. |
| `kaReset` | Keepalive reset |  | *(derived)* |
| `maxLatency` | RDT Network Cluster Max Latency | `microseconds` | RDT network cluster max latency for last 5 seconds. |
| `minLatency` | RDT Network Cluster Min Latency | `microseconds` | RDT network cluster min latency for last 5 seconds. |
| `numReadyDelay` | Num ready delay |  | *(derived)* |
| `rxSbSpaceAvg` | RDT Network Socket Average Inbound Bytes | `byte` | RDT network socket average inbound bytes for last 5 seconds. |
| `rxSbSpaceMax` | RDT Network Socket Max Inbound Bytes | `byte` | RDT network socket max inbound bytes for last 5 seconds. |
| `rxSbSpaceMin` | RDT Network Socket Min Inbound Bytes | `byte` | RDT network socket min inbound bytes for last 5 seconds. |
| `txCtxQAvg` | RDT Network Average Outbound Context Bytes | `byte` | RDT network average outbound context bytes for last 5 seconds. |
| `txCtxQMax` | RDT Network Max Outbound Context Bytes | `byte` | RDT network max outbound context bytes for last 5 seconds. |
| `txCtxQMin` | RDT Network Min Outbound Context Bytes | `byte` | RDT network min outbound context bytes for last 5 seconds. |
| `txQLatAvg` | RDT Network Average Outbound Queueing Latency | `microseconds` | RDT network average outbound queueing latency for last 5 seconds. |
| `txQLatMax` | RDT Network Max Outbound Queueing Latency | `microseconds` | RDT Network Max outbound queueing latency for last 5 seconds. |
| `txQLatMin` | RDT Network Min Outbound Queueing Latency | `microseconds` | RDT network min outbound queueing latency for last 5 seconds. |
| `txSbSpaceAvg` | RDT Network Socket Average Outbound Bytes | `byte` | RDT network socket average outbound bytes for last 5 seconds. |
| `txSbSpaceMax` | RDT Network Socket Max Outbound Bytes | `byte` | RDT network socket max outbound bytes for last 5 seconds. |
| `txSbSpaceMin` | RDT Network Socket Min Outbound Bytes | `byte` | RDT network socket min outbound bytes for last 5 seconds. |

### vSAN System Memory — `VsanSystemMemory`

perfsvc entity `system-mem` · identified by `host_uuid` · 4 objects observed · 3 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `overcommitRatio` | Over Commit Ratio | `percent` | Over commit ratio. |
| `pctMemUsed` | Used Memory Percentage | `percent` | System used memory percentage. |
| `totalMbMemUsed` | Total Memory Used | `megabyte` | System total memory used. |

### vSAN Virtual Disk — `VsanVirtualDisk`

perfsvc entity `virtual-disk` · identified by `vdisk_uuid` · 60 objects observed · 7 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `NIOPS` | Normalized IOPS | `io_operations_per_second` | This shows IOPS that are represented using a weighted size of 32KB by default. This means that a 64KB read or write operation represents 2 normalized IO. The weighted size is a configurable parameter. |
| `NIOPSDelayed` | Delayed Normalized IOPS | `io_operations_per_second` | This is the IOPS for normalized IOs that are delayed. |
| `NIOPSRead` | Niops (read) | `io_operations_per_second` | *(derived)* |
| `NIOPSReadDelayed` | Niops read delayed | `io_operations_per_second` | *(derived)* |
| `NIOPSWrite` | Niops (write) | `io_operations_per_second` | *(derived)* |
| `NIOPSWriteDelayed` | Niops write delayed | `io_operations_per_second` | *(derived)* |
| `iopsLimit` | Normalized IOPS Limit | `io_operations_per_second` | The applied IOPS limit. |

### vSAN Virtual Machine — `VsanVirtualMachine`

perfsvc entity `virtual-machine` · identified by `vm_uuid` · 30 objects observed · 8 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyRead` | vSAN Layer Read Latency | `microseconds` | Disk vSAN layer read latency. |
| `latencyWrite` | vSAN Layer Write Latency | `microseconds` | Disk vSAN layer write latency. |
| `readCount` | Read count |  | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `writeCount` | Write count |  | *(derived)* |

### vSAN VMkernel RDT Latency — `VsanVnicRdtLatency`

perfsvc entity `vnic-rdt-network-latency` · identified by `host_uuid`, `vmknic` · 4 objects observed · 17 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgLatency` | RDT Network VNIC Average Latency | `microseconds` | RDT network vnic average latency for last 5 seconds. |
| `kaReset` | Keepalive reset |  | *(derived)* |
| `maxLatency` | RDT Network Cluster Max Latency | `microseconds` | RDT network cluster max latency for last 5 seconds. |
| `minLatency` | RDT Network Cluster Min Latency | `microseconds` | RDT network cluster min latency for last 5 seconds. |
| `numReadyDelay` | Num ready delay |  | *(derived)* |
| `rxSbSpaceAvg` | RDT Network Socket Average Inbound Bytes | `byte` | RDT network socket average inbound bytes for last 5 seconds. |
| `rxSbSpaceMax` | RDT Network Socket Max Inbound Bytes | `byte` | RDT network socket max inbound bytes for last 5 seconds. |
| `rxSbSpaceMin` | RDT Network Socket Min Inbound Bytes | `byte` | RDT network socket min inbound bytes for last 5 seconds. |
| `txCtxQAvg` | RDT Network Average Outbound Context Bytes | `byte` | RDT network average outbound context bytes for last 5 seconds. |
| `txCtxQMax` | RDT Network Max Outbound Context Bytes | `byte` | RDT network max outbound context bytes for last 5 seconds. |
| `txCtxQMin` | RDT Network Min Outbound Context Bytes | `byte` | RDT network min outbound context bytes for last 5 seconds. |
| `txQLatAvg` | RDT Network Average Outbound Queueing Latency | `microseconds` | RDT network average outbound queueing latency for last 5 seconds. |
| `txQLatMax` | RDT Network Max Outbound Queueing Latency | `microseconds` | RDT Network Max outbound queueing latency for last 5 seconds. |
| `txQLatMin` | RDT Network Min Outbound Queueing Latency | `microseconds` | RDT network min outbound queueing latency for last 5 seconds. |
| `txSbSpaceAvg` | RDT Network Socket Average Outbound Bytes | `byte` | RDT network socket average outbound bytes for last 5 seconds. |
| `txSbSpaceMax` | RDT Network Socket Max Outbound Bytes | `byte` | RDT network socket max outbound bytes for last 5 seconds. |
| `txSbSpaceMin` | RDT Network Socket Min Outbound Bytes | `byte` | RDT network socket min outbound bytes for last 5 seconds. |

### Vsan Cluster Capacity — `VsanClusterCapacity`

perfsvc entity `vsan-cluster-capacity` · identified by `cluster_uuid` · 1 objects observed · 6 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `dedupRatio` | Space Efficiency Ratio |  | Space Efficiency Ratio is a metric indicating the efficiency of space efficiency. It is a percentage calculated by the capacity would be used without space efficiency divides the capacity used with space efficiency enabled. |
| `free` | Free Capacity |  | Free capacity in the vSAN cluster. |
| `savedByDedup` | Saved Capacity |  | How much physical capacity saved by space efficiency feature. |
| `total` | Total Capacity |  | Total capacity of the vSAN cluster. |
| `totalDpOverhead` | DP overhead (total) |  | *(derived)* |
| `used` | Used Capacity |  | Capacity already being consumed in the vSAN cluster. |

### vSAN CPU — `VsanCpu`

perfsvc entity `vsan-cpu` · identified by `host_uuid` · 4 objects observed · 7 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgRunPct` | Run percent (average) | `percent` | *(derived)* |
| `avgUsedPct` | Used percent (average) | `percent` | *(derived)* |
| `maxRunPct` | Run percent (max) | `percent` | *(derived)* |
| `maxUsedPct` | Used percent (max) | `percent` | *(derived)* |
| `readyPct` | Percentage of Ready CPU Time | `percent` | Percentage of ready CPU time. |
| `runPct` | Percentage of Running CPU Time | `percent` | Percentage of running CPU time. |
| `usedPct` | Percentage of Used CPU Time | `percent` | Percentage of used CPU time |

### Vsan Dp Historical Stats — `VsanDpHistoricalStats`

perfsvc entity `vsan-dp-historical-stats` · identified by `cluster_uuid` · 1 objects observed · 1 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `totalSnapshotCapacity` | Used By Snapshots |  | Used By Snapshots. |

### Vsan Esa Disk Layer — `VsanEsaDiskLayer`

perfsvc entity `vsan-esa-disk-layer` · identified by `disk_uuid` · 7 objects observed · 38 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `avgLatReadCapacity` | vSAN Layer Average Read Latency of vSAN ESA Disk |  | vSAN layer average read latency of vSAN Express Storage Architecture disk. |
| `avgLatReadPerf` | Latency read perf (average) |  | *(derived)* |
| `avgLatUnmapCapacity` | Latency unmap capacity (average) |  | *(derived)* |
| `avgLatUnmapPerf` | Latency unmap perf (average) |  | *(derived)* |
| `avgLatWriteCapacity` | vSAN Layer Average Write Latency of vSAN ESA Disk |  | vSAN layer average write latency of vSAN Express Storage Architecture disk. |
| `avgLatWritePerf` | Latency write perf (average) |  | *(derived)* |
| `iopsReadCapacity` | vSAN Layer Read IOPS of vSAN ESA Disk | `io_operations_per_second` | vSAN layer read IOPS of vSAN Express Storage Architecture disk. |
| `iopsReadPerf` | IOPS read perf | `io_operations_per_second` | *(derived)* |
| `iopsUnmapCapacity` | IOPS unmap capacity | `io_operations_per_second` | *(derived)* |
| `iopsUnmapPerf` | IOPS unmap perf | `io_operations_per_second` | *(derived)* |
| `iopsWriteCapacity` | vSAN Layer Write IOPS of vSAN ESA Disk | `io_operations_per_second` | vSAN Layer Write IOPS of vSAN Express Storage Architecture Disk. |
| `iopsWritePerf` | IOPS write perf | `io_operations_per_second` | *(derived)* |
| `maxReadTimeCapacity` | Read time capacity (max) |  | *(derived)* |
| `maxReadTimePerf` | Read time perf (max) |  | *(derived)* |
| `maxUnmapTimeCapacity` | Unmap time capacity (max) |  | *(derived)* |
| `maxUnmapTimePerf` | Unmap time perf (max) |  | *(derived)* |
| `maxWriteTimeCapacity` | Write time capacity (max) |  | *(derived)* |
| `maxWriteTimePerf` | Write time perf (max) |  | *(derived)* |
| `minReadTimeCapacity` | Read time capacity (min) |  | *(derived)* |
| `minReadTimePerf` | Read time perf (min) |  | *(derived)* |
| `minUnmapTimeCapacity` | Unmap time capacity (min) |  | *(derived)* |
| `minUnmapTimePerf` | Unmap time perf (min) |  | *(derived)* |
| `minWriteTimeCapacity` | Write time capacity (min) |  | *(derived)* |
| `minWriteTimePerf` | Write time perf (min) |  | *(derived)* |
| `readCountCapacity` | Read count capacity |  | *(derived)* |
| `readCountPerf` | Read count perf |  | *(derived)* |
| `tputReadCapacity` | vSAN Layer Read Throughput of vSAN ESA Disk |  | vSAN layer read throughput of vSAN Express Storage Architecture disk. |
| `tputReadDiskCapacity` | Throughput read disk capacity |  | *(derived)* |
| `tputReadDiskPerf` | Throughput read disk perf |  | *(derived)* |
| `tputReadPerf` | Throughput read perf |  | *(derived)* |
| `tputUnmapCapacity` | Throughput unmap capacity |  | *(derived)* |
| `tputUnmapPerf` | Throughput unmap perf |  | *(derived)* |
| `tputWriteCapacity` | vSAN Layer Write Throughput of vSAN ESA Disk |  | vSAN layer write throughput of vSAN Express Storage Architecture disk. |
| `tputWritePerf` | Throughput write perf |  | *(derived)* |
| `unmapCountCapacity` | Unmap count capacity |  | *(derived)* |
| `unmapCountPerf` | Unmap count perf |  | *(derived)* |
| `writeCountCapacity` | Write count capacity |  | *(derived)* |
| `writeCountPerf` | Write count perf |  | *(derived)* |

### Vsan Esa Disk Scsifw — `VsanEsaDiskScsifw`

perfsvc entity `vsan-esa-disk-scsifw` · identified by `disk_uuid` · 7 objects observed · 16 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `ioCountDevRead` | IO count dev (read) |  | *(derived)* |
| `ioCountDevUnmap` | IO count dev unmap |  | *(derived)* |
| `ioCountDevWrite` | IO count dev (write) |  | *(derived)* |
| `iopsDevRead` | Physical-layer Read IOPS | `io_operations_per_second` | vSAN disk physical/firmware layer read IOPS. |
| `iopsDevUnmap` | IOPS dev unmap | `io_operations_per_second` | *(derived)* |
| `iopsDevWrite` | Physical-layer Write IOPS | `io_operations_per_second` | vSAN disk physical/firmware layer write IOPS. |
| `latencyDevDAvg` | Device Average Latency | `microseconds` | vSAN disk IO device latency (from HBA to backend storage). |
| `latencyDevGAvg` | Guest Average Latency | `microseconds` | vSAN disk Guest IO latency (total latency). |
| `latencyDevKAvg` | Latency dev k (average) | `microseconds` | *(derived)* |
| `latencyDevRead` | Physical-layer Read Latency | `microseconds` | vSAN disk physical/firmware layer read latency. |
| `latencyDevUnmap` | Latency dev unmap | `microseconds` | *(derived)* |
| `latencyDevWrite` | Physical-layer Write Latency | `microseconds` | vSAN disk physical/firmware layer write latency. |
| `outstandingCmdCount` | Outstanding cmd count |  | *(derived)* |
| `throughputDevRead` | Physical-layer Read Throughput | `bibyte_per_second` | vSAN disk physical/firmware layer read throughput. |
| `throughputDevUnmap` | Throughput dev unmap | `bibyte_per_second` | *(derived)* |
| `throughputDevWrite` | Physical-layer Write Throughput | `bibyte_per_second` | vSAN disk physical/firmware layer write throughput. |

### vSAN Host Network — `VsanHostNet`

perfsvc entity `vsan-host-net` · identified by `host_uuid` · 4 objects observed · 16 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `ioChainRxdrops` | IO chain RX drops |  | *(derived)* |
| `ioChainTxdrops` | IO chain TX drops |  | *(derived)* |
| `portRxDrops` | Inbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Inbound Packet Drop Rate. |
| `portRxpkts` | Port RX packets |  | *(derived)* |
| `portTxDrops` | Outbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Outbound Packet Drop Rate. |
| `portTxpkts` | Port TX packets |  | *(derived)* |
| `rxPackets` | Inbound Packets Per Second |  | VMkernel Network Adapter Inbound Packets Per Second. |
| `rxPacketsLossRate` | Inbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Inbound Packet Discard Rate. |
| `rxThroughput` | Throughput Inbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Inbound. |
| `tcpRxErrRate` | TCP RX errors (rate) |  | *(derived)* |
| `tcpRxPackets` | TCP Inbound Packets |  | VMkernel Network Adapter TCP inbound packets. |
| `tcpTxPackets` | TCP Outbound Packets |  | VMkernel Network Adapter TCP outbound packets. |
| `tcpTxRexmitRate` | TCP TX retransmit (rate) |  | *(derived)* |
| `txPackets` | Outbound Packets Per Second |  | VMkernel Network Adapter Outbound Packets Per Second. |
| `txPacketsLossRate` | Outbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Outbound Packet Discard Rate. |
| `txThroughput` | Throughput Outbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Outbound. |

### vSAN Memory — `VsanMemory`

perfsvc entity `vsan-memory` · identified by `host_uuid` · 4 objects observed · 50 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `clomdConsumedSize` | Clomd consumed size | `byte` | *(derived)* |
| `clomdMemAllocMax` | Clomd mem alloc (max) |  | *(derived)* |
| `clomdMemAllocMin` | Clomd mem alloc (min) |  | *(derived)* |
| `clomdReservedSize` | Clomd reserved size | `byte` | *(derived)* |
| `cmmdsTimeMachineConsumedSize` | CMMDS time machine consumed size | `byte` | *(derived)* |
| `cmmdsTimeMachineMemAllocMax` | CMMDS time machine mem alloc (max) |  | *(derived)* |
| `cmmdsTimeMachineMemAllocMin` | CMMDS time machine mem alloc (min) |  | *(derived)* |
| `cmmdsTimeMachineReservedSize` | CMMDS time machine reserved size | `byte` | *(derived)* |
| `cmmdsdConsumedSize` | Cmmdsd consumed size | `byte` | *(derived)* |
| `cmmdsdMemAllocMax` | Cmmdsd mem alloc (max) |  | *(derived)* |
| `cmmdsdMemAllocMin` | Cmmdsd mem alloc (min) |  | *(derived)* |
| `cmmdsdReservedSize` | Cmmdsd reserved size | `byte` | *(derived)* |
| `epdConsumedSize` | Epd consumed size | `byte` | *(derived)* |
| `epdMemAllocMax` | Epd mem alloc (max) |  | *(derived)* |
| `epdMemAllocMin` | Epd mem alloc (min) |  | *(derived)* |
| `epdReservedSize` | Epd reserved size | `byte` | *(derived)* |
| `kernelConsumedSize` | Kernel consumed size |  | *(derived)* |
| `kernelReservedSize` | Kernel Reserved Memory Size | `byte` | Kernel Reserved Memory Size. |
| `osfsdConsumedSize` | Osfsd consumed size | `byte` | *(derived)* |
| `osfsdMemAllocMax` | Osfsd mem alloc (max) |  | *(derived)* |
| `osfsdMemAllocMin` | Osfsd mem alloc (min) |  | *(derived)* |
| `osfsdReservedSize` | Osfsd reserved size | `byte` | *(derived)* |
| `uwConsumedSize` | Uw consumed size | `byte` | *(derived)* |
| `uwMemAllocMax` | Uw mem alloc (max) |  | *(derived)* |
| `uwMemAllocMin` | Uw mem alloc (min) |  | *(derived)* |
| `uwReservedSize` | User world Reserved Memory Size | `byte` | User world Reserved Memory Size. |
| `vitdConsumedSize` | Vitd consumed size | `byte` | *(derived)* |
| `vitdMemAllocMax` | Vitd mem alloc (max) |  | *(derived)* |
| `vitdMemAllocMin` | Vitd mem alloc (min) |  | *(derived)* |
| `vitdReservedSize` | Vitd reserved size | `byte` | *(derived)* |
| `vsandevicemonitordConsumedSize` | Vsandevicemonitord consumed size | `byte` | *(derived)* |
| `vsandevicemonitordMemAllocMax` | Vsandevicemonitord mem alloc (max) |  | *(derived)* |
| `vsandevicemonitordMemAllocMin` | Vsandevicemonitord mem alloc (min) |  | *(derived)* |
| `vsandevicemonitordReservedSize` | Vsandevicemonitord reserved size | `byte` | *(derived)* |
| `vsanmgmtdConsumedSize` | Vsanmgmtd consumed size | `byte` | *(derived)* |
| `vsanmgmtdMemAllocMax` | Vsanmgmtd mem alloc (max) |  | *(derived)* |
| `vsanmgmtdMemAllocMin` | Vsanmgmtd mem alloc (min) |  | *(derived)* |
| `vsanmgmtdReservedSize` | Vsanmgmtd reserved size | `byte` | *(derived)* |
| `vsanmgmtdWatchdogConsumedSize` | Vsanmgmtd watchdog consumed size | `byte` | *(derived)* |
| `vsanmgmtdWatchdogMemAllocMax` | Vsanmgmtd watchdog mem alloc (max) |  | *(derived)* |
| `vsanmgmtdWatchdogMemAllocMin` | Vsanmgmtd watchdog mem alloc (min) |  | *(derived)* |
| `vsanmgmtdWatchdogReservedSize` | Vsanmgmtd watchdog reserved size | `byte` | *(derived)* |
| `vsanobserverConsumedSize` | Vsanobserver consumed size | `byte` | *(derived)* |
| `vsanobserverMemAllocMax` | Vsanobserver mem alloc (max) |  | *(derived)* |
| `vsanobserverMemAllocMin` | Vsanobserver mem alloc (min) |  | *(derived)* |
| `vsanobserverReservedSize` | Vsanobserver reserved size | `byte` | *(derived)* |
| `vsantracedConsumedSize` | Vsantraced consumed size | `byte` | *(derived)* |
| `vsantracedMemAllocMax` | Vsantraced mem alloc (max) |  | *(derived)* |
| `vsantracedMemAllocMin` | Vsantraced mem alloc (min) |  | *(derived)* |
| `vsantracedReservedSize` | Vsantraced reserved size | `byte` | *(derived)* |

### vSAN Physical NIC — `VsanPnic`

perfsvc entity `vsan-pnic-net` · identified by `host_uuid`, `vmnic` · 7 objects observed · 65 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `ioChainDrops` | IO chain drops |  | *(derived)* |
| `ioChainDropsActual` | IO chain drops (actual) |  | *(derived)* |
| `ioChainRxdrops` | IO chain RX drops |  | *(derived)* |
| `ioChainRxdropsActual` | IO chain RX drops (actual) |  | *(derived)* |
| `ioChainTxdrops` | IO chain TX drops |  | *(derived)* |
| `ioChainTxdropsActual` | IO chain TX drops (actual) |  | *(derived)* |
| `pauseCount` | pNic 802.3x Pause Rate |  | Percentage of Physical NIC 802.3x Pause Rate. |
| `pauseCountActual` | Pause count (actual) |  | *(derived)* |
| `pauseCountRaw` | Pause count raw |  | *(derived)* |
| `pfcCount` | PFC count |  | *(derived)* |
| `pfcCountActual` | PFC count (actual) |  | *(derived)* |
| `pfcCountRaw` | PFC count raw |  | *(derived)* |
| `portRxDrops` | Inbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Inbound Packet Drop Rate. |
| `portRxDropsActual` | Port RX drops (actual) |  | *(derived)* |
| `portRxpkts` | Port RX packets |  | *(derived)* |
| `portTxDrops` | Outbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Outbound Packet Drop Rate. |
| `portTxDropsActual` | Port TX drops (actual) |  | *(derived)* |
| `portTxpkts` | Port TX packets |  | *(derived)* |
| `rxCrcErr` | pNIC RX CRC Error |  | Percentage of Physical NIC RX CRC Error. |
| `rxCrcErrActual` | RX CRC errors (actual) |  | *(derived)* |
| `rxCrcErrRaw` | RX CRC errors raw |  | *(derived)* |
| `rxDrp` | RX dropped |  | *(derived)* |
| `rxDrpActual` | RX dropped (actual) |  | *(derived)* |
| `rxErr` | pNIC RX Generic Error |  | Percentage of Physical NIC RX Generic Error. |
| `rxErrActual` | RX errors (actual) |  | *(derived)* |
| `rxErrRaw` | RX errors raw |  | *(derived)* |
| `rxFifoErr` | pNIC RX FIFO Error |  | Percentage of Physical NIC RX FIFO Error. |
| `rxFifoErrActual` | RX FIFO errors (actual) |  | *(derived)* |
| `rxFifoErrRaw` | RX FIFO errors raw |  | *(derived)* |
| `rxFrmErr` | RX frame alignment errors |  | *(derived)* |
| `rxFrmErrActual` | RX frame alignment errors (actual) |  | *(derived)* |
| `rxLgtErr` | RX length errors |  | *(derived)* |
| `rxLgtErrActual` | RX length errors (actual) |  | *(derived)* |
| `rxMissErr` | pNIC RX Missed Error |  | Percentage of Physical NIC RX Missed Error. |
| `rxMissErrActual` | pNIC RX missed error (ring buffer full) (actual) |  | *(derived)* |
| `rxMissErrRaw` | pNIC RX missed error (ring buffer full) (raw) |  | *(derived)* |
| `rxOvErr` | pNIC RX Buffer Overflow Error |  | Percentage of Physical NIC RX Buffer Overflow Error. |
| `rxOvErrActual` | RX overrun errors (actual) |  | *(derived)* |
| `rxOvErrRaw` | RX overrun errors raw |  | *(derived)* |
| `rxPackets` | Inbound Packets Per Second |  | VMkernel Network Adapter Inbound Packets Per Second. |
| `rxPacketsLossRate` | Inbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Inbound Packet Discard Rate. |
| `rxPacketsLossRateActual` | RX packets loss (rate, actual) |  | *(derived)* |
| `rxPktRaw` | RX packet raw |  | *(derived)* |
| `rxThroughput` | Throughput Inbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Inbound. |
| `txAbortErr` | TX aborted errors |  | *(derived)* |
| `txAbortErrActual` | TX aborted errors (actual) |  | *(derived)* |
| `txCarErr` | pNIC TX Carrier Error |  | Percentage of Physical NIC TX Carrier Error. |
| `txCarErrActual` | TX carrier errors (actual) |  | *(derived)* |
| `txCarErrRaw` | TX carrier errors raw |  | *(derived)* |
| `txDrp` | TX dropped |  | *(derived)* |
| `txDrpActual` | TX dropped (actual) |  | *(derived)* |
| `txErr` | pNIC TX Generic Error |  | Percentage of Physical NIC TX Generics Error. |
| `txErrActual` | TX errors (actual) |  | *(derived)* |
| `txErrRaw` | TX errors raw |  | *(derived)* |
| `txFifoErr` | TX FIFO errors |  | *(derived)* |
| `txFifoErrActual` | TX FIFO errors (actual) |  | *(derived)* |
| `txHeartErr` | TX heartbeat errors |  | *(derived)* |
| `txHeartErrActual` | TX heartbeat errors (actual) |  | *(derived)* |
| `txPackets` | Outbound Packets Per Second |  | VMkernel Network Adapter Outbound Packets Per Second. |
| `txPacketsLossRate` | Outbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Outbound Packet Discard Rate. |
| `txPacketsLossRateActual` | TX packets loss (rate, actual) |  | *(derived)* |
| `txPktRaw` | TX packet raw |  | *(derived)* |
| `txThroughput` | Throughput Outbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Outbound. |
| `txWinErr` | TX window errors |  | *(derived)* |
| `txWinErrActual` | TX window errors (actual) |  | *(derived)* |

### vSAN TCP/IP — `VsanTcpIp`

perfsvc entity `vsan-tcpip-stats` · identified by `host_uuid`, `stack` · 4 objects observed · 32 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `arpDropRate` | ARP drop (rate) |  | *(derived)* |
| `ip6Errs` | IPv6 Errors |  | VMkernel Network Adapter IPv6 error rate. |
| `ip6Total` | IP6 (total) |  | *(derived)* |
| `ipErrs` | IPv4 Errors |  | VMkernel Network Adapter IPv4 error rate. |
| `ipTotal` | IP (total) |  | *(derived)* |
| `tcpEcnCe` | TCP ECN ce |  | *(derived)* |
| `tcpErrs` | TCP Errors |  | VMkernel Network Adapter TCP error rate. |
| `tcpErrsActual` | TCP errors (actual) |  | *(derived)* |
| `tcpHalfopenDropRate` | Half Open Drop Rate |  | VMkernel Network Adapter half open drop rate. |
| `tcpHalfopenDropRateActual` | TCP halfopen drop (rate, actual) |  | *(derived)* |
| `tcpRcvdupackRate` | Received Duplicate Acknowledge Rate |  | VMkernel Network Adapter received duplicate acknowledge rate. |
| `tcpRcvdupackRateActual` | TCP received duplicate ACKs (rate, actual) |  | *(derived)* |
| `tcpRcvduppackRate` | Received Duplicate Packets Rate |  | VMkernel Network Adapter received duplicate packets rate. |
| `tcpRcvduppackRateActual` | TCP received duplicate packets (rate, actual) |  | *(derived)* |
| `tcpRcvoopackRate` | Received Out-of-order Packets Rate |  | VMkernel Network Adapter received out-of-order packets rate. |
| `tcpRcvoopackRateActual` | TCP received out-of-order packets (rate, actual) |  | *(derived)* |
| `tcpRxErrRate` | TCP RX errors (rate) |  | *(derived)* |
| `tcpRxPackets` | TCP Inbound Packets |  | VMkernel Network Adapter TCP inbound packets. |
| `tcpRxThroughput` | TCP Inbound Throughout | `bibyte_per_second` | VMkernel Network Adapter TCP inbound throughout. |
| `tcpSackRcvBlocksRate` | Sack Received Blocks Rate |  | VMkernel Network Adapter sack received blocks rate. |
| `tcpSackRcvBlocksRateActual` | TCP SACK received blocks (rate, actual) |  | *(derived)* |
| `tcpSackRexmitsRate` | Sack Rexmits Rate |  | VMkernel Network Adapter sack rexmits rate. |
| `tcpSackRexmitsRateActual` | TCP SACK retransmits (rate, actual) |  | *(derived)* |
| `tcpSackSendBlocksRate` | Sack Send Blocks Rate |  | VMkernel Network Adapter sack send blocks rate. |
| `tcpSackSendBlocksRateActual` | TCP SACK send blocks (rate, actual) |  | *(derived)* |
| `tcpSndZeroWin` | TCP Send Zero Window |  | VMkernel Network Adapter TCP send zero window. |
| `tcpSndZeroWinActual` | TCP sent zero window (actual) |  | *(derived)* |
| `tcpTimeoutDropRate` | Timeout Drop Rate |  | VMkernel Network Adapter timeout drop rate. |
| `tcpTimeoutDropRateActual` | TCP timeout drop (rate, actual) |  | *(derived)* |
| `tcpTxPackets` | TCP Outbound Packets |  | VMkernel Network Adapter TCP outbound packets. |
| `tcpTxRexmitRate` | TCP TX retransmit (rate) |  | *(derived)* |
| `tcpTxThroughput` | TCP Outbound Throughout | `bibyte_per_second` | VMkernel Network Adapter TCP outbound throughout. |

### vSAN VMkernel NIC — `VsanVnic`

perfsvc entity `vsan-vnic-net` · identified by `host_uuid`, `stack`, `vmknic` · 4 objects observed · 64 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `arpDropRate` | ARP drop (rate) |  | *(derived)* |
| `ioChainDrops` | IO chain drops |  | *(derived)* |
| `ioChainDropsActual` | IO chain drops (actual) |  | *(derived)* |
| `ioChainRxdrops` | IO chain RX drops |  | *(derived)* |
| `ioChainRxdropsActual` | IO chain RX drops (actual) |  | *(derived)* |
| `ioChainTxdrops` | IO chain TX drops |  | *(derived)* |
| `ioChainTxdropsActual` | IO chain TX drops (actual) |  | *(derived)* |
| `ip6Errs` | IPv6 Errors |  | VMkernel Network Adapter IPv6 error rate. |
| `ip6Total` | IP6 (total) |  | *(derived)* |
| `ipErrs` | IPv4 Errors |  | VMkernel Network Adapter IPv4 error rate. |
| `ipTotal` | IP (total) |  | *(derived)* |
| `portRxDrops` | Inbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Inbound Packet Drop Rate. |
| `portRxDropsActual` | Port RX drops (actual) |  | *(derived)* |
| `portRxpkts` | Port RX packets |  | *(derived)* |
| `portTxDrops` | Outbound Packet Drop Rate of vSwitch Port |  | Percentage of VMkernel Network vSwitch Port Outbound Packet Drop Rate. |
| `portTxDropsActual` | Port TX drops (actual) |  | *(derived)* |
| `portTxpkts` | Port TX packets |  | *(derived)* |
| `rxPackets` | Inbound Packets Per Second |  | VMkernel Network Adapter Inbound Packets Per Second. |
| `rxPacketsLossRate` | Inbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Inbound Packet Discard Rate. |
| `rxPacketsLossRateActual` | RX packets loss (rate, actual) |  | *(derived)* |
| `rxThroughput` | Throughput Inbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Inbound. |
| `tcpBadrst` | TCP badrst |  | *(derived)* |
| `tcpBadsyn` | TCP badsyn |  | *(derived)* |
| `tcpConndrops` | TCP conndrops |  | *(derived)* |
| `tcpConnects` | TCP connects |  | *(derived)* |
| `tcpDrops` | TCP drops |  | *(derived)* |
| `tcpEcnCe` | TCP ECN ce |  | *(derived)* |
| `tcpErrs` | TCP Errors |  | VMkernel Network Adapter TCP error rate. |
| `tcpHalfopenDropRate` | Half Open Drop Rate |  | VMkernel Network Adapter half open drop rate. |
| `tcpKeepdrops` | TCP keepdrops |  | *(derived)* |
| `tcpKeeptimeo` | TCP keeptimeo |  | *(derived)* |
| `tcpPersisttimeo` | TCP persisttimeo |  | *(derived)* |
| `tcpRcvackpack` | TCP received ackpack |  | *(derived)* |
| `tcpRcvbadoff` | TCP received badoff |  | *(derived)* |
| `tcpRcvbadsum` | TCP received badsum |  | *(derived)* |
| `tcpRcvdupack` | TCP received duplicate ACKs |  | *(derived)* |
| `tcpRcvdupackRate` | Received Duplicate Acknowledge Rate |  | VMkernel Network Adapter received duplicate acknowledge rate. |
| `tcpRcvduppack` | TCP received duplicate packets |  | *(derived)* |
| `tcpRcvduppackRate` | Received Duplicate Packets Rate |  | VMkernel Network Adapter received duplicate packets rate. |
| `tcpRcvmemdrop` | TCP received memdrop |  | *(derived)* |
| `tcpRcvoopack` | TCP received out-of-order packets |  | *(derived)* |
| `tcpRcvoopackRate` | Received Out-of-order Packets Rate |  | VMkernel Network Adapter received out-of-order packets rate. |
| `tcpRcvshort` | TCP received short |  | *(derived)* |
| `tcpRexmttimeo` | TCP rexmttimeo |  | *(derived)* |
| `tcpRxErrRate` | TCP RX errors (rate) |  | *(derived)* |
| `tcpRxPackets` | TCP Inbound Packets |  | VMkernel Network Adapter TCP inbound packets. |
| `tcpRxThroughput` | TCP Inbound Throughout | `bibyte_per_second` | VMkernel Network Adapter TCP inbound throughout. |
| `tcpSackRcvBlocks` | TCP SACK received blocks |  | *(derived)* |
| `tcpSackRcvBlocksRate` | Sack Received Blocks Rate |  | VMkernel Network Adapter sack received blocks rate. |
| `tcpSackRexmits` | TCP SACK retransmits |  | *(derived)* |
| `tcpSackRexmitsRate` | Sack Rexmits Rate |  | VMkernel Network Adapter sack rexmits rate. |
| `tcpSackSendBlocks` | TCP SACK send blocks |  | *(derived)* |
| `tcpSackSendBlocksRate` | Sack Send Blocks Rate |  | VMkernel Network Adapter sack send blocks rate. |
| `tcpSndZeroWin` | TCP Send Zero Window |  | VMkernel Network Adapter TCP send zero window. |
| `tcpSndacks` | TCP sent ACKS |  | *(derived)* |
| `tcpTimeoutDropRate` | Timeout Drop Rate |  | VMkernel Network Adapter timeout drop rate. |
| `tcpTimeoutdrop` | TCP timeoutdrop |  | *(derived)* |
| `tcpTxPackets` | TCP Outbound Packets |  | VMkernel Network Adapter TCP outbound packets. |
| `tcpTxRexmitRate` | TCP TX retransmit (rate) |  | *(derived)* |
| `tcpTxThroughput` | TCP Outbound Throughout | `bibyte_per_second` | VMkernel Network Adapter TCP outbound throughout. |
| `txPackets` | Outbound Packets Per Second |  | VMkernel Network Adapter Outbound Packets Per Second. |
| `txPacketsLossRate` | Outbound Packet Discard Rate |  | Percentage of VMkernel Network Adapter Outbound Packet Discard Rate. |
| `txPacketsLossRateActual` | TX packets loss (rate, actual) |  | *(derived)* |
| `txThroughput` | Throughput Outbound | `bibyte_per_second` | VMkernel Network Adapter Throughput Outbound. |

### vSAN vSCSI — `VsanVscsi`

perfsvc entity `vscsi` · identified by `vm_uuid`, `device` · 106 objects observed · 8 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `iopsRead` | Read IOPS | `io_operations_per_second` | Read IO per second on the VMDK. |
| `iopsWrite` | Write IOPS | `io_operations_per_second` | Write IO per second on the VMDK. |
| `latencyRead` | vSAN Layer Read Latency | `microseconds` | Disk vSAN layer read latency. |
| `latencyWrite` | vSAN Layer Write Latency | `microseconds` | Disk vSAN layer write latency. |
| `readCount` | Read count |  | *(derived)* |
| `throughputRead` | Read throughput | `bibyte_per_second` | Read IO throughput on the VMDK. |
| `throughputWrite` | Write throughput | `bibyte_per_second` | Write IO throughput on the VMDK. |
| `writeCount` | Write count |  | *(derived)* |

### Zdom Vtx — `VsanZdomVtx`

perfsvc entity `zdom-vtx` · identified by `host_uuid` · 4 objects observed · 71 metrics

| Metric | Name | Unit | Definition |
|---|---|---|---|
| `allOpCacheMaxGetLatUSec` | All op cache max get latency u sec | `microseconds` | *(derived)* |
| `cacheMissPerLookupTxn` | Cache miss per lookup transaction |  | *(derived)* |
| `cacheMissPerPrefetchTxn` | Cache miss per prefetch transaction |  | *(derived)* |
| `cacheMissPerSegCleaningCtxDataTxn` | Cache miss per seg cleaning context data transaction |  | *(derived)* |
| `checkpointWorkerWakeupMs` | Checkpoint worker wakeup ms | `microseconds` | *(derived)* |
| `iopsCacheMissRate` | Cache Miss Per IOPS | `io_operations_per_second` | Cache miss per IOPS. |
| `latAvgCacheGet` | Latency avg cache get | `microseconds` | *(derived)* |
| `latAvgTotalOpIO` | Latency avg total op IO | `microseconds` | *(derived)* |
| `latAvgTxnBank` | Latency avg transaction bank | `microseconds` | *(derived)* |
| `latAvgTxnBankTotalIO` | Latency avg transaction bank total IO | `microseconds` | *(derived)* |
| `latAvgTxnUnmap` | Latency avg transaction unmap | `microseconds` | *(derived)* |
| `latAvgTxnUnmapTotalIO` | Latency avg transaction unmap total IO | `microseconds` | *(derived)* |
| `maxDiscUsedPct` | Disc used percent (max) | `percent` | *(derived)* |
| `missesPerIO` | Misses per IO |  | *(derived)* |
| `prefetchCacheMaxGetLatUs` | Prefetch cache max get latency us | `microseconds` | *(derived)* |
| `rateBankFlushTotalCacheRef` | Bank flush total cache ref (rate) |  | *(derived)* |
| `rateSegCleaningCtxDataTotalCacheRef` | Seg cleaning context data total cache ref (rate) |  | *(derived)* |
| `rateTotDirtyCachePage` | Tot dirty cache page (rate) |  | *(derived)* |
| `rateTotalBitmapCacheMiss` | Bitmap cache miss (rate, total) |  | *(derived)* |
| `rateTotalCacheMiss` | Cache miss (rate, total) |  | *(derived)* |
| `rateTotalCacheRef` | Cache ref (rate, total) |  | *(derived)* |
| `rateTotalLogicalTreeCacheMiss` | Logical tree cache miss (rate, total) |  | *(derived)* |
| `rateTotalMiddleTreeCacheMiss` | Middle tree cache miss (rate, total) |  | *(derived)* |
| `rateTotalSnapTreeCacheMiss` | Snap tree cache miss (rate, total) |  | *(derived)* |
| `rateTotalSutCacheMiss` | Sut cache miss (rate, total) |  | *(derived)* |
| `rateTxnBankLogicalTreeCacheMiss` | Transaction bank logical tree cache miss (rate) |  | *(derived)* |
| `rateTxnBankLogicalTreeCacheRef` | Transaction bank logical tree cache ref (rate) |  | *(derived)* |
| `rateTxnBankMiddleTreeCacheMiss` | Transaction bank middle tree cache miss (rate) |  | *(derived)* |
| `rateTxnBankMiddleTreeCacheRef` | Transaction bank middle tree cache ref (rate) |  | *(derived)* |
| `rateTxnBankSutCacheMiss` | Transaction bank sut cache miss (rate) |  | *(derived)* |
| `rateTxnBankSutCacheRef` | Transaction bank sut cache ref (rate) |  | *(derived)* |
| `rateTxnBankTotalCacheMiss` | Transaction bank total cache miss (rate) |  | *(derived)* |
| `rateTxnBankTotalCacheRef` | Transaction bank total cache ref (rate) |  | *(derived)* |
| `rateTxnLookupCacheMiss` | Transaction lookup cache miss (rate) |  | *(derived)* |
| `rateTxnLookupCacheRef` | Transaction lookup cache ref (rate) |  | *(derived)* |
| `rateTxnLookupLogicalTreeCacheMiss` | Transaction lookup logical tree cache miss (rate) |  | *(derived)* |
| `rateTxnLookupLogicalTreeCacheRef` | Transaction lookup logical tree cache ref (rate) |  | *(derived)* |
| `rateTxnLookupMiddleTreeCacheMiss` | Transaction lookup middle tree cache miss (rate) |  | *(derived)* |
| `rateTxnLookupMiddleTreeCacheRef` | Transaction lookup middle tree cache ref (rate) |  | *(derived)* |
| `rateTxnPrefetchLogicalTreeCacheMiss` | Transaction prefetch logical tree cache miss (rate) |  | *(derived)* |
| `rateTxnPrefetchLogicalTreeCacheRef` | Transaction prefetch logical tree cache ref (rate) |  | *(derived)* |
| `rateTxnPrefetchMiddleTreeCacheMiss` | Transaction prefetch middle tree cache miss (rate) |  | *(derived)* |
| `rateTxnPrefetchMiddleTreeCacheRef` | Transaction prefetch middle tree cache ref (rate) |  | *(derived)* |
| `rateTxnPrefetchSutCacheMiss` | Transaction prefetch sut cache miss (rate) |  | *(derived)* |
| `rateTxnPrefetchSutCacheRef` | Transaction prefetch sut cache ref (rate) |  | *(derived)* |
| `rateTxnPrefetchTotalCacheMiss` | Transaction prefetch total cache miss (rate) |  | *(derived)* |
| `rateTxnPrefetchTotalCacheRef` | Transaction prefetch total cache ref (rate) |  | *(derived)* |
| `rateTxnReadWrite` | Transaction (read, write, rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataLogicalTreeCacheMiss` | Transaction seg cleaning context data logical tree cache miss (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataLogicalTreeCacheRef` | Transaction seg cleaning context data logical tree cache ref (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataMiddleTreeCacheMiss` | Transaction seg cleaning context data middle tree cache miss (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataMiddleTreeCacheRef` | Transaction seg cleaning context data middle tree cache ref (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataSutCacheMiss` | Transaction seg cleaning context data sut cache miss (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataSutCacheRef` | Transaction seg cleaning context data sut cache ref (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataTotalCacheMiss` | Transaction seg cleaning context data total cache miss (rate) |  | *(derived)* |
| `rateTxnSegCleaningCtxDataTotalCacheRef` | Transaction seg cleaning context data total cache ref (rate) |  | *(derived)* |
| `rateTxnUnmapLogicalTreeCacheMiss` | Transaction unmap logical tree cache miss (rate) |  | *(derived)* |
| `rateTxnUnmapMiddleTreeCacheMiss` | Transaction unmap middle tree cache miss (rate) |  | *(derived)* |
| `rateTxnUnmapSutCacheMiss` | Transaction unmap sut cache miss (rate) |  | *(derived)* |
| `rateTxnUnmapTotalCacheMiss` | Transaction unmap total cache miss (rate) |  | *(derived)* |
| `tputCacheMissRate` | Cache Miss Per Throughput |  | Cache miss per throughput. |
| `txnBankMaxLatUs` | Transaction bank max latency us | `microseconds` | *(derived)* |
| `txnCacheFlushMaxLatUs` | Transaction cache flush max latency us | `microseconds` | *(derived)* |
| `txnDLogMaxLatUs` | Transaction d log max latency us | `microseconds` | *(derived)* |
| `txnDelExtMiddleTreeMaxLatUs` | Transaction del ext middle tree max latency us | `microseconds` | *(derived)* |
| `txnLookupMaxLatUs` | Transaction lookup max latency us |  | *(derived)* |
| `txnPrefetchMaxLatUs` | Transaction prefetch max latency us | `microseconds` | *(derived)* |
| `txnSegCtxDataMaxLatUs` | Transaction seg context data max latency us | `microseconds` | *(derived)* |
| `txnSegCtxLLPMaxLatUs` | Transaction seg context llp max latency us | `microseconds` | *(derived)* |
| `txnUnmapMaxLatUs` | Transaction unmap max latency us | `microseconds` | *(derived)* |
| `txnVatWriteSegMaxLatUs` | Transaction vat write seg max latency us | `microseconds` | *(derived)* |

<!-- METRIC-REFERENCE-END -->
