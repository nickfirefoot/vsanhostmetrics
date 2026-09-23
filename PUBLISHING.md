# Publishing this pack so people can verify it

Written 2026-09-23. Nothing here has been executed -- publishing is outward
facing and irreversible, so it needs a deliberate decision, not a default.

The goal is not just "the code is on GitHub". Anyone installing a management
pack is granting it a read-only vCenter account and running a container inside
their monitoring estate. "Trust me" is not an answer. What follows is what it
takes for a stranger to check the claim themselves.

---

## 0. The problem nobody mentions: the pak does not contain the code

A `.pak` is mostly a pointer. The adapter logic lives in a **container image**,
and the pak only records where to find it:

```
REGISTRY=registry.example.com
REPOSITORY=/nickfirefoot/vsanhostmetrics
DIGEST=sha256:9865943538...
```

Two consequences:

1. **The published pak is unusable to outsiders as-is.** `registry.example.com` is
   a private lab name that resolves nowhere else. Anyone downloading a release
   artifact gets a pak whose image cannot be pulled.
2. **Reading the GitHub source tells you nothing about what the pak runs.** The
   digest could point at an image built from entirely different code. Source
   and artifact are only connected if someone *makes* them connected.

So publishing the repository is necessary and nowhere near sufficient.

## 1. Decide what you are actually distributing

| Option | What the user gets | What they must trust |
|---|---|---|
| **Source only** | A repo; they run `mp-build` themselves against their own registry | Only the source, which they can read. Strongest position, most work for them |
| **Source + public image** | Image on a public registry (GHCR), pak references it | The image matches the source -- provable with attestation, see section 4 |
| **Pak as a release asset** | Download and install | Everything, unless sections 3-4 are done |

Recommended: **source + public image on GHCR**, with the pak as a release asset
whose digest matches an attested build. The lab Harbor stays for iteration; it
should never be the address in a published pak.

## 2. Before anything becomes public

- [x] **History scanned for credentials.** Done 2026-09-23 across all 265 blobs
      in all 50 commits: bearer tokens, `password=`, `auth_token`, private keys,
      Harbor robot accounts, `Authorization:` headers. Two matches, both
      deliberate documentation placeholders -- `robot$project+name` and
      `Bearer definitely-not-a-real-token`. **No real credential has ever been
      committed.** Credentials live in `~/*.env` at mode 600, outside the repo.
- [ ] **Re-run that scan immediately before publishing** -- it is only true as
      of the commit it was run against. `tools/scan_history.py`.
- [ ] **Decide about lab identifiers.** The repo names `example.com`, RFC1918
      addresses, host and cluster UUIDs. None are secrets and the lab is
      disposable, but they do describe an internal topology. Leaving them is
      defensible; it makes the docs concrete and the evidence checkable.
- [ ] **Add a LICENSE.** Without one the default is "no rights granted", which
      makes the repo unusable to exactly the careful people you want.
- [ ] **Keep the vendored vSAN bindings honest.** `app/vendor/` contains
      Broadcom's 2021 `vsanmgmtObjects.py` and `vsanapiutils.py`, redistributed.
      Check their license permits it and attribute them in the LICENSE file.
      This is the one genuine legal question here.

## 3. Branch and history

The work is on `agent/beta-vsan-host-metrics`; `main` has never been touched,
per the standing fence. Publishing means deciding what `main` becomes.

Keep the full history rather than squashing. Fifty commits that show a defect
being found, reproduced and fixed are *evidence of process*. A single "initial
commit" dropping 5,000 lines is the shape supply-chain attacks come in.

## 4. Making the artifact verifiable -- the part that actually matters

This is what separates "published" from "auditable".

**Sign the commits and tags.** Unsigned commits carry an author field anyone can
type. `git config commit.gpgsign true` (currently unset), or use SSH signing.

**Build in public CI, not on this box.** A GitHub Actions workflow that checks
out the tag, runs `mp-build`, pushes to `ghcr.io`, and attaches the pak to the
release means the artifact's provenance is a public log entry rather than an
assertion. Nobody has to trust the build host.

**Emit a provenance attestation.** `actions/attest-build-provenance` signs a
statement binding the image digest to the exact commit and workflow that built
it. A user then runs:

```sh
gh attestation verify oci://ghcr.io/<owner>/vsan-host-metrics@sha256:<digest> \
  --owner <owner>
```

and gets a cryptographic answer to "was this image built from that source",
which is precisely the question section 0 leaves open.

**Publish the pak's digest in the release notes**, and make the workflow fail
if `adapter.zip!VsanHostMetrics.conf` disagrees with the image it just pushed.

**Say plainly that the pak is unsigned.** Installing it requires ticking
*Ignore the PAK file signature checking* -- Broadcom signing is not available
here. Users should be told that up front rather than discovering it mid-install.

## 5. What to write for a reader who is deciding whether to trust it

Most of this already exists and only needs pointing at:

- **What it collects and from where** -- one vCenter on 443, read-only, no ESXi
  access. `REQUIREMENTS.md` section 3.
- **What privileges it needs, and why that little** -- read-only propagated
  from the vCenter root.
- **What it does with the data** -- writes to Operations; the adapter never
  calls back into the Suite API and makes no other outbound connection.
- **Known defects, including its own** -- `BACKLOG.md` and `BUGS-UPSTREAM.md`.
  A project honest about its own bugs is easier to trust than one with none.
- **How to reproduce every claim** -- `REQUIREMENTS.md` section 5.
- **SECURITY.md** -- where to report something privately.

## 6. Tooling note

`gh` is not installed on this build host (`git` and `docker` are). Anything in
section 4 needs it, or needs to run in Actions where it is preinstalled.
