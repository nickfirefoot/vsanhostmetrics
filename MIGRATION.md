# Migrating to 2.0.0

2.0.0 removes the *vCenter username* field (`vcenter_user`) from the adapter
account. The vCenter username now lives only in the account's credential
(credential type *vCenter credential*, `vsan_vc_credential`), as
`vcenter_username` beside `vcenter_password`. That is the one deliberate
break. Every resource kind and metric key is unchanged, so object history
carries over. Compared with the `describe.xml` of 1.5.0-rc.3: 70 resource
kinds and 1701 metric and property keys (counted per kind), none removed, none
added; one identifier removed.

The 1.5.0 release candidates read the old field as a fallback and logged a
WARNING each cycle. 2.0.0 does not read it at all.

## What breaks

An account whose credential has no username stops collecting. Validate
Connection and every collection fail with:

    No vCenter username. Edit the account's credential and enter the
    username with its domain, e.g. vsanmon@vsphere.local.

No login is attempted and nothing is deleted: the account, its objects and
their history stay as they are, and collection resumes on the next cycle after
the username is entered.

Accounts created on 1.4.x have a credential with only a password, so all of
them are in this state until they are edited. Accounts that were already given
the username in their credential under a 1.5.0 release candidate are not
affected.

## Two accounts on the same vCenter now collide

An account's identity is made from its identifying fields. After 2.0.0 those
are:

| Field | Key |
|---|---|
| vCenter Server | `vcenter_host` |
| Verify vCenter certificate | `verify_certs` |
| Metrics to collect | `metric_scope` |
| Attach objects to vCenter inventory | `attach_to_vcenter` |

The username was one of them and no longer is. Two accounts that point at the
same vCenter with the same three settings, and differed only by username, now
have the same identity. That is intended: the same vCenter collected twice
produces the same objects twice. Before upgrading, delete all but one such
account. What Operations does with a pair that is still there at upgrade time
has not been tested.

## Upgrade steps

1. For each vSAN Host Metrics account: **Administration > Integrations >
   Accounts**, edit the account, edit its credential, enter the username with
   its domain (e.g. `vsanmon@vsphere.local`) and save. On 1.4.x the credential
   form has no username field yet; do this right after step 3 instead.
2. Delete any duplicate accounts as described above.
3. Install the 2.0.0 pak over the installed one (Integrations > Repository).
4. Edit each account's credential if step 1 was not possible, then click
   **Validate Connection**. It should pass.
5. After the next collection, confirm the account shows no error and its
   objects receive new values.

## Is an in-place upgrade accepted?

Whether VCF Operations accepts the 2.0.0 pak installed over 1.4.x or 1.5.0 when
it drops an identifying field, and whether existing accounts keep their
objects, is proven only by installing it, not by this branch. The branch
proves the code and the generated `describe.xml`; it does not prove what the
platform does with them. The credential's username field is also now
required, and how Operations treats a stored credential that lacks a required
field is part of the same test.

> **Live install result:** _PLACEHOLDER, to be filled after installing over
> 1.x on 8.18.7, 9.0.2 and 9.1.1: accepted or refused, accounts kept or not,
> objects and history kept or not._

## Rolling back

Install the 1.4.7 pak. 1.4.7 reads the username from the *vCenter username*
account field, not the credential. Whether a value stored there before 2.0.0
survives the round trip is not known; if the field is empty, enter the
username there again.
