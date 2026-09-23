# QUICKSTART — deploy this pack from scratch

For someone picking this up cold with their own VCF Operations environment.
Deeper detail lives in `REQUIREMENTS.md` (what must be true) and `README.md`
(why each step exists). This file is the shortest correct path.

Verified against **VCF Operations 9.x** on 2026-09-23.
**8.x is unverified** — see "Known unknowns" at the end.

---

## 0. Read this first: the pak is not portable

A `.pak` does not contain the adapter code. It contains a *pointer* to a
container image:

```
REGISTRY=registry.example.com
REPOSITORY=/nickfirefoot/vsanhostmetrics
DIGEST=sha256:a5085321c9e6e8271ee9a2c4dbc11de4334dfee96f9bac0010472a9d6e14a0e1
```

`registry.example.com` resolves only inside the lab it was built in. **Taking the
`.pak` to another environment does not work** unless that environment's Cloud
Proxy can reach that exact registry.

So pick a path before starting:

| Path | When | What you do |
|---|---|---|
| **A. Rebuild** | you have your own registry, or a different site | build from source against your registry — section 2 |
| **B. Reuse** | your Cloud Proxy can genuinely reach `registry.example.com:443` | skip to section 4 with the existing pak |

Path A is the normal one. Assume it unless you know otherwise.

---

## 1. What you need before starting

| Thing | Notes |
|---|---|
| VCF Operations | 9.x verified. Admin rights to install a pak |
| A Cloud Proxy | the adapter runs as a container **on the proxy**, not on analytics nodes |
| vCenter | with vSAN, and the **vSAN Performance Service enabled** on the cluster |
| A vCenter account | **read-only**, propagated from the vCenter root, is sufficient |
| An OCI registry | Harbor, ECR, GHCR, anything both the build host and Cloud Proxy can reach by **hostname** |
| A Linux build host | 2 vCPU / 4 GB / 40 GB, Docker, Python 3.9+ — throwaway |

You do **not** need: ESXi access, host credentials, SSH to hosts, or any
firewall rule to ESXi. The pack talks to exactly one thing, vCenter on 443.

---

## 2. Build (path A)

On the build host:

```sh
sudo apt update && sudo apt install -y python3-venv python3-pip docker.io
sudo usermod -aG docker "$USER" && newgrp docker

python3 -m venv ~/.mp && . ~/.mp/bin/activate
pip install vmware-aria-operations-integration-sdk==1.3.1

git clone <this repo> && cd vsan-net-mp
python3 test_perfsvc.py        # expect 24/24 — if not, stop
```

Create the SDK project. **Use the script, not `mp-init`** — `mp-init`
self-deletes its own project on a host without `ensurepip`:

```sh
python3 scaffold_project.py ~/vsan-host-metrics
cp -a app/. ~/vsan-host-metrics/app/
cp pak_icon.png ~/vsan-host-metrics/
```

Bump `version` in `~/vsan-host-metrics/manifest.txt` — Operations handles
same-version reinstalls badly — then build and push:

```sh
cd ~/vsan-host-metrics
mp-build --no-ttl \
  -r "<registry-fqdn>/<project>/vsan-host-metrics" \
  --registry-username "<user>" --registry-password "<pass>"
```

Quote the username if it is a Harbor robot: `robot$project+name` — an unquoted
`$project` is eaten by the shell and produces a baffling `unauthorized`.

Output: `build/VsanHostMetrics_<version>.pak`. Confirm the image really landed:

```sh
D=$(python3 -c "import zipfile,io;z=zipfile.ZipFile('build/VsanHostMetrics_<version>.pak');\
a=zipfile.ZipFile(io.BytesIO(z.read('adapter.zip')));\
print([l for l in a.read('VsanHostMetrics.conf').decode().splitlines() if l.startswith('DIGEST')][0].split('=')[1])")
curl -s -o /dev/null -w '%{http_code}\n' -u "<user>:<pass>" \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
  "https://<registry-fqdn>/v2/<project>/vsan-host-metrics/manifests/$D"   # -> 200
```

---

## 3. Registry trust on the Cloud Proxy

**This is the step that silently blocks everything else.** If your registry
uses a private CA (Harbor's self-signed `Harbor CA` does), the Cloud Proxy
fails the image pull on certificate verification, and the Operations UI reports
it as a generic failure.

DNS first — the registry must be reachable **by hostname**. Harbor's generated
certificate has a DNS SAN and **no IP SAN**, so a bare IP always fails. An
`/etc/hosts` entry is fine on the build host and useless on the Cloud Proxy;
it needs a real A record.

SSH is disabled by default on the Cloud Proxy appliance. Enable from the VM
console with `systemctl enable --now sshd`, then:

```sh
mkdir -p /etc/docker/certs.d/<registry-fqdn>
cp registry-ca.crt /etc/docker/certs.d/<registry-fqdn>/ca.crt
chmod 644 /etc/docker/certs.d/<registry-fqdn>/ca.crt
```

No daemon restart — Docker reads that path per pull. For Harbor as a Supervisor
Service the CA comes from:

```sh
kubectl -n svc-harbor-<id> get secret harbor-tls -o jsonpath='{.data.ca\.crt}' | base64 -d
```

Verify before moving on. `Verify return code: 0 (ok)` is what you want:

```sh
echo | openssl s_client -connect <registry-fqdn>:443 2>/dev/null | grep 'Verify return code'
docker pull <registry-fqdn>/<project>/vsan-host-metrics@sha256:<digest>
```

Prove the pull here, before installing the pak. It separates registry problems
from management-pack problems, which otherwise look identical in the UI.

Consider turning SSH back off afterwards.

---

## 4. Install the pak

**Administration → Integrations → Repository → Add.**

(Broadcom's docs say Data Sources → Integrations; Administration → Integrations
is the path actually present in 9.x. Not "Software Depot" — that is the VCF
software depot and unrelated.)

Tick **both** boxes:

- *Install the PAK file even if it is already installed* — needed for every reinstall
- *Ignore the PAK file signature checking* — **required**, this pak is unsigned

Replacing an existing install? Uninstall the old pack and delete its adapter
instances first. A schema change leaves the old `describe.xml` in the
Operations database otherwise, and you end up with orphaned resource kinds and
objects that never collect again.

---

## 5. Create the adapter instance

**Administration → Integrations → Accounts → Add Account →** `vSAN Host Metrics`.

| Field | Value |
|---|---|
| vCenter Server | **FQDN** of vCenter |
| vCenter username | e.g. `vsanmon@vsphere.local` |
| Credential | that account's password |
| Verify vCenter certificate | **false** — see below |
| Cloud Proxy / Group | **your Cloud Proxy**, explicitly |
| container_memory_limit | 1024 (Advanced Settings) |

**Two things fail here if you rush them.**

*Collector selection.* Pick the Cloud Proxy explicitly. Left on a default
collector group, Operations tries to run the container on an analytics node
that has neither the image nor the registry CA — and the failure looks like a
registry problem rather than a placement one.

*Certificate verification.* The default is `true` and **does not work
unmodified**: vCenter presents a VMCA-issued certificate
(`CN=CA, DC=vsphere, DC=local`) that nothing in the adapter's base image
trusts. Either set it false, or import the VMCA root from
`https://<vcenter>/certs/download.zip` into the container trust store. If you
leave it true, the vCenter field must hold the FQDN — an IP fails hostname
matching even once the root is trusted.

Click **Validate Connection** before saving. That runs a real Performance
Service query, so green proves credential, privilege and network path at once.
Expect one certificate-acceptance prompt for vCenter.

---

## 6. Verify it worked

The first collection carries data — there is no warm-up. An empty first cycle
is a fault, not the design.

Expect roughly **210 objects per host** plus per-VM and per-disk objects; a
4-host cluster produced 847. Names must be real (`esxi01.example.com [vmnic0]`,
`NVMe Micron 7450 MTFDKCB1T9TFR FCD815400175A000 (esxi03.example.com)`), never
bare UUIDs.

Check through the API rather than by eye:

```sh
TOK=$(curl -sk -X POST "https://<ops>/suite-api/api/auth/token/acquire" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"username":"<user>","password":"<pass>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -sk -H "Authorization: vRealizeOpsToken $TOK" -H 'Accept: application/json' \
  "https://<ops>/suite-api/api/resources?pageSize=10000" \
| python3 -c "import sys,json,collections; r=[x for x in json.load(sys.stdin)['resourceList'] \
  if x['resourceKey'].get('adapterKindKey')=='VsanHostMetrics']; \
  print(len(r), collections.Counter(x['resourceStatusStates'][0]['resourceStatus'] for x in r))"
```

Every object should be `DATA_RECEIVING`.

---

## 7. Known unknowns — tell us if you hit these

Things genuinely untested, listed so a failure is recognised rather than
debugged from scratch:

- **VCF Operations 8.x.** `manifest.txt` claims `vcops_minimum_version 8.10.0`
  but only 9.x has been run. If 8.x fails, the likely suspects are the
  container-adapter runtime on the Cloud Proxy and the describe schema version.
- **`Verify vCenter certificate: true`.** Known to fail without importing the
  VMCA root; the import path itself has not been exercised.
- **OSA clusters.** All modelling and testing is on **ESA**. The OSA entity
  types (`disk-group`, `cache-disk`, `capacity-disk`, `ddh-disk`) are in the
  model but return nothing on ESA, so they are unverified.
- **vSAN file services and iSCSI.** Present in the schema, never enabled here.
- **Stretched clusters, multiple clusters per vCenter, >4 hosts.** Only a
  single 4-host cluster has been exercised.
- **A truly minimal read-only role.** The account used had read-only propagated
  from the root; the precise minimum privilege set has not been reduced to.
