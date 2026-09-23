#!/usr/bin/env python3
"""Bundle a built .pak with the docs needed to deploy it.

    python3 tools/build_release_bundle.py [version]

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

## Read this before you plan anything

**This pak is not portable.** It does not contain the adapter code — it
contains a *pointer* to the container image above, which is roughly 99 MB and
lives in a registry. The pak itself is ~145 KB and holds only the schema,
labels and icon.

Operations installs the schema; the **Cloud Proxy** pulls that image and runs
it. So `{registry}` must be reachable and trusted **from your Cloud Proxy**. If
it is not — and if it is not your registry, it is not — you must rebuild
against a registry of your own. `QUICKSTART.md` section 2 covers it.

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

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pak_path, pak_name)
        z.writestr("README.md", readme)
        sums = [f"{sha256(pak_path)}  {pak_name}"]
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
