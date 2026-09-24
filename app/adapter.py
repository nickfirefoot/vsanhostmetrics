#  Copyright 2022-2023 VMware, Inc.
#  SPDX-License-Identifier: Apache-2.0
"""
VCF Operations adapter -- vSAN metrics from the Performance Service.

Collects via vCenter's VsanPerfQueryPerf rather than scraping each ESXi host.
One source: never two gathering points for the same metric.  See
docs/COLLECTION-DESIGN.md for why, and what that costs.

The object schema is GENERATED from app/perfsvc_model.py, which is itself
derived from a live Performance Service -- 31 entity types, 1,035 metric
definitions.  Hand-writing that does not scale and would drift every time the
API changes.

The host-scrape path (vsanmetrics.py, model.py) is retained but DORMANT.
Nothing imports it.  It exists so that reviving a family perfsvc does not serve
-- heaps, slabs, CMMDS workload, memory detail, ESA internals -- is a routing
change rather than archaeology.

Import block and main() dispatch are taken verbatim from the mp-init generated
adapter.py (SDK 1.3.1 / lib 1.1.0), which is ground truth.
"""
import os
import sys
from typing import Dict
from typing import List

import aria.ops.adapter_logging as logging
from aria.ops.adapter_instance import AdapterInstance
from aria.ops.definition.adapter_definition import AdapterDefinition
from aria.ops.definition.units import Units
from aria.ops.object import Identifier, Key, Object
from aria.ops.result import CollectResult
from aria.ops.result import EndpointResult
from aria.ops.result import TestResult
from aria.ops.timer import Timer
from constants import ADAPTER_KIND
from constants import ADAPTER_NAME
from constants import VC_HOST_PARAM
from constants import VC_USER_PARAM
from constants import VC_PASS_CRED
from constants import VERIFY_PARAM

import perfsvc
import metric_labels

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------
def get_adapter_definition() -> AdapterDefinition:
    with Timer(logger, "Get Adapter Definition"):
        d = AdapterDefinition(ADAPTER_KIND, ADAPTER_NAME)

        d.define_string_parameter(
            VC_HOST_PARAM,
            label="vCenter Server",
            description="FQDN or IP of the vCenter Server managing the vSAN cluster.",
            required=True,
        )
        d.define_string_parameter(
            VC_USER_PARAM,
            label="vCenter username",
            description="Read-only is sufficient. Needs System.View and System.Read "
                        "propagated from the vCenter root -- no cluster edit rights.",
            required=True,
        )
        # NOTE: lib 1.1.0 has no define_bool_parameter; an enum of "true"/"false"
        # is the supported equivalent.
        d.define_enum_parameter(
            VERIFY_PARAM,
            values=["true", "false"],
            label="Verify vCenter certificate",
            description="Leave enabled. Disable only for initial bring-up.",
            default="true",
        )
        # Special key read by the collector to size the adapter container.
        d.define_int_parameter(
            "container_memory_limit",
            label="Adapter Memory Limit (MB)",
            description="Maximum memory VCF Operations may allocate to the "
                        "container running this adapter instance.",
            required=True,
            advanced=True,
            default=1024,
        )

        cred = d.define_credential_type("vsan_vc_credential", "vCenter credential")
        # NOTE: credential parameters in lib 1.1.0 take only key/label/required.
        cred.define_password_parameter(
            VC_PASS_CRED,
            label="vCenter password",
            required=True,
        )

        # ------------------------------------------------------------------
        # Object types are GENERATED from app/perfsvc_model.py.
        # Identity comes from parsing entityRefId, which is regular across
        # every entity type: "<type>:<uuid>[|<part>[|<part>]]".
        # ------------------------------------------------------------------
        for entity in sorted(perfsvc.MODEL.ENTITIES):
            spec = perfsvc.MODEL.ENTITIES[entity]
            ot = d.define_object_type(spec["kind"], spec["label"])

            for label in spec["identity"]:
                ot.define_string_identifier(label, _label_for(label),
                                            is_part_of_uniqueness=True)
            for label in spec["identity"]:
                # identity values are also exposed as properties so they are
                # visible without reading the object name
                ot.define_string_property(f"{label}_prop", _label_for(label))

            for metric in spec["metrics"]:
                # Every perfsvc metric is a point value: the service has already
                # reduced into 5-minute buckets, so nothing here is a rate we
                # compute or a counter we difference.
                unit = _unit_for(metric)
                if unit is not None:
                    ot.define_metric(metric, _metric_label(metric), unit=unit)
                else:
                    ot.define_metric(metric, _metric_label(metric))

        logger.debug(f"Returning adapter definition: {d.to_json()}")
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_LABEL_OVERRIDES = {
    "host_uuid": "Host UUID", "cluster_uuid": "Cluster UUID",
    "vm_uuid": "VM UUID", "vdisk_uuid": "Virtual disk UUID",
    "disk_uuid": "Disk UUID", "stack": "TCP/IP stack",
    "vmnic": "Physical NIC", "vmknic": "VMkernel NIC", "cpu": "CPU",
    "device": "Device", "world_name": "World name", "world_id": "World ID",
}


def _label_for(key: str) -> str:
    return _LABEL_OVERRIDES.get(key, key.replace("_", " ").capitalize())


# vCenter objects our objects attach to. Operations already holds these from
# the built-in VMWARE adapter, keyed on the managed object reference plus the
# vCenter instance UUID; see perfsvc.build_parent_map.
VC_ADAPTER = "VMWARE"
VC_KINDS = {"hosts": "HostSystem", "vms": "VirtualMachine",
            "clusters": "ClusterComputeResource",
            "disks": "HostSystem", "vdisks": "VirtualMachine"}


def _vc_parent(cache, parents, bucket, uuid):
    """Object for the vCenter host/VM/cluster an object belongs to, or None.

    Returns an Object keyed exactly as the VMWARE adapter keys it, so
    Operations matches the existing object rather than creating a second one.
    Only the two uniqueness identifiers are set -- adding the non-unique ones
    (VMEntityName and friends) risks a mismatch when they change.
    """
    moid = parents.get(bucket, {}).get(uuid)
    vcid = parents.get("vcid")
    if not moid or not vcid:
        return None
    # Dedupe on the vCenter object, not the bucket that found it. Two buckets
    # resolve to the same VirtualMachine -- vm_uuid and a virtual disk's
    # datastore path -- and two buckets resolve to the same HostSystem. Keying
    # the cache by bucket built two Python objects sharing one Operations key,
    # and CollectResult rejects that with ObjectKeyAlreadyExistsException,
    # which aborts the entire collection.
    ckey = (VC_KINDS[bucket], moid)
    if ckey not in cache:
        # Use the object's REAL vCenter name. Supplying anything else renames
        # the object in Operations -- passing the MoRef turned every host into
        # "host-27" and the cluster into "domain-c9".
        cache[ckey] = Object(Key(
            adapter_kind=VC_ADAPTER,
            object_kind=VC_KINDS[bucket],
            name=parents.get("names", {}).get(moid) or moid,
            identifiers=[Identifier("VMEntityObjectID", moid),
                         Identifier("VMEntityVCID", vcid)],
        ))
    return cache[ckey]


def _metric_label(key: str) -> str:
    """Readable label for a perfsvc metric id.

    Generated in app/metric_labels.py, because camelCase-splitting the id is
    not enough: txSbSpaceMin becomes "Tx sb space min", which is derived from
    the name and tells you nothing. "Sb" is socket buffer.
    """
    label = metric_labels.LABELS.get(key)
    if label:
        return label
    out = []
    for i, ch in enumerate(key):
        if ch.isupper() and i and not key[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).replace("_", " ").capitalize()


def _unit_for(key: str):
    """Resolve a dotted Units path, e.g. "TIME.MICROSECONDS".

    Without a unit Operations renders a bare number, so tcpRxThroughput gives
    no way to tell bytes/s from bits/s. Units are harvested from HCIBench's
    dashboards over the same underlying stats; metrics with no entry stay
    dimensionless rather than being guessed at.
    """
    path = metric_labels.UNITS.get(key)
    if not path:
        return None
    node = Units
    for part in path.split("."):
        node = getattr(node, part, None)
        if node is None:
            return None
    return node


def _cfg(adapter_instance: AdapterInstance, key: str, default: str = "") -> str:
    return adapter_instance.get_identifier_value(key) or default


def _verify(adapter_instance: AdapterInstance) -> bool:
    return _cfg(adapter_instance, VERIFY_PARAM, "true").strip().lower() in (
        "true", "1", "yes")


def _password(adapter_instance: AdapterInstance) -> str:
    return adapter_instance.get_credential_value(VC_PASS_CRED) or ""


def _connect(adapter_instance: AdapterInstance):
    return perfsvc.connect(
        _cfg(adapter_instance, VC_HOST_PARAM),
        _cfg(adapter_instance, VC_USER_PARAM),
        _password(adapter_instance),
        verify=_verify(adapter_instance),
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test(adapter_instance: AdapterInstance) -> TestResult:
    with Timer(logger, "Test"):
        result = TestResult()
        host = _cfg(adapter_instance, VC_HOST_PARAM)
        if not host:
            result.with_error("No vCenter Server configured.")
            return result
        si = None
        try:
            si, clusters, mos = _connect(adapter_instance)
            if not clusters:
                result.with_error(
                    "Connected to vCenter but no clusters are visible. The "
                    "account likely lacks Read-only propagated from the root.")
                return result
            objs, problems = perfsvc.collect(mos["vsan-performance-manager"],
                                             clusters[0])
            logger.info("%s: %d clusters, %d objects, %d metrics",
                        host, len(clusters), len(objs),
                        sum(len(g.gauges) for g in objs.values()))
            if problems:
                logger.warning("%s: %d problem(s): %s", host, len(problems),
                               problems[:5])
        except perfsvc.PerfSvcError as exc:
            result.with_error(str(exc))
        except Exception as exc:                    # noqa: BLE001
            result.with_error(f"{host}: {type(exc).__name__}: {exc}")
        finally:
            _safe_disconnect(si)
        return result


def get_endpoints(adapter_instance: AdapterInstance) -> EndpointResult:
    """Hand vCenter's cert to Operations so it lands in the trust store."""
    with Timer(logger, "Get Endpoints"):
        result = EndpointResult()
        host = _cfg(adapter_instance, VC_HOST_PARAM)
        if host:
            result.with_endpoint(f"https://{host}")
        return result


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------
def collect(adapter_instance: AdapterInstance) -> CollectResult:
    with Timer(logger, "Collection"):
        result = CollectResult()
        si = None
        try:
            si, clusters, mos = _connect(adapter_instance)
            if not clusters:
                raise perfsvc.PerfSvcError(
                    "No clusters visible to this account -- check that the "
                    "Read-only role is propagated from the vCenter root.")
            perf = mos["vsan-performance-manager"]

            # perfsvc identifies everything by UUID and returns no friendly
            # name alongside it, unlike the host exposition. Without this every
            # object in Operations reads as a bare UUID.
            names = perfsvc.build_name_map(si, clusters, perf, mos)
            logger.info("resolved %d identifier names", len(names))
            parents = perfsvc.build_parent_map(si, clusters, perf, mos)
            logger.info("mapped %d hosts, %d VMs, %d clusters to vCenter objects",
                        len(parents.get("hosts", {})), len(parents.get("vms", {})),
                        len(parents.get("clusters", {})))
            vc_cache: dict = {}
            linked = 0

            total_problems: List[str] = []
            for cluster in clusters:
                objs, problems = perfsvc.collect(perf, cluster)
                total_problems.extend(problems)
                for key, grouped in objs.items():
                    spec = perfsvc.MODEL.ENTITIES[key.entity]
                    obj = result.object(
                        ADAPTER_KIND,
                        spec["kind"],
                        key.display(names),
                        identifiers=[Identifier(name, value)
                                     for name, value in key.idents],
                    )
                    for metric, value in grouped.gauges.items():
                        obj.with_metric(metric, value)
                    for name, value in grouped.props.items():
                        if value:
                            obj.with_property(f"{name}_prop",
                                              names.get(value, value))

                    # Hang the object off the vCenter object it belongs to, so
                    # vSAN metrics show up under the host or VM an operator is
                    # already looking at. Identity order matters: host_uuid
                    # before cluster_uuid, because a host-scoped object that
                    # also carries a cluster id belongs under the host.
                    idents = dict(key.idents)
                    for bucket, ident in (("hosts", "host_uuid"),
                                          ("vms", "vm_uuid"),
                                          ("disks", "disk_uuid"),
                                          ("vdisks", "vdisk_uuid"),
                                          ("clusters", "cluster_uuid")):
                        value = idents.get(ident)
                        if not value:
                            continue
                        parent = _vc_parent(vc_cache, parents, bucket, value)
                        if parent is not None:
                            parent.add_child(obj)
                            linked += 1
                        break

            for parent in vc_cache.values():
                result.add_object(parent)
            logger.info("linked %d objects to %d vCenter parents",
                        linked, len(vc_cache))

            if total_problems:
                # Loud on purpose. A silently dropped sample is how the io_type
                # collision survived a green test suite.
                logger.warning("%d collection problem(s); first few: %s",
                               len(total_problems), total_problems[:5])
        finally:
            _safe_disconnect(si)

        logger.debug(f"Returning collection result {result.get_json()}")
        return result


def _safe_disconnect(si) -> None:
    if si is None:
        return
    try:
        from pyVim.connect import Disconnect
        Disconnect(si)
    except Exception:                                # noqa: BLE001
        pass


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
