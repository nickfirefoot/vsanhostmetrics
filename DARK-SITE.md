# Installing where the Cloud Proxy cannot reach the internet

The pak is small and travels fine by scp. The **container image** does not: the
pak records where to fetch it, and the Cloud Proxy pulls it at install time. A
proxy with no route to `ghcr.io` fails there, and the failure looks like a
management-pack problem rather than a network one.

The fix is to mirror the image into a registry the proxy can reach and tell
Operations to look there. No rebuild, no change to the pak.

## What the pak actually asks for

Inside `adapter.zip`, `VsanHostMetrics.conf`:

    REGISTRY=ghcr.io
    REPOSITORY=/nickfirefoot/vsanhostmetrics
    DIGEST=sha256:2c5b4a7294540e8ca4ea4ff2683a0a37fce8dbf4dfed6e0ebbb3e73fb1eb299c

The image pulled is `{REGISTRY}{REPOSITORY}@{DIGEST}`. Only `REGISTRY` changes.

## 1. Mirror the image, from a host that can reach both

    docker pull ghcr.io/nickfirefoot/vsanhostmetrics@sha256:2c5b4a7294540e8ca4ea4ff2683a0a37fce8dbf4dfed6e0ebbb3e73fb1eb299c
    docker tag  ghcr.io/nickfirefoot/vsanhostmetrics@sha256:2c5b4a7294540e8ca4ea4ff2683a0a37fce8dbf4dfed6e0ebbb3e73fb1eb299c \
                registry.example.local/nickfirefoot/vsanhostmetrics:1.4.6
    docker push registry.example.local/nickfirefoot/vsanhostmetrics:1.4.6

Keep the path after the registry host identical to `REPOSITORY`, because
Operations joins the two literally.

`docker tag` and `docker push` do not rewrite the manifest, so the **digest is
preserved** and the pull by digest still resolves. That is the point: the proxy
gets a byte-identical image, and you can prove it did.

## 2. Install the pak

Normally, through the UI. The image pull will fail until step 3.

## 3. Point Operations at your registry

Edit on **every cluster node** -- NOT on the Cloud Proxy. `docs/DELIVERY-PIVOT.md`
records a tested negative: editing `REGISTRY`/`DIGEST` in the **proxy's** copy
achieves nothing, because Operations owns that file and re-syncs the whole
plugin directory, restoring the values from its own database. The cluster nodes
are the source; the proxy is a replica.


    $VCOPS_BASE/user/plugins/inbound/VsanHostMetrics.conf

Change only:

    REGISTRY=registry.example.local

Leave `REPOSITORY` and `DIGEST` alone. Changing the digest means you are no
longer running the image that was built and tested.

## 4. Restart the collector on each Cloud Proxy

    service collector restart

## Before you blame the management pack

Prove the pull by digest **on the proxy itself**, before installing:

    docker pull registry.example.local/nickfirefoot/vsanhostmetrics@sha256:2c5b4a72...

If that fails, nothing about the pak matters yet. Two causes dominate:

- **The proxy does not trust your registry's CA.** Put it in
  `/etc/docker/certs.d/<registry>/ca.crt`.
- **The registry is reached by IP rather than hostname.** Most registry
  certificates carry a DNS SAN and no IP SAN, so an IP fails hostname matching
  and the error is indistinguishable from an untrusted chain.

## Provenance

The `REGISTRY` override, the `$VCOPS_BASE/user/plugins/inbound/` location and
`service collector restart` are the procedure documented by the VCF Operations
vCommunity management pack, which solves the same problem the same way:
https://github.com/vmbro/VCF-Operations-vCommunity/blob/main/docs/dark-site.md

The `.conf` contents above are read from our own built pak and are exact.
The proxy-versus-cluster distinction above IS tested (2026-09-23, recorded in
docs/DELIVERY-PIVOT.md) and is the trap worth knowing: a proxy-side edit looks
like it worked and is silently reverted.

**The filesystem path and the restart command have NOT been tested against this
pack on a real deployment** -- they are adopted from a pack that shares the
format. If the path differs on your build, say so and this gets corrected
rather than left to be discovered.
