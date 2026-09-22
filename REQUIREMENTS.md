# REQUIREMENTS

Everything needed to build, stage and deploy this management pack, in one
place. Versions below are what the pack was **verified against**, not minimums
— where something is a genuine floor it says so.

Anything marked **[unverified]** is believed true but was not tested. Treat
those as the first things to check if a rebuild misbehaves.

Last verified end-to-end: **2026-09-22**, against `example.com`.

---

## 1. Build host

A throwaway Linux VM. Nothing here is precious; rebuild rather than repair.

| Component | Verified | Notes |
|---|---|---|
| OS | Ubuntu 24.04 | Photon/RHEL should work, untested **[unverified]** |
| CPU / RAM / disk | 2 vCPU / 4 GB / 40 GB | Docker images are ~400 MB each and accumulate |
| Python | 3.12.3 | SDK floor is 3.9 |
| Docker | 29.1.3 | Must run as the build user, not just root |
| SDK CLI | `vmware-aria-operations-integration-sdk` **1.3.1** | provides `mp-init`, `mp-test`, `mp-build` |
| Adapter lib (in container) | `vmware-aria-operations-integration-sdk-lib` **~=1.1.0** | pinned by the generated `adapter_requirements.txt` |
| Base image | `base-adapter:python-1.2.0` | built automatically by the SDK |

```sh
sudo apt update && sudo apt install -y python3-venv python3-pip docker.io
sudo usermod -aG docker "$USER" && newgrp docker
python3 -m venv ~/.mp && source ~/.mp/bin/activate
pip install vmware-aria-operations-integration-sdk==1.3.1
```

### Build-host quirks that cost real time

**`docker` group membership needs a new login.** `mp-init` failing on Docker is
usually a shell that predates `usermod -aG`, not a Docker problem.

**`python3-venv` may be missing, and that breaks `mp-init` destructively.**
`mp-init`'s last step is `venv.create(..., with_pip=True)`. Without `ensurepip`
that raises `SystemExit`, which `mp-init` catches in a broad
`except (KeyboardInterrupt, Exception, SystemExit)` and responds to by
`shutil.rmtree`-ing the project it just generated — so a failed run leaves
nothing behind and no obvious cause. Either install `python3.12-venv`, or use
`scaffold_project.py` in this repo, which drives the same generator and skips
only the venv step. The venv is an IDE convenience; `mp-test` and `mp-build`
run the adapter in a container built from `adapter_requirements.txt`.

Blast radius of that delete is bounded: `NewProjectDirectoryValidator` refuses
any path that already exists and is non-empty, so only the scaffold `mp-init`
itself just created can be removed.

---

## 2. Target environment

| Component | Verified | Notes |
|---|---|---|
| ESXi | **9.1.1.0.25714478** | `/vsanmetrics` endpoint; see `BUGS-UPSTREAM.md` |
| VCF Operations | 9.x | pak install via Administration → Integrations → Repository |
| Cloud Proxy | VCF Operations Cloud Appliance, Photon OS 5.0 | runs the adapter container; Docker + containerd active |
| Registry | Harbor **2.15.2+vmware.1-vks.1** as a Supervisor Service | any OCI registry both the build host and Cloud Proxy can reach works |

The registry does not have to be Harbor. It has to be reachable from the build
host (to push) and from the Cloud Proxy (to pull), with TLS both trust.

---

## 3. Network requirements

These are the ones that actually bite. Each was a real failure during bring-up.

| From | To | Why |
|---|---|---|
| Build host | ESXi host `:443` | `mp-test` scrapes `/vsanmetrics` directly |
| Build host | registry `:443` | `mp-build` pushes the image |
| Cloud Proxy | registry `:443` | pulls the adapter image by digest |
| Cloud Proxy | ESXi hosts `:443` | the adapter scrapes from inside the container |
| **Supervisor workload network** | **internet `:443`** | **only if the registry is a Supervisor Service** |

### The workload-network trap

If Harbor runs as a Supervisor Service, its images are pulled by the **ESXi
image fetcher**, which is a CRX VM (`/var/run/crx/imgfetcher-*`) attached to
the **Supervisor workload network** — not the ESXi management network. On
`example.com` that was `<workload-net-ip>/24` via gateway `<workload-net-ip>` on
`dvportgroup-8016`.

Consequence: every shell-based reachability test on an ESXi host (`nc`,
`openssl s_client`) sources from the management network and **passes while the
fetcher fails**. Do not use them to validate this path. To test it honestly,
source traffic from the workload subnet.

On `example.com` the failure was a firewall auto-blocking newly-discovered
devices. Each fetcher is a fresh MAC living ~90 seconds, so they could never
age into being trusted, and per-device allow rules could never catch them. The
fix has to be scoped to the network, not to devices.

### DNS and TLS

- The registry must be reachable **by hostname**. Harbor's generated cert has a
  DNS SAN and **no IP SAN**, so the bare IP always fails verification.
- An A record must exist before anything pulls. `/etc/hosts` is fine for a
  build host and useless for the Cloud Proxy.
- The Cloud Proxy must trust the registry CA — see `README.md` deploy step 3.
  Without it the pull fails on cert verification with no useful signal in the
  Operations UI.
- ESXi and Photon trust stores lack **DigiCert Global Root G3**, so they report
  verification errors against Broadcom's own endpoints while Ubuntu verifies
  cleanly. Not a blocker for this pack, but it will confuse any TLS debugging
  done from those hosts.

---

## 4. Credentials

| Credential | Used by | Stored | Scope |
|---|---|---|---|
| ESXi bearer token | the adapter, at collection time | Operations adapter instance | **cluster-wide** (verified) |
| Registry push credential | `mp-build` on the build host | `~/harbor.env`, mode 600, **outside this repo** | project-scoped robot recommended |
| Registry pull credential | Cloud Proxy | `/root/.docker/config.json` on the proxy | pull-only is sufficient |
| Operations admin | pak install | not stored | UI or API |

Get the ESXi token, on any host in the cluster:

```sh
configstorecli config current get -c vsan -g system -k vsan
# -> metric_subscriptions[0].auth_token
```

**No credential belongs in this repo.** `mp-test connect` writes the bearer
token as plaintext JSON into `connections.json` in the *SDK project* directory,
which is deliberately outside this repo and gitignored there. Do not relocate
the SDK project inside this repo.

Harbor robot accounts are named `robot$project+name`. **Quote it** — an
unquoted `$project` is eaten by shell expansion and produces a baffling
`unauthorized` from `docker login`.

---

## 5. Repeatability checklist

In order. Each step is verifiable before the next, which is the point.

1. Build host prerequisites installed; `docker ps` works as the build user
2. `python3 test_vsanmetrics.py` → **8/8**. If not, stop — the rate math is
   wrong and nothing downstream matters
3. `curl -sk -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOK" https://<esxi>/vsanmetrics` → **200**
4. SDK project created (`scaffold_project.py` or `mp-init`), adapter files
   copied in, container builds
5. `mp-test -c <conn> collect` **twice** — run 1 emits no rates *by design*
   (counters have no baseline); run 2 emits one `VsanHostTcpIp` object with
   9 rates + 4 percentages
6. Registry reachable by hostname from the build host, TLS verifying
7. `mp-build --no-ttl` → image pushed, `.pak` produced, digest in the pak's
   `.conf` matching the registry artifact
8. Cloud Proxy: DNS resolves the registry, CA trusted, `docker pull` by digest
   succeeds and reports the same digest
9. Pak installed, collector restarted, adapter instance created against the
   Cloud Proxy as collector
10. Objects appear with real identifiers — not `unknown`, not a hostname
    fallback

Steps 1-8 were verified on 2026-09-22. Steps 9-10 **[unverified]**.

---

## 6. Known-good versions, for pinning

```
vmware-aria-operations-integration-sdk==1.3.1      # build host CLI
vmware-aria-operations-integration-sdk-lib~=1.1.0  # in-container, set by the scaffold
base-adapter:python-1.2.0                          # built by the SDK
```

The adapter itself is **stdlib-only** — nothing to add to
`adapter_requirements.txt`. That is deliberate: `vsanmetrics.py` has no SDK
imports and runs anywhere, so the logic can be tested without any of the above.
