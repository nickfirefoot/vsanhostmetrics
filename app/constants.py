ADAPTER_KIND = "VsanHostMetrics"
ADAPTER_NAME = "vSAN Host Metrics"

# --- Adapter instance configuration (Performance Service source) -----------
VC_HOST_PARAM = "vcenter_host"
# Deprecated since 1.5.0: the username moved into the credential
# (VC_USER_CRED). The identifier is kept, optional, so accounts created
# before then keep working until their credential is updated.
VC_USER_PARAM = "vcenter_user"
VC_USER_CRED = "vcenter_username"
VC_PASS_CRED = "vcenter_password"
VERIFY_PARAM = "verify_certs"

# --- Retained for the DORMANT host-scrape path -----------------------------
# vsanmetrics.py and model.py are not imported by adapter.py. They exist so
# that reviving a family the Performance Service does not serve -- heaps,
# slabs, CMMDS workload, memory detail, ESA internals -- is a routing change
# rather than archaeology. See docs/COLLECTION-DESIGN.md.
HOSTS_PARAM = "hosts"
TOKEN_CRED = "bearer_token"

# Object kinds are GENERATED -- see app/perfsvc_model.py ENTITIES[*]['kind'].

# Broadcom thresholds, for the symptom definitions in content/.
# Source: "Understanding vSAN Network TCP/IP Expectations and Thresholds"
# NOTE: these are stated in PERCENT and are relative to RECEIVED packets.
# The Performance Service reports ratios in per-mille (its tcpRcvdupackRate
# read 1-2 where the host scrape measured 0.122%), so a symptom written against
# a perfsvc metric must divide these by 10. Confirm before use.
THRESHOLDS = {
    "outOfOrderPct":   {"warning": 0.1, "immediate": 0.5, "critical": 1.0},
    "retransmitPct":   {"critical": 0.5},
    "duplicateAckPct": {"critical": 1.0},
}

# Which metrics to collect. Most modelled metrics are referenced by no shipped
# view, and about half the entity types by none at all -- each of those is a
# skipped query (counts: the header of the generated app/metric_scope.py). Declared in describe either way, so a customer who turns
# this to "all" gets them without a new pak.
METRIC_SCOPE_PARAM = "metric_scope"


# Whether to attach our objects to vCenter objects. OFF by default since
# 2026-10-21, see CLAUDE.md rule 1: asserting children on an object we do not
# own destroys the owning adapter's relationships, and it did -- 26 of 28 VMs
# lost their HostSystem parent. Turning this on re-enables that risk and is
# only safe if NOTHING ELSE writes child lists on the same objects.
VC_ATTACH_PARAM = "attach_to_vcenter"
