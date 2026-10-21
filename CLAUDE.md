# Operating rules for this repository

Hard constraints, not preferences. Each exists because breaking it damaged a
live environment. Do not relax one without the user saying so explicitly.

---

## 1. NEVER write relationships onto objects this pack does not own

**An adapter may only assert parent/child relationships between objects of its
OWN adapter kind.** It must never emit a `VMWARE`, `VsphereNetStats`,
`VirtualAndPhysicalSANAdapter` or any other foreign object in a
`CollectResult`, for any reason, including "merging" its children first.

### Why this is absolute

Relationship serialisation in the Operations SDK is **REPLACE, not merge**.
`CollectResult.get_json()` emits, per object, `{"parent": key, "children":
[...]}` -- the complete child set. Putting a foreign object in the result
therefore asserts that object's *entire* child list, destroying whatever the
owning adapter had.

The read-then-merge workaround -- read the parent's existing children over
suite-api, re-assert them alongside ours -- is NOT a fix. It narrows the window;
it does not close it. Its own code comment admitted the race: "a child created
between our read and our write is dropped." With a second pack doing the same
read-modify-write on the same parents, the race becomes the normal case.

### What it actually cost, twice

- **2026-10-02**, recorded as "CRITICAL: this pack strips vCenter's own
  relationships every collection". The merge was the fix.
- **2026-10-21**, with the merge in place and a second pack attaching to the
  same hosts: **26 of 28 VMs lost their `HostSystem` parent.** They kept every
  other parent, because those come from objects nothing here touches. The loss
  did not self-heal -- the vCenter adapter does not re-assert host-to-VM every
  cycle, so what gets dropped stays dropped.

### The verification that is NOT sufficient

Counting that foreign children *exist* on a parent. On 2026-10-16 this pack was
declared clean because hosts showed 8, 10, 14 and 59 VMWARE children. Those
counts were already missing most of their VMs. **Presence is not completeness.**
The only valid check is from the CHILD side: every VM must still have a
`HostSystem` parent.

    VMWARE VirtualMachine objects      28
    with a HostSystem parent            2      <- the failure
    without                            26

### Why the damage is selective, and why that misleads

Measured 2026-10-21: Pods survive on those hosts, VirtualMachines do not. That
is not evidence the write is harmless. Supervisor churns Pods constantly so the
vCenter adapter re-asserts Pod-to-Host edges within minutes; VM-to-Host is
stable and rarely re-asserted, so once dropped it stays dropped. A partially
populated child list is the signature of this bug, not of its absence.

### What to do instead

Build the pack's own hierarchy, in its own adapter kind, parented among itself.
`docs/DELIVERY-PIVOT.md` reached this conclusion before any of the damage:
"Build our own hierarchy. A vSAN World of our own kinds, parented among
themselves, touching nothing of vCenter's." That was the right answer and was
not taken, because co-location in the inventory looked worth the risk. It was
not.

---

## 2. Verify the OUTCOME, never the code path

Three consecutive releases claimed to fix object orphaning and all three were
broken, because the code path was verified and the result never was. State the
one measurement that proves a fix before writing it, then take that measurement.

## 3. Check the repo's own notes before theorising

`BACKLOG.md`, `docs/`, and the lab API via `~/ops.env` usually hold the answer
already. Several multi-hour investigations here re-derived something this
repository had written down.

## 4. Do not claim a figure that was not computed

Contrast ratios, thresholds, "identical in every observed pair" -- compute it or
do not assert it. Three claims in this repository were wrong in exactly this
way, and each was discovered by someone else checking.
