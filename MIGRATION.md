# Migrating to 2.0.0

2.0.0 removes the *vCenter username* field (`vcenter_user`) from the adapter
account. The vCenter username now lives only in the account's credential
(credential type *vCenter credential*, `vsan_vc_credential`), as
`vcenter_username` beside `vcenter_password`, and that credential field is now
required. That is the one deliberate break.

In 1.4.7, the released version this upgrades from, `vcenter_user` was a
required identifying field (`required="true" identType="1"`), so **every
existing account has a value in the field 2.0.0 drops**.

What the pak itself shows, comparing the `describe.xml` of 1.4.7 and 2.0.0:

- 70 resource kinds and 1701 metric and property keys (counted per kind),
  none removed and none added;
- one account identifier removed (`vcenter_user`);
- the credential gains `vcenter_username`, required.

No resource kind or metric key is removed, so nothing on the adapter side
orphans an object's history. What Operations did with the upgrade in place is
in [Live upgrade result](#live-upgrade-result) below: accepted on 8.18.7,
9.0.2 and 9.1.1, with accounts, credentials and objects kept.

The 1.5.0 release candidates read the old field as a fallback and logged a
WARNING each cycle. 2.0.0 does not read it at all.

## Do not uninstall 1.x first

The general rule in README section 5 and QUICKSTART section 1 says a schema
change means uninstalling the old pack and deleting its accounts. That rule is
not for this upgrade. Following it means deleting the accounts, and with them
the collected objects and their history; a pak uninstall on Operations has
also been seen to delete the credentials of the adapter kind. Install 2.0.0
over the top; that was accepted on all three Operations versions tested.

## What breaks

An account whose credential has no username stops collecting. Validate
Connection and every collection fail with:

    No vCenter username. Edit the account's credential and enter the
    username with its domain, e.g. vsanmon@vsphere.local.

On that path the adapter attempts no login and deletes nothing: it reports
the error and returns no objects. In the live upgrade the account stayed
started with status ERROR, its objects were kept, and collection resumed after
the username was entered in the credential (see below).

Test Connection on such an account through the public API
(`POST /suite-api/api/adapters/testConnection`) returned HTTP 500 "Internal
Server error, cause unknown." on 8.18.7 and 9.0.2; the adapter's own message
appeared only in the Cloud Proxy's test log. What the UI's Validate
Connection shows in that state was not checked.

Accounts created on 1.4.x have a credential with only a password, so all of
them are in this state until their credential is edited. Accounts given the
username in their credential under a 1.5.0 release candidate do not hit this
error, but they still lose the `vcenter_user` identifier like every other
account.

## Two accounts on the same vCenter now collide

An account's identity is made from its identifying fields. After 2.0.0 those
are:

| Field | Key |
|---|---|
| vCenter Server | `vcenter_host` |
| Verify vCenter certificate | `verify_certs` |
| Metrics to collect | `metric_scope` |
| Attach objects to vCenter inventory | `attach_to_vcenter` |

The username was one of them and no longer is. Two accounts collide when all
four values above are identical, character for character in the vCenter
Server field, and they differed only by username. Two accounts that differ in
any of the four (for example one collecting `dashboard`, the other `all`, or
one by FQDN and one by IP) do not collide. The collision is intended: the same
vCenter collected twice produces the same objects twice.

What to do about a colliding pair is not established. Neither what Operations
does with a pair still present at upgrade time, nor what deleting one of two
accounts that collect the same objects removes (the shared objects, their
history, the credential), has been tested; the live upgrade had one account
per instance. If you have such a pair, do not upgrade it on the strength of
this document.

## Upgrade steps

1. Check for colliding accounts as above. If there are any, stop: that case is
   untested.
2. For each vSAN Host Metrics account on a 1.5.0 release candidate:
   **Administration > Integrations > Accounts**, edit the account, edit its
   credential, enter the username with its domain (e.g.
   `vsanmon@vsphere.local`) and save. On 1.4.x the credential form has no
   username field yet; do this in step 4 instead.
3. Install the 2.0.0 pak over the installed one (Integrations > Repository).
   Do not uninstall 1.x and do not delete the accounts.
4. Edit each account's credential if step 2 was not possible: enter the
   username, click **Validate Connection**, save. Collection resumes on a
   following cycle; on 8.18.7 the adapter container was recreated first.
5. After the next collection, confirm the account shows no error and its
   existing objects receive new values.
6. If *Verify vCenter certificate* is `true`, validate the connection again
   after editing the account and accept vCenter's certificate if prompted (see
   the certificate note below).

## Live upgrade result

v2.0.0-rc.1 (CI-built pak `VsanHostMetrics_2.0.0.pak`, image
`sha256:9a3587e3...55d6`, provenance attestation verified) was installed in
place over 1.5.0-rc.2 on 2026-10-29, on VCF Operations 8.18.7, 9.0.2 and
9.1.1, one account per instance, *Verify vCenter certificate* `false` on all
three. Recorded as seen, through the Suite API and the Cloud Proxy logs:

- **Accepted in place.** The install finished without an uninstall on all
  three, and the solution reported version 2.0.0.
- **Accounts and credentials kept.** Adapter instance id and credential id
  were the same before and after on all three.
- **Objects kept.** Object count and distinct stat keys, before = after:
  8.18.7 655 / 1390, 9.0.2 427 / 1373, 9.1.1 523 / 1401. The pack's 31 views
  and 8 dashboards were still present. On 9.1.1 a stat written before the
  upgrade was still readable after it. On 8.18.7 and 9.0.2 older history was
  not read back; that it is kept is inferred from the unchanged object ids.
- **The identifier is gone.** After the upgrade the account's identifiers
  were `attach_to_vcenter`, `container_memory_limit`, `metric_scope`,
  `vcenter_host` and `verify_certs`; `vcenter_user` and its value were gone on
  all three (Suite API; the UI account page was not checked). The adapter
  logs carry no mention of it.
- **A credential without the now-required username** (8.18.7 and 9.0.2): the
  upgrade was not refused and the credential was kept. The account went
  STARTED / ERROR with "PerfSvcError: No vCenter username. Edit the account's
  credential and enter the username with its domain, e.g.
  vsanmon@vsphere.local." Nothing was deleted and no login was attempted.
  After the username was entered in the credential (edited in place,
  validated, saved), collection resumed: on 9.0.2 in the running container,
  on 8.18.7 after the adapter container was recreated. No ERROR after that.
- **A credential that already had the username** (9.1.1, set under a 1.5.0
  release candidate): Test Connection passed and collection ran with no
  ERROR and no username or `vcenter_user` line in the log.

**Certificate note.** On 9.1.1 the adapter logged "Operations passed 1
certificate(s)" before the upgrade and "0 certificate(s)" after it: the
previously accepted vCenter certificate was no longer handed to the account.
With verification off that changes nothing. With verification on, collection
would fail until the certificate is accepted again, so validate the connection
after editing an account and accept vCenter's certificate if prompted. The
cause (the upgrade, the account edit or the restart) was not isolated.

### Still not tested

- **A direct upgrade from 1.4.7.** The base above was 1.5.0-rc.2, where
  `vcenter_user` was already optional and the credential type already had an
  optional `vcenter_username`. From 1.4.7 the identifier is required and the
  credential field does not exist yet; that path was not installed.
- **Colliding accounts** (see above).
- **Downgrade to 1.4.7** (see Rolling back).

## Rolling back

Not established. Whether Operations accepts the 1.4.7 pak over 2.0.0 (a lower
version over a higher one) has not been tested. 1.4.7 also adds `vcenter_user`
back as a required identifying field, so any account that comes through the
downgrade without a value in it has to be edited, and that edits the
account's identity on a live account, with an outcome that is not known. Treat
rollback as unavailable; the live upgrade did not test it.
