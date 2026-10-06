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

**Upgrading?** It depends on whether the release changes the schema, and the
answer is in the pak rather than in the version number.

*Schema unchanged* -- install over the top. Tick both boxes above and leave the
adapter instance alone. Its credentials, its collector assignment and its
collected history all survive, and the new views and dashboards appear on the
next content import. **1.3.1 to 1.4.0 is this case**: content only.

*Schema changed* -- uninstall the old version and delete its adapter instances
first. Otherwise the previous `describe.xml` stays in the Operations database
and you are left with orphaned resource kinds and objects that never collect
again. **1.2.x to 1.3.x was this case.**

To tell which, compare the two paks rather than trusting the version bump:

```sh
python3 - <<'PY'
import zipfile, io, re, sys
def schema(p):
    z = zipfile.ZipFile(p)
    a = zipfile.ZipFile(io.BytesIO(z.read('adapter.zip')))
    d = a.read('VsanHostMetrics/conf/describe.xml').decode('utf-8', 'replace')
    # NB: `key` is NOT the first attribute on these elements. An earlier
    # version of this snippet anchored on `<ResourceKind key="` and silently
    # found ZERO ResourceIdentifiers, so it compared two empty sets and never
    # checked identity at all -- which is the one dimension that actually
    # forces an uninstall. Match the tag, then the attribute, anywhere in it.
    def keys(tag):
        return set(re.findall(r'<%s\b[^>]*?\bkey="([^"]+)"' % tag, d))
    # identType 1 = part of uniqueness, 2 = informational. A key DEMOTED from
    # 1 to 2 keeps the field in the schema and still changes every computed
    # object identity, so compare the pair rather than the name.
    idents = set(re.findall(
        r'<ResourceIdentifier\b[^>]*?\bkey="([^"]+)"[^>]*?identType="(\d)"', d))
    return (keys('ResourceKind'), keys('ResourceAttribute'),
            keys('CredentialKind'), idents)
old, new = schema(sys.argv[1]), schema(sys.argv[2])
print("schema unchanged" if old == new else "SCHEMA CHANGED -- uninstall first")
PY
```

Pass the old pak then the new one. Do not diff `describe.xml` byte for byte:
the SDK writes the `UnitType` block in a different order on every build, so two
builds of the same schema differ in hundreds of lines while describing exactly
the same 70 resource kinds and 971 attributes. Compare the key sets, as above.

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

## 2b. Give the dashboards two or three collection cycles before judging them

**Observed 2026-10-01 on a fresh install, and it will mislead you if you do not
expect it.** After the pak is installed and the adapter instance created, panels
come alive at different times rather than all at once. Measured on this lab:

| Panel | Rendered after |
|---|---|
| Most | first cycle |
| Network and Storage tables | two cycles |
| zDOM per host | roughly ten minutes, two cycles behind its neighbours |

Nothing was changed between a panel reading "no data" and the same panel
working. It simply arrived.

The reason is that a view traverses from the selected cluster down to its
descendants, so it cannot resolve until **both** the objects exist **and** their
parent relationships have been built. Object creation and relationship creation
do not complete in the same cycle, and different resource kinds land in
different cycles. On a fresh install every object and every relationship is new
at once, which is the worst case for this.

**So: wait fifteen minutes before concluding a panel is broken.** A panel that
is genuinely misconfigured says it needs a view selected. A panel that is merely
waiting renders its headers with no rows. Those two look different, and only the
first is a fault.

## 2c. "The widget is not configured" with an hourglass means WAIT

**Observed 2026-10-05, and it looks exactly like a broken dashboard.** Shortly
after installing, a dashboard can show every widget reading:

> The widget is not configured. Select a view to render.

including the cluster selector, with a small hourglass beside each widget
title. Another dashboard in the same pak renders perfectly at the same moment.

**That is the content import still running, not a fault.** The hourglass is the
in-progress marker. The widgets bind themselves when it completes, with no
action taken and nothing changed. Larger dashboards finish later than small
ones, which is why one screen works while another does not.

The two states are worth telling apart, because they look similar and only one
is a problem:

| What you see | What it means |
|---|---|
| "Widget is not configured", hourglass present | Import still running. **Wait.** |
| "Widget is not configured", no hourglass, settled | The widget genuinely has no view bound |
| "The view cannot be rendered for the specified object" | The view resolved but the selected object is not a valid subject |
| Headers render, no rows | Bound and working, waiting on data or relationships |

Combined with the collection-cycle lag above, **budget fifteen minutes after an
install before investigating anything.** Several hours were spent chasing two
unrelated code defects that this paragraph would have prevented.

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
