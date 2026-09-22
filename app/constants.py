ADAPTER_KIND = "VsanHostMetrics"
ADAPTER_NAME = "vSAN Host Metrics"

# Adapter instance configuration
HOSTS_PARAM = "hosts"
VERIFY_PARAM = "verify_certs"
TOKEN_CRED = "bearer_token"

# Object kinds are GENERATED -- see app/model.py FAMILIES[*]['kind'].
# The old single hand-written OBJ_TCPIP is gone; EsxTcpIp is its successor.

# Broadcom thresholds, for the symptom definitions in content/.
# Source: "Understanding vSAN Network TCP/IP Expectations and Thresholds"
# These are relative to RECEIVED packets, which is what the fixed
# derive_percentages() now divides by -- see vsanmetrics.DERIVED.
THRESHOLDS = {
    "outOfOrderPct":   {"warning": 0.1, "immediate": 0.5, "critical": 1.0},
    "retransmitPct":   {"critical": 0.5},
    "duplicateAckPct": {"critical": 1.0},
}
