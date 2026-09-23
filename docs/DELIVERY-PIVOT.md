# Delivery: replace the container adapter with a pushing collector

Written 2026-09-23 after proving the container-adapter path cannot meet the
actual requirement. Nothing is built yet; this is the decision and the
evidence for it.

## The requirement

Hand a customer a zip. They deploy it. Metrics inside 24 hours. No firewall
change requests, no registry, no waiting on infrastructure that the monitoring
itself does not need.

## Why the management pack cannot do that

A container management pack does not contain its adapter. The pak is ~145 KB of
schema plus a pointer; the adapter is a ~430 MB container image the Cloud Proxy
pulls from a registry, by **RepoDigest**:

```
Config.Image = registry.example.com/nickfirefoot/vsanhostmetrics@sha256:a2792739...
```

Tested on the lab Cloud Proxy, all negative:

- `docker load` of the saved image does **not** create that RepoDigest
  association, so the image is not found and a pull is attempted anyway.
- Docker there uses the **overlay2** image store, so no digest-preserving
  `ctr` import into Docker's store exists; no skopeo/crane/regctl is installed.
- Editing `REGISTRY`/`DIGEST` in the proxy's `.conf` achieves nothing:
  **Operations owns that file and re-syncs the whole plugin directory**,
  restoring the digest from its own database. Proxy-side workarounds are dead.

So every container management pack -- ours and Broadcom's alike -- requires a
registry the Cloud Proxy can reach. That is a platform constraint, not a defect
in this pack, and it is irreconcilable with "no registry, no firewall tickets".

## What works instead — verified end to end

VCF Operations ships a push adapter kind, `vRealizeOpsMgrAPI`
("VCF Operations API"), with an instance already present by default. A plain
HTTP client can create objects and push metrics into it.

Proven on `operations.example.com`, 2026-09-23:

```
POST /suite-api/api/resources/adapterkinds/vRealizeOpsMgrAPI   -> 201 Created
     resourceKindKey "VsanPushProbe" (arbitrary kind accepted)
POST /suite-api/api/resources/{id}/stats                       -> 200 OK
GET  /suite-api/api/resources/{id}/stats/latest
     vsan|pnic|rxMissErr    = 3.0
     vsan|pnic|rxThroughput = 1156862.0
```

The probe object was deleted afterwards (204). The full surface exists:

| Need | Endpoint |
|---|---|
| Create object | `POST /api/resources/adapterkinds/{adapterKind}` |
| Push metrics | `POST /api/resources/{id}/stats`, bulk `POST /api/resources/stats` |
| Push properties | `POST /api/resources/properties` |
| Relationships | `POST /api/resources/{id}/relationships/{relationshipType}` |

No pak, no registry, no container, no Cloud Proxy.

## What the customer needs

| | |
|---|---|
| A Linux host with Python 3.9+ | can be an existing jump box; no appliance changes |
| Network: collector -> vCenter :443 | the same access any vSAN monitoring needs |
| Network: collector -> Operations :443 | already open wherever the UI is used |
| A vCenter account | **read-only**, propagated from the root |
| An Operations account | able to create resources and push stats |

Two accounts and two already-normal network paths. No registry, no image pull,
no Cloud Proxy involvement, no schema installed into the Operations database.

## What is given up, honestly

- **`describe.xml`.** Units, labels and attribute metadata currently come from
  the pak's generated schema. Pushed metrics carry a `statKey` and a value; in
  the probe the `unit` field was accepted but read back as `None`, so unit
  handling needs its own investigation. The mitigation is that the statKey
  *is* the display path, so readable names can be encoded directly --
  `Network|pNIC|RX missed errors (ring buffer full)` rather than `rxMissErr`.
- **Shipped dashboards.** A pak can carry `content/dashboards`. A pushing
  collector cannot; dashboards would ship as a separate import file.
- **Lifecycle integration.** No adapter instance in the Operations UI, no
  collector-managed scheduling, no Validate Connection button. The collector
  runs under systemd or cron and is managed like any other service.
- **Object typing.** Objects appear under the "VCF Operations API" adapter
  rather than a first-class `VsanHostMetrics` adapter kind.

## What is kept

Everything expensive. `perfsvc.py` imports nothing from the SDK by design, so
the collector, the 31-entity model, the 1035 metric definitions, the labels and
units, the UUID->name resolution and the relationship mapping all carry over
unchanged. Only `adapter.py` -- the thin SDK binding -- is replaced by an HTTP
client.

## Proposed shape of the zip

```
vsan-collector-<version>.zip
  collector/            perfsvc.py, perfsvc_model.py, metric_labels.py, vendor/
  configure.sh          prompts for vCenter + Operations creds, writes config
  install.sh            venv, pip install, systemd unit, enable timer
  README.md             15-minute path from zip to metrics
```

Dependencies are the open question: pyVmomi is needed and is not stdlib, so the
zip either vendors wheels for offline install or the host needs PyPI access.
Vendoring wheels is the honest answer for a disconnected site.
