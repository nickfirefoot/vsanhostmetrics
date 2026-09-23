#!/usr/bin/env python3
"""Bundle a built .pak with the docs -- and optionally the adapter image.

    python3 tools/build_release_bundle.py [version] [--with-image]

With --with-image the container image is saved into the bundle as a tar, for
targets with no registry and no external network. See AIRGAP.md in the bundle:
the image must be loaded onto the Cloud Proxy before the pak is installed.

Produces dist/VsanHostMetrics-<version>.zip, flat, so unpacking leaves the
.pak beside the README rather than buried in directories.

Why a script and not a zip command: the bundle has to state the image digest
the pak points at, and that digest is only discoverable by opening the pak.
Typing it by hand is how a bundle ends up describing a different build than
the one it contains.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile

PROJECT = os.path.expanduser("~/vsan-host-metrics")
DOCS = ["README.md", "QUICKSTART.md", "REQUIREMENTS.md", "BACKLOG.md",
        "BUGS-UPSTREAM.md", "LICENSE"]


def pak_facts(pak_path):
    """(version, vendor, registry, repository, digest) read from the pak."""
    with zipfile.ZipFile(pak_path) as pak:
        manifest = json.loads(pak.read("manifest.txt"))
        with zipfile.ZipFile(io.BytesIO(pak.read("adapter.zip"))) as adapter:
            conf = adapter.read("VsanHostMetrics.conf").decode()
    fields = dict(line.split("=", 1) for line in conf.strip().splitlines()
                  if "=" in line)
    return (manifest["version"], manifest.get("vendor", ""),
            fields.get("REGISTRY", ""), fields.get("REPOSITORY", ""),
            fields.get("DIGEST", ""))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def airgap_doc(version, registry, repository, digest, tar_name):
    return f"""# Offline install — no registry, no external network

This bundle carries the adapter container image alongside the pak, for targets
that cannot reach any registry.

## Why this step exists

A VCF Operations container management pack does not contain its adapter. The
pak is ~145 KB of schema and a pointer; the adapter is a ~430 MB container
image. Normally the Cloud Proxy pulls that image from a registry. With no
registry and no egress, the image has to be placed on the Cloud Proxy by hand
**before** the pak is installed.

| | |
|---|---|
| Image | `{registry}{repository}` |
| Digest | `{digest}` |
| Tar | `{tar_name}` |

## Steps, on the Cloud Proxy

SSH is disabled by default on the appliance. Enable it from the VM console:

```sh
systemctl enable --now sshd
```

Copy the tar over and load it:

```sh
scp {tar_name} root@<cloud-proxy>:/tmp/
ssh root@<cloud-proxy> 'docker load -i /tmp/{tar_name}'
```

Confirm the image is present. The loaded image ID must equal the digest above:

```sh
docker images --no-trunc | grep -i vsan
```

Then install the pak in Operations
(**Administration → Integrations → Repository → Add**), tick both boxes, and
create the adapter instance against that Cloud Proxy.

Consider disabling SSH again afterwards.

## Status of this procedure — READ THIS

**[unverified]** Loading the image locally is necessary, but whether the
collector will *use* a locally loaded image instead of attempting a registry
pull has not yet been confirmed on a real Cloud Proxy.

What is known, tested on the build host:

- `docker save` then `docker load` restores the image with ID
  `{digest}` — the same value the pak references.
- It does **not** restore the repository/digest association
  (`docker images --digests` shows none), so a literal
  `docker pull <registry>/<repo>@<digest>` would still go to the network.

So this works if the collector resolves the image locally first, and fails if
it always resolves through the registry reference. If it fails, the symptom
will be an adapter instance that installs cleanly and then reports
`Dockerized adapter API client error` with no objects collected.

If you hit that, say so — the fallback is to run a minimal local registry on
the Cloud Proxy itself, which needs no external network but is more moving
parts than a `docker load`.
"""


def save_image(registry, repository, digest, dest):
    """docker save the image the pak points at, for offline delivery.

    Pulls by digest first so the tar contains exactly the bytes the pak
    references, rather than whatever happens to be tagged locally.
    """
    import subprocess
    ref = f"{registry}{repository}@{digest}"
    subprocess.run(["docker", "pull", ref], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["docker", "save", "-o", dest, ref], check=True)
    return os.path.getsize(dest)


def main() -> None:
    builds = os.path.join(PROJECT, "build")
    paks = sorted(f for f in os.listdir(builds) if f.endswith(".pak"))
    if len(sys.argv) > 1:
        paks = [f for f in paks if sys.argv[1] in f]
    if not paks:
        raise SystemExit("no matching .pak in " + builds)
    pak_name = paks[-1]
    pak_path = os.path.join(builds, pak_name)
    version, vendor, registry, repository, digest = pak_facts(pak_path)

    os.makedirs("dist", exist_ok=True)
    out = os.path.join("dist", f"VsanHostMetrics-{version}.zip")

    readme = f"""# vSAN Host Metrics {version} — deployment bundle

Long-term vSAN telemetry for VCF Operations, collected from the vSAN
Performance Service through vCenter.

| | |
|---|---|
| Version | **{version}** |
| Pak | `{pak_name}` |
| Vendor | {vendor} |
| Adapter image | `{registry}{repository}` |
| Image digest | `{digest}` |
| Pak SHA-256 | `{sha256(pak_path)}` |

## Start here

**Read `QUICKSTART.md` first.** It is the shortest correct path from nothing to
a collecting adapter.

## The one network requirement

This pak does not contain the adapter code. It is ~145 KB of schema and a
pointer to the container image above; the adapter itself is a ~100 MB image.
Operations installs the schema, and the **Cloud Proxy** pulls that image once
per version.

So the Cloud Proxy needs **outbound 443 to `{registry}`**. That is the whole
network ask. It is a public registry with a publicly trusted certificate, so
there is no CA to install and no DNS to add.

If your Cloud Proxy has no internet access at all, see `docs/OFFLINE-DELIVERY.md`
— that case needs a registry inside your environment, and it is the same for
any container-based management pack.

## What it collects

One vCenter connection on 443. No ESXi access, no host credentials, no
per-host firewall rules. A **read-only** vCenter account is sufficient.

A four-host cluster produced 847 objects across 31 resource kinds and 1035
metrics. Every object attaches to the vCenter host, VM or cluster it belongs
to, so vSAN metrics appear under objects already in your inventory.

## Files

| File | What it is |
|---|---|
| `{pak_name}` | the management pack |
| `QUICKSTART.md` | deploy from scratch — **start here** |
| `README.md` | this file, plus the full metric reference |
| `REQUIREMENTS.md` | versions, network, credentials, repeatability checklist |
| `BACKLOG.md` | known gaps and open decisions, including per-mille ratios |
| `BUGS-UPSTREAM.md` | defects found in Broadcom's own endpoints |
| `SHA256SUMS.txt` | checksums for everything here |

## Status

Dashboards and alert content are **not** included — `content/` ships empty.
Thresholds are deliberately deferred pending data runs. See `BACKLOG.md`.

Verified against VCF Operations 9.x. **8.x is unverified** despite the
manifest's 8.10.0 floor; see `QUICKSTART.md` section 7 for everything else
untested.
"""

    staged = {}
    staged[pak_name] = pak_path
    tmp_readme = os.path.join("dist", "_README.md")
    with open(tmp_readme, "w") as fh:
        fh.write(readme)

    want_image = "--with-image" in sys.argv
    image_tar = None
    if want_image:
        image_tar = os.path.join("dist", f"vsan-host-metrics-{version}.image.tar")
        size = save_image(registry, repository, digest, image_tar)
        print(f"  saved image tar: {size/1024/1024:.0f} MB")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pak_path, pak_name)
        if image_tar:
            z.write(image_tar, os.path.basename(image_tar))
            z.writestr("AIRGAP.md", airgap_doc(version, registry, repository,
                                               digest, os.path.basename(image_tar)))
        z.writestr("README.md", readme)
        sums = [f"{sha256(pak_path)}  {pak_name}"]
        if image_tar:
            sums.append(f"{sha256(image_tar)}  {os.path.basename(image_tar)}")
        for doc in DOCS:
            if not os.path.exists(doc):
                continue
            name = "REFERENCE.md" if doc == "README.md" else doc
            z.write(doc, name)
            sums.append(f"{sha256(doc)}  {name}")
        z.writestr("SHA256SUMS.txt", "\n".join(sums) + "\n")
    os.remove(tmp_readme)

    size = os.path.getsize(out)
    print(f"  wrote {out}  ({size/1024:.0f} KB)")
    with zipfile.ZipFile(out) as z:
        for n in z.namelist():
            print(f"     {n:42} {z.getinfo(n).file_size:>9} bytes")


if __name__ == "__main__":
    main()
