# Offline delivery — what works and what does not

Tested 2026-09-23 on the lab Cloud Proxy (VCF Operations Cloud Appliance,
Docker 29.5.3), not inferred. This decides how the pack can be distributed to
an environment with **no registry and no external network**.

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
