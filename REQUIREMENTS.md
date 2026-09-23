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

Verified 2026-09-23 against `example.com`.

**Runtime needs exactly one destination: vCenter on 443.** The adapter opens no
other connection. Confirmed by reading every outbound call in the active path
(`perfsvc.connect` -> `SmartConnect`, and `get_endpoints` which only echoes the
same URL), and confirmed in production: the deployed instance collects 848
objects with `vcenter_host=vcenter.example.com` and no host credentials at all.

The vSAN Performance Service is reached over the *same* connection -- the vSAN
management endpoint is a path (`/vsanHealth`) on vCenter's 443, not a separate
port. No extra rule is needed for it.

| From | To | Port | Why | Verified |
|---|---|---|---|---|
| Cloud Proxy | **vCenter** | 443 | the only runtime dependency: login, inventory, Performance Service | yes -- instance collecting, `lastCollected` current |
| Cloud Proxy | registry | 443 | pulls the adapter image by digest, once per version | yes |
| Build host | vCenter | 443 | `mp-test` and the model generator query live | yes -- TCP open, API reachable |
| Build host | registry | 443 | `mp-build` pushes | yes -- manifest HTTP 200 |
| Supervisor workload network | internet | 443 | **only** if the registry is a Supervisor Service | yes -- see below |

**No longer required:** any path to ESXi hosts. The host-scrape path is dormant
(`docs/COLLECTION-DESIGN.md`), so the firewall surface is one vCenter rather
than every host in every cluster. That is the main operational argument for the
Performance Service rebuild at fleet scale -- one rule per site, not N.

### vCenter certificate

`Verify vCenter certificate` defaults to **true and does not work unmodified**.
vCenter presents a VMCA-issued certificate:

```
subject= CN = vcenter.example.com
issuer = CN = CA, DC = vsphere, DC = local
Verify return code: 21 (unable to verify the first certificate)
```

Nothing in the adapter's base image trusts the VMCA, so a stock install that
accepts the defaults fails with `CERTIFICATE_VERIFY_FAILED`. Either import the
VMCA root from `https://<vcenter>/certs/download.zip` into the container trust
store, or set the field to false. If left true the field must hold the **FQDN**
-- an IP fails hostname matching even once the root is trusted. The adapter's
error message names both causes; see `README.md` step 6.

### If you host the image on a private registry inside vSphere

Only relevant if you choose to mirror the adapter image into a registry that
runs *as a Supervisor Service* rather than pulling from a public one. Recorded
because it cost a day to diagnose.

Such a registry's own images are pulled by the **ESXi image fetcher**, which is
a CRX VM (`/var/run/crx/imgfetcher-*`) attached to the **Supervisor workload
network** -- not the ESXi management network.

Consequence: every shell-based reachability test on an ESXi host (`nc`,
`openssl s_client`) sources from the management network and **passes while the
fetcher fails**. Do not use them to validate that path. To test it honestly,
source traffic from the workload subnet. Each fetcher is also a fresh MAC
living about ninety seconds, so any firewall policy that auto-blocks unknown
devices will block them permanently and no per-device allow rule can ever
catch up -- the rule has to be scoped to the network.

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
| **vCenter account** | the adapter, at collection time | Operations adapter instance (credential) | read-only, propagated from the vCenter root |
| ESXi bearer token | dormant host path only -- not used at runtime | n/a | **cluster-wide** (verified) |
| Registry push credential | `mp-build` on the build host | `~/harbor.env`, mode 600, **outside this repo** | project-scoped robot recommended |
| Registry pull credential | Cloud Proxy | `/root/.docker/config.json` on the proxy | pull-only is sufficient |
| Operations admin | pak install | not stored | UI or API |

Get the ESXi token, on any host in the cluster:

```sh
configstorecli config current get -c vsan -g system -k vsan -n
# -> metric_subscriptions[].auth_token
```

**The `-n` is required.** Without it the value comes back masked, and a masked
token fails authentication as a 403 rather than anything that says "bad
credential". Confirm with a 200 before using it:

```sh
curl -sk -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOK" https://<esxi>/vsanmetrics
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
Verified end-to-end 2026-09-23 against `example.com`.

1. Build host prerequisites installed; `docker ps` works as the build user
2. `python3 test_perfsvc.py` -> **21/21** and `python3 test_vsanmetrics.py` ->
   **16/16**. If not, stop
3. vCenter reachable and the account can read the Performance Service:
   ```sh
   python3 -c "import sys;sys.path[:0]=['app','app/vendor'];import perfsvc,os;\
   si,c,m=perfsvc.connect(os.environ['VC_HOST'],os.environ['VC_USER'],os.environ['VC_PASS'],False);\
   o,p=perfsvc.collect(m['vsan-performance-manager'],c[0]);print(len(o),'objects',len(p),'problems')"
   ```
   Expect **847 objects, 0 problems** on a 4-host cluster; any cluster should
   return hundreds and zero problems. Zero objects raises `PerfSvcError`
   deliberately rather than reporting an empty success
4. SDK project created (`scaffold_project.py`, **not** `mp-init` -- it
   self-deletes its project on this host), adapter files copied in
5. Icon regenerated if the artwork changed:
   `python3 tools/make_pak_icon.py docs/assets/pak_icon_source.png pak_icon.png`
   -- asserts 256x256 PNG, which `mp-build` does not check
6. `version` bumped in `manifest.txt` -- Operations handles same-version
   reinstalls badly
7. Registry reachable by hostname from the build host, TLS verifying
8. `mp-build --no-ttl` -> image pushed, `.pak` produced. Confirm the digest in
   `adapter.zip!VsanHostMetrics.conf` resolves in the registry:
   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' -u "$HARBOR_USER:$HARBOR_PASS" \
     -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
     "https://<registry>/v2/<project>/<repo>/manifests/sha256:<digest>"   # -> 200
   ```
9. Cloud Proxy: DNS resolves the registry, CA trusted, `docker pull` by digest
   returns the same digest
10. Pak installed; adapter instance created **against the Cloud Proxy** as
    collector, with `Verify vCenter certificate` false (see section 3)
11. Objects appear with real names -- not UUIDs. Verified through the
    Operations API rather than by eye:
    ```sh
    curl -sk -H "Authorization: vRealizeOpsToken $TOK" \
      "https://<ops>/suite-api/api/resources?pageSize=10000" \
    | python3 -c "import sys,json,collections;r=[x for x in json.load(sys.stdin)['resourceList'] \
      if x['resourceKey'].get('adapterKindKey')=='VsanHostMetrics'];\
      print(len(r),collections.Counter(x['resourceStatusStates'][0]['resourceStatus'] for x in r))"
    ```
    Expect every object `STARTED` / `DATA_RECEIVING`.

Step 11 evidence, 2026-09-23: **848 objects across 32 resource kinds, all
`DATA_RECEIVING`** -- the 847 the collector produces plus the adapter instance
object, matching a local `perfsvc.collect()` exactly. Names resolve to
`esxi01.example.com [vmnic0]`, `NVMe INTEL SSDPE2KE016T8 00011773C1E4D25C
(esxi04.example.com)`, `license02 [scsi0:0]`.

Known exception: `VsanVirtualDisk` objects still name themselves by UUID --
they are CNS volumes whose filenames genuinely are UUIDs. See `BACKLOG.md`.

## 6. Known-good versions, for pinning

```
vmware-aria-operations-integration-sdk==1.3.1      # build host CLI
vmware-aria-operations-integration-sdk-lib~=1.1.0  # in-container, set by the scaffold
base-adapter:python-1.2.0                          # built by the SDK
```

The adapter itself is **stdlib-only** — nothing to add to
`adapter_requirements.txt`. That is deliberate: `vsanmetrics.py` has no SDK
imports and runs anywhere, so the logic can be tested without any of the above.
