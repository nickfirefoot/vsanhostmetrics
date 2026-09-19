ADAPTER_KIND = "VsanHostMetrics"
ADAPTER_NAME = "vSAN Host Metrics"

# Adapter instance configuration
HOSTS_PARAM = "hosts"
VERIFY_PARAM = "verify_certs"
TOKEN_CRED = "bearer_token"

# Object kinds
OBJ_TCPIP = "VsanHostTcpIp"

# Broadcom thresholds, for the symptom definitions in content/.
# Source: "Understanding vSAN Network TCP/IP Expectations and Thresholds"
THRESHOLDS = {
    "outOfOrderPct":   {"warning": 0.1, "immediate": 0.5, "critical": 1.0},
    "retransmitPct":   {"critical": 0.5},
    "duplicateAckPct": {"critical": 1.0},
}
