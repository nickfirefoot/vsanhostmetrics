# Network requirements — what talks to what

For an environment with egress, but only through an explicit proxy. The
no-egress case is `OFFLINE-DELIVERY.md`, which is a different and harder
problem.

Traced 2026-10-22 by following an actual anonymous pull, not read from
documentation. Where something is inferred rather than measured it says so.

---

## The short version

**Exactly one component needs the internet: the Cloud Proxy, and only to pull
the adapter image.** Nothing else in this pack reaches outside the
environment at any point, including at collection time.

| # | From | To | Port | When | Required |
|---|---|---|---|---|---|
| 1 | Cloud Proxy | `ghcr.io` | 443 | first collection after install | **yes** |
| 2 | Cloud Proxy | `pkg-containers.githubusercontent.com` | 443 | first collection after install | **yes** |
| 3 | Admin workstation | `github.com` | 443 | downloading the `.pak` | no — see below |
| 4 | Admin workstation | `release-assets.githubusercontent.com` | 443 | downloading the `.pak` | no — see below |
| 5 | Adapter container | vCenter | 443 | every collection | yes, **internal** |
| 6 | Adapter container | VCF Operations | 443 | every collection | yes, **internal** |
| 7 | Whoever verifies signatures | `*.sigstore.dev`, `api.github.com` | 443 | optional | no |

### 2 is the one that gets missed

An allowlist containing only `ghcr.io` **will fail**. GHCR serves the registry
API from `ghcr.io` but redirects every blob to a different host:

```
GET https://ghcr.io/v2/<repo>/blobs/sha256:61320b01...
  -> 307 Location: https://pkg-containers.githubusercontent.com/ghcr1/blobs/sha256:61320b01...
```

So the token request and the manifest succeed, the pull looks like it is
starting, and then the layers fail. Both hosts are required.

### 3 and 4 are not really requirements

The `.pak` is uploaded to Operations through a browser by an administrator.
Nothing in the product fetches it. Download it anywhere — a laptop on a guest
network, another site — and carry it in. Only the Cloud Proxy's pull is
load-bearing.

### 5 and 6 are internal, and 6 surprises people

The adapter container talks to vCenter over the vCenter host configured on
the adapter instance, and to **VCF Operations itself** over the suite-api
(`https://<ops-host>/suite-api/`). It needs the latter because
`attach_to_vcenter` reads each vCenter object's existing children before
re-asserting them — see rule 1 in `CLAUDE.md`. Neither leaves the
environment, but a proxy configured as a blanket default route can
accidentally send internal traffic through it.

---

## How it fails today

Honest about confidence: the chain in the table is **measured**; the symptom
below is **partly inferred**, because a blocked pull has not been reproduced
deliberately here. What is measured is the shape of an adapter that cannot
run, observed on 2026-10-21:

```
resourceStatusStates : [{"resourceState": "FAILED"}]
resourceHealth       : GREY
statusMessage        : ""            <- empty, which is the problem
samples              : none
```

**Operations does not tell you the image pull failed.** The adapter instance
goes FAILED, health goes GREY, and the `statusMessage` on the suite-api
payload is an empty string. Alerts on the instance return environment-wide
noise rather than the cause. The actual reason is in the adapter log inside
the Cloud Proxy support bundle, and nowhere else that is easy to reach.

That matters for a proxy problem specifically, because the failure is
indistinguishable at a glance from wrong credentials or an unreachable
vCenter. A fast discriminator:

* **Test Connection passes but collection never starts** — the image is the
  suspect, not the credentials. Test Connection exercises vCenter reachability;
  it does not prove the container was pulled.
* **The pak installs cleanly and the content appears** — dashboards, views and
  new `describe.xml` properties all land **without any egress**, because the
  pak is already on the appliance. Content landing is NOT evidence the image
  was pulled. These two halves fail independently and we have seen them do so.

### The one-line check from the Cloud Proxy

```
curl -sI https://pkg-containers.githubusercontent.com/ 2>&1 | head -1
```

If `ghcr.io` answers and this does not, that is the whole problem.

---

## TLS interception

If the proxy terminates TLS, its CA must be trusted by the **Cloud Proxy**,
because the Cloud Proxy is what performs the pull. Trusting it on the
Operations appliance or on the admin workstation does not help — neither one
pulls the image.

**Unverified here:** whether this appliance honours `HTTP_PROXY`/`HTTPS_PROXY`
from its own configuration for the container-image pull specifically, or
requires the proxy to be set in the Docker daemon configuration. Those are
different settings and the distinction decides where a customer has to put
it. Worth establishing before telling anyone it works.

---

## If there is no egress at all

See `OFFLINE-DELIVERY.md`. The short version is that `docker save`/`load`
does **not** work, because the Cloud Proxy runs the container by RepoDigest
and a loaded image carries no registry association. A reachable registry — the
customer's own is fine — is the recommended path, and the pak's `REGISTRY` and
`REPOSITORY` can be pointed at it.
