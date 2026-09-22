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

The adapter runs in a container on a Cloud Proxy and cannot run
`configstorecli` on each host, so the token is a config field you paste in.

**Tokens are cluster-wide, not per-host** (confirmed on `example.com`,
2026-09-22). The single credential field in `get_adapter_definition()` is
therefore the right model, not a simplification -- one credential covers every
host in the cluster, and the `hosts` parameter can list them all against it.

Still open: what rotates them, and how the adapter notices. Note that this is
harder than it looks here, because the host returns **403 for every
authentication failure and never 401** -- see `BUGS-UPSTREAM.md` item 4. A
rotated token is thus not trivially distinguishable from an authorisation
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

Output lands in `build/VsanHostMetrics_1.0.0.pak`, with the image digest baked
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

Install `build/VsanHostMetrics_1.0.0.pak` through the VCF Operations UI
(Administration -> Repository). This writes the adapter's `describe.xml` schema
-- resource kinds, identifiers, attributes -- into the Operations database, and
drops a plugin directory alongside the existing ones in
`/usr/lib/vmware-vcops/user/plugins/inbound/`.

**Bump `Implementation-Version` in `manifest.txt` for every reinstall.**
Operations uses it for upgrade detection and handles same-version reinstalls
badly.

### 6. Restart the collector, create the adapter instance

Restart the Cloud Proxy service, then create the adapter instance and assign it
to that proxy. Configuration takes `hosts`, `verify_certs`, the bearer token
credential, and `container_memory_limit`.

### 7. What needs a full reinstall, and what does not

Most iteration does not need step 5 at all:

| Changed | Needed |
|---|---|
| `vsanmetrics.py`, `collect()` logic, thresholds | rebuild, update `DIGEST` in the `.conf`, restart collector |
| `get_adapter_definition()`, `content/`, display names | full pak reinstall (regenerates `describe.xml`) |

The container is disposable; the schema written into the Operations database is
not. Snapshot the Operations cluster before schema changes -- not the Cloud
Proxy, which holds little beyond cached images and the `.conf`. Prune cached
images there periodically; each digest is roughly 265 MB on disk.

Note the fast path in row one is claimed but not yet verified -- confirm it on
the first code-only iteration before relying on it.
