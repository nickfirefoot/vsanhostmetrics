# Offline delivery — what works and what does not

> **If the environment HAS egress but only through a proxy, you want
> `NETWORK-REQUIREMENTS.md` instead.** That case needs two hostnames
> allowlisted and nothing else. This document is the harder no-egress case.

Tested 2026-09-23 on the lab Cloud Proxy (VCF Operations Cloud Appliance,
Docker 29.5.3), not inferred. This decides how the pack can be distributed to
an environment with **no registry and no external network**.

## Why this problem exists at all: DOCKERIZED vs GENERAL

Measured 2026-10-23 against the lab, and it reframes everything below.

Operations has two adapter architectures, and `/suite-api/api/adapterkinds/<kind>`
reports which one an adapter is:

| adapter | type |
|---|---|
| `VsanHostMetrics` (this pack) | **DOCKERIZED** |
| `VsphereNetStats` | **DOCKERIZED** |
| `VMWARE` | GENERAL |
| `NSXTAdapter` | GENERAL |
| `VirtualAndPhysicalSANAdapter` (Broadcom's vSAN MP) | GENERAL |
| `ManagementPackBuilderAdapter` | GENERAL |

**Everything Broadcom ships is GENERAL. Only Integration SDK packs are
DOCKERIZED.** A GENERAL adapter has no container: the pak IS the whole thing,
so installing it is one file import with no registry, no digest and no
egress. A DOCKERIZED adapter is content plus an image the Cloud Proxy must
pull by RepoDigest, which is the entire subject of this document.

So the airgap difficulty is not a packaging detail this pack can engineer
around. It is a property of the adapter TYPE, chosen when the pack was built
on the Integration SDK. That also explains why Broadcom's own management
packs install cleanly in environments where ours cannot.

**Management Pack Builder produces GENERAL adapters**, which makes it the
only observed route to a container-free pak. Whether THIS pack could be
expressed that way is unknown and probably no: MPB targets REST/JSON-shaped
sources, while this pack needs the vSAN Management API over SOAP at a
separate `/vsanHealth` endpoint, the vendored `vsanmgmtObjects` types that
are absent from pyVmomi, and `entityRefId` grammar parsing. Nothing has been
built with MPB on this lab, so there is no example here to inspect, and its
capabilities are UI-driven rather than visible through the API.

Worth settling before investing in any of the options below, because if MPB
can reach a SOAP endpoint it beats all of them.

## Management Pack Builder: investigated and closed, 2026-10-23

MPB produces GENERAL adapters, so an MPB-built pack has no container and
installs from a single file. That makes it the obvious airgap candidate. It
does not work for this pack, and the reasons are measured rather than assumed.

**MPB offers exactly two source types: HTTP API and PROMETHEUS.**

**HTTP API cannot reach the Performance Service.** Measured against the lab:

    GET /vsanHealth                  501 Not Implemented   (POST-only SOAP)
    GET /vsanhealth                  404                   (path is case-sensitive)
    GET /sdk/vsanServiceVersions.xml 200 text/xml          (version manifest only)

The 501 is the answer: `/vsanHealth` accepts only POST with SOAP envelopes.
Collection would need a SOAP login at `/sdk` holding a session cookie, then
`VsanPerfQueryPerf` envelopes carrying typed `VsanPerfQuerySpec` objects, then
parsing XML whose numbers arrive as CSV strings packed in a `values` field,
repeated across 69 entity types. MPB's "Use Session Authentication" might
cover the login; the rest is a SOAP client with vendored type bindings, which
is why this pack carries `vsanmgmtObjects.py`. A declarative HTTP connector
does not do that.

**PROMETHEUS needs a Prometheus SERVER, not an exposition endpoint.** The
connection dialog takes host, port, base path and credentials -- the shape of
querying a server, not scraping a target. So it would require a Prometheus
deployed and already scraping, which is infrastructure the customer must run
and feed. Not a file import.

**And the only vSAN data in Prometheus format is per-ESXi-host anyway.**
`/vsanmetrics` is served by ESXi (158 metric names, 1912 series), NOT by
vCenter -- confirmed 404 on vc01 for both `/vsanmetrics` and `//vsanmetrics`.
It is also a different dataset: 158 host-level cumulative counters against the
191 columns across 69 entity types these dashboards render, with no per-VM,
per-vSCSI, per-vmknic or per-disk breakdown. Building on it would be a new
pack, not a repackaging.

**Standing constraint, set 2026-10-23: this pack does not interface directly
with ESXi hosts.** vCenter only -- one endpoint, one credential. That closes
the `/vsanmetrics` route permanently regardless of the points above.

## The mechanism

The Cloud Proxy runs the adapter container by **RepoDigest reference**:

```
$ docker inspect dockerized_adapter_VsanHostMetrics_3041
Config.Image = registry.example.com/nickfirefoot/vsanhostmetrics@sha256:a2792739...
RepoDigests  = [registry.example.com/nickfirefoot/vsanhostmetrics@sha256:a2792739...]
```

That reference comes from the pak's `adapter.zip!VsanHostMetrics.conf`
(`REGISTRY` + `REPOSITORY` + `DIGEST`). For the container to start without a
pull, an image carrying **that exact RepoDigest** must already be in the
proxy's image store.

## What does not work: `docker load`

```
$ docker load -i vsan-host-metrics-1.1.10.image.tar
Loaded image ID: sha256:13c695e8...

$ docker images -a --no-trunc | grep vsan
registry.example.com/nickfirefoot/vsanhostmetrics  <none>  sha256:4eacff88...   (older, pulled)
registry.example.com/nickfirefoot/vsanhostmetrics  <none>  sha256:f6439836...   (older, pulled)
                                                     ^ the loaded image is not here
```

No image on the proxy carried RepoDigest `sha256:7d2a5233...` after the load.
`docker save`/`load` transports layers and an image ID; it does **not**
reconstruct the registry association, because that association is a fact about
where the bytes came from, not about the bytes.

The image ID even changes between build host and proxy (`7d2a5233` vs
`13c695e8`), so matching on ID is not a fallback either.

Also ruled out on this appliance:

- **containerd image store** — Docker uses `overlay2`, so a digest-preserving
  `ctr images import` into Docker's store is not available.
- **skopeo / crane / regctl** — none installed; only `ctr`.

## What remains

### 1. A registry the target can reach (recommended where there is egress)

Publish the image to a public registry and point `REGISTRY` at it. The
recipient needs **no registry of their own** — only outbound 443 to it. This
removes the CA-trust and DNS steps entirely and makes the zip small again.
Ruled out here only because the target has no external network.

### 2. A minimal registry on the Cloud Proxy itself (the only zip-only option)

Ship `registry:2` plus our image in the bundle, run the registry bound to
localhost on the proxy, and point the pak's `REGISTRY` at it. No external
network is involved.

**Unverified, and one detail decides whether it is viable:** the pak carries a
fixed `DIGEST`, so whatever the local registry serves must have *the same*
manifest digest. `docker load` followed by `docker push` re-creates the
manifest and will generally produce a **different** digest, which would not
match the pak. Preserving it requires transporting an OCI layout whose
manifest bytes are byte-identical -- e.g. `skopeo copy --all
docker://<src>@sha256:X oci:layout` and serving that layout directly -- rather
than a `docker save` tar.

### 3. Tag-based reference instead of digest [untested, cheap to try]

If the collector accepts a `REGISTRY`/`REPOSITORY` reference without `DIGEST`,
or with a tag, then `docker load` plus `docker tag` would be enough and no
registry is needed at all. `mp-build` always writes `DIGEST`, so this means
hand-editing the `.conf` in a pak and seeing whether the collector honours it.
Cheapest experiment remaining and worth doing before building option 2.

## Consequence for the bundle

`tools/build_release_bundle.py --with-image` produces a 101 MB zip containing
the image tar. **That tar is not currently usable** -- keep the flag for
transporting bytes, but the bundle must not claim an offline install works
until option 2 or 3 is proven. `AIRGAP.md` in the bundle overstates this and
needs correcting.
