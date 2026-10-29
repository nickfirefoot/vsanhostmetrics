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
orphans an object's history. Whether Operations keeps the existing accounts,
objects and history through the upgrade is a platform outcome, and is owed to
the live install below.

The 1.5.0 release candidates read the old field as a fallback and logged a
WARNING each cycle. 2.0.0 does not read it at all.

## Do not uninstall 1.x first

The general rule in README section 5 and QUICKSTART section 1 says a schema
change means uninstalling the old pack and deleting its accounts. That rule is
not for this upgrade. Following it means deleting the accounts, and with them
the collected objects and their history; a pak uninstall on Operations has
also been seen to delete the credentials of the adapter kind. Install 2.0.0 over the top, unless the live
install result below says that is refused.

## What breaks

An account whose credential has no username stops collecting. Validate
Connection and every collection fail with:

    No vCenter username. Edit the account's credential and enter the
    username with its domain, e.g. vsanmon@vsphere.local.

On that path the adapter attempts no login and deletes nothing: it reports
the error and returns no objects. Once the username is entered, the next
collection proceeds normally. What Operations shows for the account's objects
while it is in error is a platform behaviour and is not tested here.

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
history, the credential), has been tested. If you have such a pair, wait for
the live install result below before upgrading.

## Upgrade steps

1. Check for colliding accounts as above. If there are any, stop here until the
   live install result covers them.
2. For each vSAN Host Metrics account on a 1.5.0 release candidate:
   **Administration > Integrations > Accounts**, edit the account, edit its
   credential, enter the username with its domain (e.g.
   `vsanmon@vsphere.local`) and save. On 1.4.x the credential form has no
   username field yet; do this in step 4 instead.
3. Install the 2.0.0 pak over the installed one (Integrations > Repository).
   Do not uninstall 1.x and do not delete the accounts.
4. Edit each account's credential if step 2 was not possible, then click
   **Validate Connection**. It should pass.
5. After the next collection, confirm the account shows no error and its
   existing objects receive new values.

## Owed to the live install

The branch proves the code, the error path and the generated `describe.xml`.
It does not prove what the platform does with them. These are proven only by
installing over 1.4.7 and over a 1.5.0 release candidate:

- whether Operations accepts the 2.0.0 pak in place when it drops an
  identifying field;
- whether existing accounts, their objects and their history are kept;
- how Operations treats a stored credential that lacks the now-required
  username field (loads it, forces an edit, or refuses it);
- what happens to a colliding pair of accounts;
- whether a downgrade to 1.4.7 is accepted (see Rolling back).

> **Live install result:** _PLACEHOLDER, to be filled after installing over
> 1.x on 8.18.7, 9.0.2 and 9.1.1: accepted or refused, accounts kept or not,
> objects and history kept or not, credential without username handled how,
> colliding pair handled how, downgrade to 1.4.7 accepted or refused._

## Rolling back

Not established. Whether Operations accepts the 1.4.7 pak over 2.0.0 (a lower
version over a higher one) has not been tested. 1.4.7 also adds `vcenter_user`
back as a required identifying field, so any account that comes through the
downgrade without a value in it has to be edited, and that edits the
account's identity on a live account, with an outcome that is not known. Treat
rollback as unavailable until the live install result above covers it.
