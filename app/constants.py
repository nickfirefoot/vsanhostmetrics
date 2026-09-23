ADAPTER_KIND = "VsanHostMetrics"
ADAPTER_NAME = "vSAN Host Metrics"

# --- Adapter instance configuration (Performance Service source) -----------
VC_HOST_PARAM = "vcenter_host"
VC_USER_PARAM = "vcenter_user"
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
