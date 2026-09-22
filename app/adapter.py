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
import os
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
from constants import TOKEN_CRED
from constants import VERIFY_PARAM

import vsanmetrics as vm

logger = logging.getLogger(__name__)

# commands.cfg runs `python app/adapter.py collect` once per collection, so this
# module is re-imported in a BRAND NEW interpreter every interval.  A purely
# in-memory cache is therefore always empty and no rate is ever emitted; the
# baseline has to live on the container filesystem.  See RateCache docstring.
# /tmp, not /var/log: mp-test bind-mounts the project's logs/ over /var/log, and
# the adapter runs as uid 1000 while that directory is owned by the host user, so
# /var/log is read-only in practice.  /tmp is container-local and always writable,
# which is exactly the container-lifetime scope we want.
_RATES = vm.RateCache(
    path=os.getenv("VSAN_RATE_CACHE", "/tmp/vsan_rate_cache.json")
)


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
        # Full command, on any host in the cluster -- note the -n, without it
        # the token comes back masked:
        #   configstorecli config current get -c vsan -g system -k vsan -n
        #     -> metric_subscriptions[].auth_token
        #
        # metric_subscriptions is a LIST, and every entry's token is valid
        # simultaneously (verified 2026-09-22: two entries, both returning 200
        # on two hosts).  Do not assume index 0 -- entries are added and removed
        # over time, and a token observed earlier the same day had already been
        # invalidated.  Any current entry will do.
        cred.define_password_parameter(
            TOKEN_CRED,
            label="Bearer token (vsan/system/vsan -> any metric_subscriptions[].auth_token)",
            required=True,
        )

        # ------------------------------------------------------------------
        # Object types are GENERATED from app/model.py, which is itself derived
        # from a real /vsanmetrics exposition.  Hand-writing 385 metric
        # definitions across 16 resource kinds does not scale and would drift
        # every time ESXi changes the endpoint.
        #
        # Identity vs metric key is the rule that matters here:
        #   * identity labels split objects   (stack, vmnic, world_id, ...)
        #   * measurement labels join the key (io_type -> total|rx, total|tx)
        # The second is why the io_type collision cannot recur.
        # ------------------------------------------------------------------
        for fam in sorted(vm.MODEL.FAMILIES):
            spec = vm.MODEL.FAMILIES[fam]
            ot = d.define_object_type(spec["kind"], spec["label"])

            # host_uuid is always part of identity: every sample carries it and
            # objects must not merge across hosts.
            ot.define_string_identifier("host_uuid", "Host UUID",
                                        is_part_of_uniqueness=True)
            for lab in spec["identity"]:
                ot.define_string_identifier(lab, _label_for(lab),
                                            is_part_of_uniqueness=True)

            ot.define_string_property("hostname", "Host name")
            ot.define_string_property("vsan_cluster_uuid", "vSAN cluster UUID")
            for prop in spec["properties"]:
                if prop in ("hostname", "vsan_cluster_uuid", "host_uuid"):
                    continue
                ot.define_string_property(prop, _label_for(prop))

            for key, _src, _vals, kind, help_text in spec["metrics"]:
                label = _metric_label(key, help_text)
                if kind == "counter":
                    # Counters are cumulative since boot; we emit a rate.
                    # NOTE Units.RATE.PER_SECOND -- lib 1.1.0 has no
                    # Units.RATIO.PER_SECOND; Ratio only defines PERCENT.
                    ot.define_metric(key, label, unit=Units.RATE.PER_SECOND)
                else:
                    ot.define_metric(key, label)

            # Derived percentages live only on the TCP/IP kind for now; they
            # are what symptom definitions can actually alert on, since a
            # symptom cannot divide two metrics itself.
            if fam == "vmware_esx_tcppkt":
                for key, lbl in vm.DERIVED_LABELS.items():
                    ot.define_metric(key, lbl, unit=Units.RATIO.PERCENT)

        logger.debug(f"Returning adapter definition: {d.to_json()}")
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_LABEL_OVERRIDES = {
    "host_uuid": "Host UUID", "hostname": "Host name",
    "vsan_cluster_uuid": "vSAN cluster UUID", "stack": "TCP/IP stack",
    "vmnic": "Physical NIC", "world_id": "World ID", "name": "Name",
    "heap_id": "Heap ID", "heap_name": "Heap name", "slab": "Slab",
    "cpu": "CPU", "disk_uuid": "Disk UUID", "objuuid": "Object UUID",
    "objpath": "Object path", "vm_name": "VM name",
    "vm_instance_uuid": "VM instance UUID", "vscsi_name": "vSCSI device",
    "splinter_uuid": "Splinter UUID", "splinter_db_name": "Splinter DB",
    "sink_type": "Sink type", "subsystem": "Subsystem", "role": "Role",
}


def _label_for(key: str) -> str:
    return _LABEL_OVERRIDES.get(key, key.replace("_", " ").capitalize())


def _metric_label(key: str, help_text: str) -> str:
    """Readable label for a generated metric key.

    `total|rx` -> "Total (rx)".  Operations builds its metric tree from the
    '|' separators, so the label only needs to read well as a leaf.
    """
    parts = key.split("|")
    base = parts[0].replace("_total", "").replace("_", " ").strip().capitalize()
    if len(parts) > 1:
        base = f"{base} ({', '.join(parts[1:])})"
    return base or key


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
                found = list(vm.parse(text, keep=vm.ALL_NAMES))
                if not found:
                    result.with_error(
                        f"{host}: scrape succeeded but contained none of the "
                        f"{len(vm.ALL_NAMES)} metrics this adapter knows. "
                        f"Different ESXi build?"
                    )
                    continue
                objs, unknown = vm.group(found)
                logger.info("%s: %d samples -> %d objects across %d kinds",
                            host, len(found), len(objs),
                            len({o.family for o in objs}))
                if unknown:
                    # Surfaced in the connection test, not just the log: a new
                    # ESXi build adding metrics is something the operator wants
                    # to know at configuration time, not months later.
                    logger.warning("%s: %d unrecognised sample(s): %s",
                                   host, len(unknown), unknown[:5])
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

            samples = list(vm.parse(text, keep=vm.ALL_NAMES))
            if not samples:
                logger.warning("%s: no known samples in response", host)
                continue

            objs, unknown = vm.group(samples)
            if unknown:
                # Loud on purpose.  A silently dropped sample is how the
                # io_type collision survived a green test suite; an ESXi
                # upgrade adding a metric or a new label value should show up
                # here rather than as quietly missing data.
                logger.warning("%s: %d unrecognised sample(s); first few: %s",
                               host, len(unknown), unknown[:5])

            rates, resets = _RATES.rates_for_objects(host, objs)
            if resets:
                logger.warning("%s: %d counter resets this interval", host, resets)

            for okey, g in objs.items():
                spec = vm.MODEL.FAMILIES[okey.family]
                hostname = g.props.get("hostname", host)

                obj = result.object(
                    ADAPTER_KIND,
                    spec["kind"],
                    okey.display(hostname),
                    identifiers=[Identifier("host_uuid", okey.host_uuid)]
                    + [Identifier(k, v) for k, v in okey.idents],
                )

                # Gauges are point-in-time and need no baseline, so objects
                # appear on the very first collection rather than waiting an
                # interval.  Only counter-derived rates need two samples.
                for k, v in g.gauges.items():
                    obj.with_metric(k, v)

                counter_rates = rates.get(okey, {})
                for k, v in counter_rates.items():
                    obj.with_metric(k, v)

                if okey.family == "vmware_esx_tcppkt":
                    for k, v in vm.derive_percentages(counter_rates).items():
                        obj.with_metric(k, v)

                for k, v in g.props.items():
                    if v:
                        obj.with_property(k, v)

                # TODO cross-adapter relationship to the vCenter adapter's
                # HostSystem, so these are navigable from the host in
                # Operations.  Biggest usability gap -- see BACKLOG.md.

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
