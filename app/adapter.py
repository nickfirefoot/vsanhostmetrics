"""
VCF Operations adapter -- vSAN host TCP/IP metrics (beta scope).

Scrapes https://<esxi>/vsanmetrics directly from each host, converts the
cumulative TCP counters to rates, and emits one VsanHostTcpIp object per
(host, tcpip stack).

>>> RECONCILE THE IMPORTS BELOW <<<
The SDK was renamed from vmware-aria-operations-integration-sdk to
vmware-vcf-operations-integration-sdk in 9.0 and the python package path may
have moved with it.  Run `mp-init`, open the adapter.py it generates, and
copy its import block over the one below.  Everything else in this file is
written against the same object model (AdapterDefinition / Object / Key /
Identifier / CollectResult) and should need no changes.
"""
from __future__ import annotations

import logging
import sys
from typing import Dict, List

# --- SDK imports: verify against your generated adapter.py ------------------
from aria.ops.adapter_instance import AdapterInstance
from aria.ops.adapter_logging import setup_logging
from aria.ops.definition.adapter_definition import AdapterDefinition
from aria.ops.definition.units import Units
from aria.ops.object import Identifier, Key, Object
from aria.ops.result import CollectResult, EndpointResult, TestResult
# ---------------------------------------------------------------------------

from constants import (
    ADAPTER_KIND,
    ADAPTER_NAME,
    HOSTS_PARAM,
    OBJ_TCPIP,
    TOKEN_CRED,
    VERIFY_PARAM,
)
import vsanmetrics as vm

logger = logging.getLogger(__name__)

# Module-level so baselines survive across collect() calls within the
# container's lifetime.  See RateCache docstring.
_RATES = vm.RateCache()


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------
def get_adapter_definition() -> AdapterDefinition:
    d = AdapterDefinition(ADAPTER_KIND, ADAPTER_NAME)

    d.define_string_parameter(
        HOSTS_PARAM,
        label="ESXi hosts",
        description="Comma-separated FQDNs or IPs of the vSAN hosts to scrape.",
        required=True,
    )
    d.define_bool_parameter(
        VERIFY_PARAM,
        label="Verify host certificates",
        description="Leave enabled. Disable only for initial bring-up.",
        default=True,
    )

    cred = d.define_credential_type("vsanmetrics_token", "vSAN metrics token")
    cred.define_password_parameter(
        TOKEN_CRED,
        label="Bearer token",
        description=(
            "auth_token from the host config store: "
            "configstorecli config current get -c vsan -g system -k vsan "
            "-> metric_subscriptions[0].auth_token"
        ),
        required=True,
    )

    tcpip = d.define_object_type(OBJ_TCPIP, "vSAN Host TCP/IP")
    tcpip.define_string_identifier("host_uuid", "Host UUID", is_part_of_uniqueness=True)
    tcpip.define_string_identifier("stack", "TCP/IP stack", is_part_of_uniqueness=True)
    tcpip.define_string_property("hostname", "Host name")
    tcpip.define_string_property("vsan_cluster_uuid", "vSAN cluster UUID")

    # Rates
    for key, label in (
        ("tcpPacketsTotal",       "TCP packets/s"),
        ("tcpBytesTotal",         "TCP bytes/s"),
        ("rcvOutOfOrderPackets",  "Out-of-order packets/s"),
        ("rcvDuplicateAcks",      "Duplicate ACKs/s"),
        ("rcvDuplicatePackets",   "Duplicate packets/s"),
        ("sndRetransmitPackets",  "Retransmitted packets/s"),
        ("sackRcvBlocks",         "SACK blocks received/s"),
        ("sackSendBlocks",        "SACK blocks sent/s"),
        ("sackRetransmits",       "SACK retransmits/s"),
    ):
        tcpip.define_metric(key, label, unit=Units.RATIO.PER_SECOND)

    # Derived percentages -- these are what symptoms alert on.
    for key, label in (
        ("outOfOrderPct",       "Out-of-order packets"),
        ("retransmitPct",       "Retransmitted packets"),
        ("duplicateAckPct",     "Duplicate ACKs"),
        ("duplicatePacketPct",  "Duplicate packets"),
    ):
        tcpip.define_metric(key, label, unit=Units.RATIO.PERCENT)

    return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hosts(adapter_instance: AdapterInstance) -> List[str]:
    raw = adapter_instance.get_identifier_value(HOSTS_PARAM) or ""
    return [h.strip() for h in raw.split(",") if h.strip()]


def _token(adapter_instance: AdapterInstance) -> str:
    return adapter_instance.get_credential_value(TOKEN_CRED) or ""


def _verify(adapter_instance: AdapterInstance) -> bool:
    v = adapter_instance.get_identifier_value(VERIFY_PARAM)
    return True if v is None else str(v).lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# test / get_endpoints / collect
# ---------------------------------------------------------------------------
def test(adapter_instance: AdapterInstance) -> TestResult:
    result = TestResult()
    hosts = _hosts(adapter_instance)
    if not hosts:
        result.with_error("No hosts configured.")
        return result

    token = _token(adapter_instance)
    verify = _verify(adapter_instance)
    for host in hosts:
        try:
            text = vm.scrape(host, token, verify=verify, timeout=20)
            found = list(vm.parse(text, keep=vm.TCP_COUNTERS))
            if not found:
                result.with_error(
                    f"{host}: scrape succeeded but no vmware_esx_tcppkt_* "
                    f"samples present."
                )
            else:
                logger.info("%s: %d TCP samples", host, len(found))
        except Exception as exc:
            result.with_error(f"{host}: {exc}")
    return result


def get_endpoints(adapter_instance: AdapterInstance) -> EndpointResult:
    """Hand each host's cert to Operations so it lands in the trust store."""
    result = EndpointResult()
    for host in _hosts(adapter_instance):
        result.with_endpoint(f"https://{host}")
    return result


def collect(adapter_instance: AdapterInstance) -> CollectResult:
    result = CollectResult()
    token = _token(adapter_instance)
    verify = _verify(adapter_instance)

    for host in _hosts(adapter_instance):
        try:
            text = vm.scrape(host, token, verify=verify)
        except Exception as exc:
            # Partial failure: one unreachable host must not fail the whole
            # collection.  Operations shows the object as not-collecting.
            logger.error("scrape failed for %s: %s", host, exc)
            continue

        samples = list(vm.parse(text, keep=vm.TCP_COUNTERS))
        if not samples:
            logger.warning("%s: no TCP samples in response", host)
            continue

        rates, resets = _RATES.rates(host, samples)
        if resets:
            logger.warning("%s: %d counter resets this interval", host, resets)
        if not rates:
            continue                      # first interval, or a reboot

        # Group rates by (host_uuid, stack) -> {metric_key: value}
        grouped: Dict[tuple, Dict[str, float]] = {}
        props: Dict[tuple, Dict[str, str]] = {}
        for (scope, name, labels), rate in rates.items():
            lab = dict(labels)
            ident = (lab.get("host_uuid", host), lab.get("stack", "unknown"))
            grouped.setdefault(ident, {})[vm.TCP_COUNTERS[name]] = rate
            props.setdefault(ident, {
                "hostname": lab.get("hostname", host),
                "vsan_cluster_uuid": lab.get("vsan_cluster_uuid", ""),
            })

        for (host_uuid, stack), metrics in grouped.items():
            obj = result.object(
                ADAPTER_KIND,
                OBJ_TCPIP,
                f"{props[(host_uuid, stack)]['hostname']} [{stack}]",
                identifiers=[
                    Identifier("host_uuid", host_uuid),
                    Identifier("stack", stack),
                ],
            )
            for k, v in metrics.items():
                obj.with_metric(k, v)
            for k, v in vm.derive_percentages(metrics).items():
                obj.with_metric(k, v)
            for k, v in props[(host_uuid, stack)].items():
                if v:
                    obj.with_property(k, v)

            # TODO cross-adapter relationship to the vCenter adapter's
            # HostSystem, so this is navigable from the host in Operations.
            # Needs whatever VMWARE keys HostSystem on -- match on the FQDN
            # in `hostname` if that is the HostSystem name, otherwise
            # translate via GetVcMoRefFromPerfEntityRefId on /vsanperf.

    return result


# ---------------------------------------------------------------------------
def main(argv):
    setup_logging("adapter.log")
    ...  # mp-init generates the dispatch block; keep the generated one.


if __name__ == "__main__":
    main(sys.argv[1:])
