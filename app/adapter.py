#  Copyright 2022-2023 VMware, Inc.
#  SPDX-License-Identifier: Apache-2.0
"""
VCF Operations adapter -- vSAN host TCP/IP metrics (beta scope).

Scrapes https://<esxi>/vsanmetrics directly from each host, converts the
cumulative TCP counters to rates, and emits one VsanHostTcpIp object per
(host, tcpip stack).

Import block and main() dispatch are taken verbatim from the mp-init
generated adapter.py (SDK 1.3.1 / lib 1.1.0), which is ground truth.
"""
import sys
from typing import Dict
from typing import List

import aria.ops.adapter_logging as logging
from aria.ops.adapter_instance import AdapterInstance
from aria.ops.definition.adapter_definition import AdapterDefinition
from aria.ops.definition.units import Units
from aria.ops.object import Identifier
from aria.ops.result import CollectResult
from aria.ops.result import EndpointResult
from aria.ops.result import TestResult
from aria.ops.timer import Timer
from constants import ADAPTER_KIND
from constants import ADAPTER_NAME
from constants import HOSTS_PARAM
from constants import OBJ_TCPIP
from constants import TOKEN_CRED
from constants import VERIFY_PARAM

import vsanmetrics as vm

logger = logging.getLogger(__name__)

# Module-level so baselines survive across collect() calls within the
# container's lifetime.  See RateCache docstring.
_RATES = vm.RateCache()


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------
def get_adapter_definition() -> AdapterDefinition:
    with Timer(logger, "Get Adapter Definition"):
        d = AdapterDefinition(ADAPTER_KIND, ADAPTER_NAME)

        d.define_string_parameter(
            HOSTS_PARAM,
            label="ESXi hosts",
            description="Comma-separated FQDNs or IPs of the vSAN hosts to scrape.",
            required=True,
        )
        # NOTE: lib 1.1.0 has no define_bool_parameter.  An enum of "true"/"false"
        # is the supported equivalent; _verify() already parses the string form.
        d.define_enum_parameter(
            VERIFY_PARAM,
            values=["true", "false"],
            label="Verify host certificates",
            description="Leave enabled. Disable only for initial bring-up.",
            default="true",
        )

        # Special key read by the VCF Operations collector to size the adapter
        # container.  Kept from the generated template: removing it removes the
        # ability to tune container memory at configuration time.
        d.define_int_parameter(
            "container_memory_limit",
            label="Adapter Memory Limit (MB)",
            description="Sets the maximum amount of memory VMware Aria Operations can "
            "allocate to the container running this adapter instance.",
            required=True,
            advanced=True,
            default=1024,
        )

        cred = d.define_credential_type("vsanmetrics_token", "vSAN metrics token")
        # NOTE: credential parameters in lib 1.1.0 take no `description` kwarg
        # (only key/label/required), so the retrieval hint lives in the label.
        # Full command, run on the host:
        #   configstorecli config current get -c vsan -g system -k vsan
        #     -> metric_subscriptions[0].auth_token
        cred.define_password_parameter(
            TOKEN_CRED,
            label="Bearer token (vsan/system/vsan -> metric_subscriptions[0].auth_token)",
            required=True,
        )

        tcpip = d.define_object_type(OBJ_TCPIP, "vSAN Host TCP/IP")
        tcpip.define_string_identifier("host_uuid", "Host UUID", is_part_of_uniqueness=True)
        tcpip.define_string_identifier("stack", "TCP/IP stack", is_part_of_uniqueness=True)
        tcpip.define_string_property("hostname", "Host name")
        tcpip.define_string_property("vsan_cluster_uuid", "vSAN cluster UUID")

        # Rates.  NOTE: Units.RATE.PER_SECOND -- there is no Units.RATIO.PER_SECOND
        # in lib 1.1.0; Ratio only defines PERCENT.
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
            tcpip.define_metric(key, label, unit=Units.RATE.PER_SECOND)

        # Derived percentages -- these are what symptoms alert on.
        for key, label in (
            ("outOfOrderPct",       "Out-of-order packets"),
            ("retransmitPct",       "Retransmitted packets"),
            ("duplicateAckPct",     "Duplicate ACKs"),
            ("duplicatePacketPct",  "Duplicate packets"),
        ):
            tcpip.define_metric(key, label, unit=Units.RATIO.PERCENT)

        logger.debug(f"Returning adapter definition: {d.to_json()}")
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
    with Timer(logger, "Test"):
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
    with Timer(logger, "Get Endpoints"):
        result = EndpointResult()
        for host in _hosts(adapter_instance):
            result.with_endpoint(f"https://{host}")
        return result


def collect(adapter_instance: AdapterInstance) -> CollectResult:
    with Timer(logger, "Collection"):
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

        logger.debug(f"Returning collection result {result.get_json()}")
        return result


# Main entry point of the adapter. You should not need to modify anything below this line.
def main(argv: List[str]) -> None:
    logging.setup_logging("adapter.log")
    # Start a new log file by calling 'rotate'. By default, the last five calls will be
    # retained. If the logs are not manually rotated, the 'setup_logging' call should be
    # invoked with the 'max_size' parameter set to a reasonable value, e.g.,
    # 10_489_760 (10MB).
    logging.rotate()
    logger.info(f"Running adapter code with arguments: {argv}")
    if len(argv) != 3:
        # `inputfile` and `outputfile` are always automatically appended to the
        # argument list by the server
        logger.error("Arguments must be <method> <inputfile> <ouputfile>")
        sys.exit(1)

    method = argv[0]
    try:
        if method == "test":
            test(AdapterInstance.from_input()).send_results()
        elif method == "endpoint_urls":
            get_endpoints(AdapterInstance.from_input()).send_results()
        elif method == "collect":
            collect(AdapterInstance.from_input()).send_results()
        elif method == "adapter_definition":
            result = get_adapter_definition()
            if type(result) is AdapterDefinition:
                result.send_results()
            else:
                logger.info(
                    "get_adapter_definition method did not return an AdapterDefinition"
                )
                sys.exit(1)
        else:
            logger.error(f"Command {method} not found")
            sys.exit(1)
    finally:
        logger.info(Timer.graph())
        sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
