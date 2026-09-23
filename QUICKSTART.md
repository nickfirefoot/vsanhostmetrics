# QUICKSTART — deploy this pack

From nothing to collecting, for someone who has not seen this before.
Deeper detail is in `REQUIREMENTS.md`; this is the shortest correct path.

Verified against **VCF Operations 9.x**. 8.x is unverified — see the end.

---

## What you need

| | |
|---|---|
| VCF Operations | 9.x, admin rights to install a pak |
| A Cloud Proxy | the adapter runs as a container **on the proxy** |
| vCenter | with vSAN, and the **vSAN Performance Service enabled** on the cluster |
| A vCenter account | **read-only**, propagated from the vCenter root |
| Outbound 443 from the Cloud Proxy to `ghcr.io` | to pull the adapter image, once per version |

You do **not** need: ESXi credentials, SSH to any host, a container registry of
your own, or any per-host firewall rule. The pack talks to exactly one thing at
collection time — your vCenter, on 443.

### The one firewall line

The `.pak` is ~145 KB of schema. The adapter itself is a ~100 MB container
image published at `ghcr.io/nickfirefoot/vsanhostmetrics`, which the **Cloud
Proxy** pulls once per version. So the Cloud Proxy needs outbound 443 to
`ghcr.io`. That is the whole network ask — `ghcr.io` is a public registry with a
publicly trusted certificate, so there is no CA to install and no DNS to add.

If your Cloud Proxy cannot reach the internet at all, see
`docs/OFFLINE-DELIVERY.md` — that case needs a registry inside your
environment, and it is the same for any container-based management pack.

---

## 1. Install the pak

**Administration → Integrations → Repository → Add.**

(Broadcom's docs say Data Sources → Integrations; Administration → Integrations
is the path actually present in 9.x. Not "Software Depot", which configures the
VCF software depot and is unrelated.)

Tick **both** boxes:

- *Install the PAK file even if it is already installed* — needed for every reinstall
- *Ignore the PAK file signature checking* — **required**, this pak is unsigned

**Upgrading?** Uninstall the old version and delete its adapter instances
first. A schema change otherwise leaves the previous `describe.xml` in the
Operations database, and you end up with orphaned resource kinds and objects
that never collect again.

## 2. Create the adapter instance

**Administration → Integrations → Accounts → Add Account →** `vSAN Host Metrics`.

| Field | Value |
|---|---|
| vCenter Server | **FQDN** of vCenter |
| vCenter username | e.g. `vsanmon@vsphere.local` |
| Credential | that account's password |
| Verify vCenter certificate | **false** — see below |
| Cloud Proxy / Group | **your Cloud Proxy**, explicitly |
| container_memory_limit | 1024 (Advanced Settings) |

Two things fail here if rushed.

**Collector selection.** Pick the Cloud Proxy explicitly. Left on a default
collector group, Operations tries to run the container on an analytics node
that never pulled the image — and the failure reads like a registry problem
rather than a placement one.

**Certificate verification.** The default is `true` and **does not work
unmodified**: vCenter presents a VMCA-issued certificate
(`CN=CA, DC=vsphere, DC=local`) that nothing in the adapter's base image
trusts. Either set it false, or import the VMCA root from
`https://<vcenter>/certs/download.zip` into the container trust store. If you
leave it `true`, the vCenter field must hold the **FQDN** — an IP fails
hostname matching even once the root is trusted, and that failure looks
identical to an untrusted chain.

Click **Validate Connection** before saving. That runs a real Performance
Service query, so green proves credential, privilege and network path at once.
Expect one certificate-acceptance prompt for vCenter.

## 3. Confirm it is collecting

The first collection carries data — there is no warm-up. An empty first cycle
is a fault, not the design.

Expect roughly **210 objects per host**, plus per-VM and per-disk objects; a
four-host cluster produces 847 across 31 resource kinds. Names must be real
(`esxi01.example.com [vmnic0]`, `NVMe Micron 7450 MTFDKCB1T9TFR FCD8154… (esxi03.example.com)`),
never bare UUIDs.

Check through the API rather than by eye:

```sh
TOK=$(curl -sk -X POST "https://<ops>/suite-api/api/auth/token/acquire" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"username":"<user>","password":"<pass>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -sk -H "Authorization: vRealizeOpsToken $TOK" -H 'Accept: application/json' \
  "https://<ops>/suite-api/api/resources?pageSize=10000" \
| python3 -c "import sys,json,collections; r=[x for x in json.load(sys.stdin)['resourceList'] \
  if x['resourceKey'].get('adapterKindKey')=='VsanHostMetrics']; \
  print(len(r), collections.Counter(x['resourceStatusStates'][0]['resourceStatus'] for x in r))"
```

Every object should be `DATA_RECEIVING`.

---

## Building it yourself (optional)

You do not need to. The published pak points at a public image. Build only if
you want to modify the adapter or host the image yourself.

```sh
python3 -m venv ~/.mp && . ~/.mp/bin/activate
pip install vmware-aria-operations-integration-sdk==1.3.1

git clone https://github.com/nickfirefoot/vsanhostmetrics && cd vsanhostmetrics
python3 test_perfsvc.py                      # expect 26/26 — if not, stop

python3 scaffold_project.py ~/vsan-host-metrics
cp -a app/. ~/vsan-host-metrics/app/ && cp pak_icon.png ~/vsan-host-metrics/
# bump "version" in ~/vsan-host-metrics/manifest.txt

cd ~/vsan-host-metrics
mp-build --no-ttl -r "<your-registry>/<project>/vsanhostmetrics" \
  --registry-username "<user>" --registry-password "<pass>"
```

Use `scaffold_project.py`, **not** `mp-init` — `mp-init` deletes its own
project on a host without `ensurepip`.

If you point this at your own private registry, the Cloud Proxy must trust its
CA (`/etc/docker/certs.d/<registry>/ca.crt`) and resolve it **by hostname** —
most registry certificates have a DNS SAN and no IP SAN. Prove `docker pull` by
digest on the proxy *before* installing the pak; it separates registry problems
from management-pack problems, which otherwise look identical in the UI.

---

## Known unknowns

Untested, listed so a failure is recognised rather than debugged from scratch:

- **VCF Operations 8.x.** `manifest.txt` claims `vcops_minimum_version 8.10.0`
  but only 9.x has been run.
- **`Verify vCenter certificate: true`.** Known to fail without importing the
  VMCA root; the import path itself has not been exercised.
- **OSA clusters.** All modelling and testing is on **ESA**. The OSA entity
  types are in the model but return nothing on ESA, so they are unverified.
- **vSAN file services and iSCSI.** Present in the schema, never enabled.
- **Stretched clusters, multiple clusters per vCenter, more than four hosts.**
- **A truly minimal read-only role.** The account used had read-only
  propagated from the root; the precise minimum privilege set was not reduced.
