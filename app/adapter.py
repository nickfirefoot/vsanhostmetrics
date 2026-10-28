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
adapter.py (SDK 1.3.1 / lib 1.1.0), which is ground truth -- except the
sys.exit(0) in main()'s finally, which is removed; see the comment there.
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
from constants import METRIC_SCOPE_PARAM
from constants import VC_ATTACH_PARAM
import metric_scope

import perfsvc
import metric_labels

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------
def get_adapter_definition() -> AdapterDefinition:
    with Timer(logger, "Get Adapter Definition"):
        d = AdapterDefinition(ADAPTER_KIND, ADAPTER_NAME)

        # The descriptions carry WORKED EXAMPLES, not just prose. Both of these
        # fields are filled in wrong on a first attempt often enough to be
        # worth the words: the username gets typed without its domain, and the
        # server gets pasted as a URL. A URL is now trimmed to its host and
        # port (perfsvc.split_host), and an IP works once its certificate is
        # accepted, because the accepted certificate is pinned rather than
        # hostname-matched.
        d.define_string_parameter(
            VC_HOST_PARAM,
            label="vCenter Server",
            description="FQDN or IP address of the vCenter Server managing the "
                        "vSAN cluster. Example: vc01.example.com. A URL such as "
                        "https://vc01.example.com/ is trimmed to the host; a "
                        "port other than 443 can be given as "
                        "vc01.example.com:8443.",
            required=True,
        )
        d.define_string_parameter(
            VC_USER_PARAM,
            label="vCenter username",
            description="Must include the domain. Example: "
                        "vsanmon@vsphere.local -- a bare username without "
                        "@vsphere.local will not authenticate. Read-only is "
                        "sufficient: System.View and System.Read propagated "
                        "from the vCenter root, no cluster edit rights.",
            required=True,
        )
        # NOTE: lib 1.1.0 has no define_bool_parameter; an enum of "true"/"false"
        # is the supported equivalent.
        # 1383 of 1636 modelled metrics (84%) are referenced by no shipped
        # view, and 45 of the 69 entity types by none at all. Every metric
        # stays DECLARED in describe, so switching this to "all" surfaces them
        # without a new pak -- but by default we do not query those 45 entity
        # types, which is 45 fewer round trips per cycle. The vSAN perf API
        # returns all of an entity's metrics in one call, so narrowing within
        # an entity saves storage rather than time.
        # OFF by default since 2026-10-21. See CLAUDE.md rule 1. Attaching to a
        # vCenter object means asserting that object's COMPLETE child list,
        # which destroys whatever the owning adapter had there. With a second
        # pack writing the same lists it cost 26 of 28 VMs their HostSystem
        # parent. Our objects are orphaned with this off -- views that traverse
        # from a vCenter object will not find them -- and that is the lesser
        # harm until the pack owns its own hierarchy.
        d.define_enum_parameter(
            VC_ATTACH_PARAM,
            values=["true", "false"],
            default="true",
            label="Attach objects to vCenter inventory",
            description="True is the default because every dashboard in this "
                        "pack resolves its views by descendant from a vCenter "
                        "cluster: with this false, the objects are standalone "
                        "and the dashboards render nothing. Operations replaces "
                        "an object's child list with the list a collection "
                        "reports, so with this true the pack reads the existing "
                        "children of each vCenter host, VM and cluster it "
                        "attaches to and reports them together with its own. Set "
                        "it false if another adapter also writes relationships "
                        "on those objects; the change takes effect on the next "
                        "collection with no reinstall.",
            required=False,
        )
        # Counted from the model rather than typed in: these figures changed
        # every time a view did, and a form that states a stale count is wrong
        # in front of the person choosing the setting.
        _ent_for_kind = {sp["kind"]: e for e, sp in perfsvc.MODEL.ENTITIES.items()}
        _in_scope = {e: set(m) for k, m in metric_scope.COVERED.items()
                     if (e := _ent_for_kind.get(k))}
        _all_metrics = sum(len(perfsvc.metrics_for(e)) for e in perfsvc.MODEL.ENTITIES)
        _scoped_metrics = sum(len(m & set(perfsvc.metrics_for(e)))
                              for e, m in _in_scope.items())
        _skipped_types = len(perfsvc.MODEL.ENTITIES) - len(_in_scope)
        d.define_enum_parameter(
            METRIC_SCOPE_PARAM,
            values=["dashboard", "all"],
            default="dashboard",
            label="Metrics to collect",
            description=f"dashboard (default) collects the {_scoped_metrics} metrics "
                        f"that the shipped views and dashboards render, from "
                        f"{len(_in_scope)} of {len(perfsvc.MODEL.ENTITIES)} entity "
                        f"types. Choose all to collect all {_all_metrics} metrics "
                        f"this pack defines, which adds {_skipped_types} entity-type "
                        f"queries to each collection. Every metric is defined either "
                        f"way, so switching to all needs no reinstall.",
            required=False,
        )
        d.define_enum_parameter(
            VERIFY_PARAM,
            values=["true", "false"],
            label="Verify vCenter certificate",
            description="Leave true. When you validate the connection, "
                        "Operations shows vCenter's certificate for review; "
                        "accept it and the adapter trusts exactly that "
                        "certificate, including a VMCA-issued one and when "
                        "the server field holds an IP address. If vCenter's "
                        "certificate is later replaced, collection fails "
                        "until the new one is accepted. False turns "
                        "certificate checking off entirely.",
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

            # Drive hardware, for the kinds that ARE a drive. Properties, not
            # metrics: a firmware level has a current value and no time
            # series, and a column left marked as a metric queries a time
            # range and finds nothing -- the mechanism that killed the host
            # services view.
            if spec["kind"] in perfsvc.DISK_HARDWARE_KINDS:
                ot.define_string_property("firmware", "Firmware")
                ot.define_string_property("driver", "Driver")
                ot.define_string_property("driver_version", "Driver Version")
                ot.define_string_property("model", "Model")
                ot.define_string_property("vendor", "Vendor")

            for metric in perfsvc.metrics_for(entity):
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
_PAGE = 1000

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



def _uniqueness_key(idents):
    """Hashable identity from {name: value}, order-independent."""
    return frozenset((str(n), str(v)) for n, v in idents.items())


def _resource_index(client, adapter_kind, object_kind):
    """Every object of one kind, keyed by its uniqueness identifiers.

    This used to be one query PER PARENT, filtered on identifiers. That never
    worked: /api/resources/query IGNORES identifier filtering. Verified against
    a live Operations -- a query naming one host's VMEntityObjectID returned
    all four hosts, and so did `resourceIdentifiers` and
    `GET ?identifiers[k]=v`. `propertyConditions` returned zero. Only `name`
    filters, and names are neither unique across vCenters nor stable, so they
    are not an identity.

    The 401 hid this for three releases: every query failed before anyone could
    notice that a successful one answers with the whole kind.

    So fetch each kind once and match here. Three calls instead of one per
    parent, and correct rather than ambiguous.
    """
    out = {}
    page = 0
    while True:
        try:
            batch = client.paged_get(
                "api/resources", "resourceList",
                params={"adapterKindKey": adapter_kind,
                        "resourceKind": object_kind,
                        "pageSize": _PAGE, "page": page})
        except Exception as exc:                 # noqa: BLE001
            logger.warning("could not list %s/%s from the suite API (%s)",
                           adapter_kind, object_kind, exc)
            return out
        found = batch.get("resourceList", batch.get("values", [])) or []
        for res in found:
            rk = res.get("resourceKey", {})
            idents = {i["identifierType"]["name"]: i.get("value", "")
                      for i in rk.get("resourceIdentifiers", [])
                      if str(i.get("identifierType", {})
                             .get("isPartOfUniqueness", "")).lower()
                      in ("true", "1")}
            rid = res.get("identifier") or res.get("id") or res.get("uuid")
            if idents and rid:
                out[_uniqueness_key(idents)] = rid
        if len(found) < _PAGE:
            break
        page += 1
    return out


def _key_from_suite_api(res):
    """Build an Object Key from a suite-api resourceList entry."""
    try:
        rk = res["resourceKey"]
        return Key(
            adapter_kind=rk["adapterKindKey"],
            object_kind=rk["resourceKindKey"],
            name=rk["name"],
            identifiers=[Identifier(i["identifierType"]["name"], i.get("value") or "",
                                    bool(i["identifierType"].get("isPartOfUniqueness")))
                         for i in rk.get("resourceIdentifiers", [])
                         if i.get("identifierType", {}).get("isPartOfUniqueness")],
        )
    except Exception as exc:                     # noqa: BLE001
        logger.warning("could not rebuild a key from suite-api entry: %s", exc)
        return None


def _preserve_existing_children(adapter_instance, vc_cache):
    """Add each vCenter object's CURRENT children to what we are about to claim.

    Returns the parents that are safe to put in the result. A parent whose
    existing children could not be read is omitted -- see the caller.

    The race is real and is the lesser evil: a child created between our read
    and our write is dropped until the owning adapter's next collection. That
    is one object for one cycle, against the previous behaviour of dropping
    every object every cycle.
    """
    try:
        api = adapter_instance.get_suite_api_client()
    except Exception as exc:                     # noqa: BLE001
        logger.warning("no suite-api client (%s); claiming NO vCenter "
                       "relationships this cycle rather than overwriting "
                       "theirs", exc)
        return []
    if api is None:
        logger.error("Operations supplied no cluster_connection_info, so there "
                     "is no suite-api client. Every vCenter parent will be "
                     "skipped and every object orphaned.")
        return []

    safe = []
    # The SDK acquires its token in __enter__ and NOWHERE else
    # (suite_api_client.py:79), and _to_vrops_request only sets the
    # Authorization header 'if self.token'. Calling the client without this
    # 'with' sends every request unauthenticated, which Operations answers
    # with 401 -- silently, because a 401 is a Response, not an exception.
    # That is what orphaned every object at every site from 1.4.3 to 1.4.4.
    with api as client:
        if not getattr(client, "token", ""):
            logger.error("suite-api token acquisition produced no token; "
                         "every request will be unauthenticated. Check the "
                         "credentials Operations injected for this instance.")
            return []
        # One index per kind, built once, instead of a query per parent.
        index = {}
        for ak, ok in sorted({(p.get_key().adapter_kind,
                               p.get_key().object_kind)
                              for p in vc_cache.values()}):
            index[(ak, ok)] = _resource_index(client, ak, ok)
            logger.info("indexed %d %s/%s objects from the suite API",
                        len(index[(ak, ok)]), ak, ok)
        if not any(index.values()):
            logger.error("the suite API returned no objects for any vCenter "
                         "kind we attach to. Every object will be orphaned. "
                         "This is a collection failure, not a content problem.")
            return []

        for parent in vc_cache.values():
            key = parent.get_key()
            want = _uniqueness_key({n: i.value
                                    for n, i in key.identifiers.items()})
            ident = index.get((key.adapter_kind, key.object_kind), {}).get(want)
            if ident is None:
                logger.warning("no %s in the suite API matches %s on %s; "
                               "leaving it out rather than claiming its "
                               "children", key.object_kind, key.name,
                               sorted(n for n, _ in want))
                continue
            try:
                existing = client.paged_get(
                    f"api/resources/{ident}/relationships/children",
                    "resourceList")
            except Exception as exc:             # noqa: BLE001
                logger.warning("could not read children of %s (%s); leaving "
                               "it out", parent.get_key().name, exc)
                continue
            ours = {k for k in parent.get_children()}
            for res in existing.get("resourceList",
                                    existing.get("values", [])) or []:
                key = _key_from_suite_api(res)
                if key is not None and key not in ours:
                    parent._children.add(key)
            safe.append(parent)
    return safe


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


def _scope_for(adapter_instance: AdapterInstance):
    """{entity: {metric}} to collect, or None for everything.

    metric_scope.COVERED is keyed by RESOURCE KIND because that is what the
    views name; perfsvc wants ENTITY ids. The model holds both, so translate
    here rather than duplicating the mapping in the generated file.
    """
    if _cfg(adapter_instance, METRIC_SCOPE_PARAM, "dashboard").strip().lower() == "all":
        return None
    ent_for_kind = {spec["kind"]: ent
                    for ent, spec in perfsvc.MODEL.ENTITIES.items()}
    scope = {}
    for kind, metrics in metric_scope.COVERED.items():
        ent = ent_for_kind.get(kind)
        if ent:
            scope[ent] = set(metrics)
    return scope


def _cfg(adapter_instance: AdapterInstance, key: str, default: str = "") -> str:
    return adapter_instance.get_identifier_value(key) or default


def _verify(adapter_instance: AdapterInstance) -> bool:
    return _cfg(adapter_instance, VERIFY_PARAM, "true").strip().lower() in (
        "true", "1", "yes")


def _password(adapter_instance: AdapterInstance) -> str:
    return adapter_instance.get_credential_value(VC_PASS_CRED) or ""


def _accepted_pems(adapter_instance: AdapterInstance) -> List[str]:
    """Certificates Operations passes for this account.

    That is the leaves the user accepted for it plus every CA the
    Operations cluster trusts globally, on every test and collect. The SDK
    applies them to nothing, so perfsvc.connect does. Each entry is read on
    its own: one that cannot be read is logged and skipped, and the rest are
    still used.
    """
    pems = []
    certs = list(adapter_instance.get_certificates() or [])
    for i, cert in enumerate(certs, 1):
        try:
            pem = cert.get_certificate_string()
        except Exception as exc:                    # noqa: BLE001
            logger.warning("certificate %d of %d from Operations could not "
                           "be read (%s); skipped", i, len(certs),
                           type(exc).__name__)
            continue
        if pem and pem != "None":
            pems.append(pem)
    logger.info("Operations passed %d certificate(s) for this account",
                len(pems))
    return pems


def _connect(adapter_instance: AdapterInstance):
    host, port = perfsvc.split_host(_cfg(adapter_instance, VC_HOST_PARAM))
    return perfsvc.connect(
        host,
        _cfg(adapter_instance, VC_USER_PARAM),
        _password(adapter_instance),
        verify=_verify(adapter_instance),
        accepted_pems=_accepted_pems(adapter_instance),
        port=port,
    )


def _cluster_label(cluster) -> str:
    """The cluster's name, or its MoRef if the name cannot be read.

    Reading .name is a call to vCenter, and a cluster deleted since the
    inventory was listed raises ManagedObjectNotFound; getattr's default
    covers only AttributeError. _moId is local.
    """
    try:
        return cluster.name
    except Exception:                               # noqa: BLE001
        return getattr(cluster, "_moId", "?")


def _not_vsan(cluster) -> bool:
    """True only when the cluster's vSAN config says disabled.

    Every cluster is queried either way: a compute cluster that mounts a
    remote vSAN datastore may report vSAN disabled and still have
    Performance Service data. This only decides how a cluster that returned
    nothing is reported.
    """
    return perfsvc.vsan_enabled(cluster) is False


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
            # One query PER CLUSTER, NOT a full collection. This used to
            # call perfsvc.collect, which queries all 69 entity types; 99% of
            # the test's runtime was that call, and on a large cluster it
            # overran the Validate Connection timeout so a correctly
            # configured account was told the connection timed out. It then
            # probed clusters[0] only, so a compute-only first cluster failed
            # the test while the vSAN clusters would have collected, and a
            # broken second cluster passed it.
            failed, no_vsan = [], []
            for cluster in clusters:
                name, found = "?", 0
                try:
                    name = _cluster_label(cluster)
                    found, problem = perfsvc.probe(
                        mos["vsan-performance-manager"], cluster)
                except Exception as exc:            # noqa: BLE001
                    problem = perfsvc.fault_text(exc)
                if not found and _not_vsan(cluster):
                    # Nothing back from a cluster whose vSAN config says
                    # disabled is its normal state, not a failure.
                    no_vsan.append(name)
                    logger.info("%s: cluster %s has vSAN disabled, probe "
                                "returned nothing%s", host, name,
                                f" ({problem})" if problem else "")
                    continue
                if problem:
                    failed.append(f"{name} ({problem})")
                logger.info("%s: cluster %s, probe returned %d result(s)%s",
                            host, name, found,
                            f", problem: {problem}" if problem else "")
            if failed:
                result.with_error(
                    f"Connected to {host}, but the vSAN Performance Service "
                    f"did not answer on {len(failed)} of {len(clusters)} "
                    f"cluster(s): {'; '.join(failed)}. Check that it is "
                    f"enabled on each. Collection skips a cluster that does "
                    f"not answer and still collects the others.")
                return result
            if len(no_vsan) == len(clusters):
                result.with_error(
                    f"Connected to {host} and found {len(clusters)} cluster(s), "
                    f"none with vSAN enabled: {', '.join(sorted(no_vsan))}.")
                return result
            logger.info("%s: %d cluster(s) answered, %d with vSAN disabled",
                        host, len(clusters) - len(no_vsan), len(no_vsan))
        except perfsvc.PerfSvcError as exc:
            logger.warning("Test failed: %s", exc)
            result.with_error(str(exc))
        except Exception as exc:                    # noqa: BLE001
            logger.exception("Test failed")
            result.with_error(f"{host}: {perfsvc.fault_text(exc)}")
        finally:
            _safe_disconnect(si)
        return result


def get_endpoints(adapter_instance: AdapterInstance) -> EndpointResult:
    """Ask Operations to show vCenter's certificate for review and accept.

    What the user accepts comes back on every test and collect as
    get_certificates(), and perfsvc.connect pins it. With verification off
    nothing is checked, so no prompt: accepting would mean nothing.
    """
    with Timer(logger, "Get Endpoints"):
        result = EndpointResult()
        if not _verify(adapter_instance):
            return result
        try:
            host, port = perfsvc.split_host(_cfg(adapter_instance, VC_HOST_PARAM))
        except perfsvc.PerfSvcError as exc:
            # Test Connection reports the same error with its wording.
            logger.warning("no certificate endpoint: %s", exc)
            return result
        result.with_endpoint(perfsvc.endpoint_url(host, port))
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
            disk_hw = perfsvc.build_disk_hardware(
                si, clusters, mos.get("vsan-cluster-health-system"))
            logger.info("mapped %d hosts, %d VMs, %d clusters to vCenter objects",
                        len(parents.get("hosts", {})), len(parents.get("vms", {})),
                        len(parents.get("clusters", {})))
            vc_cache: dict = {}
            linked = 0
            # CLAUDE.md rule 1: off unless the operator explicitly opts in.
            # DEFAULT TRUE, and that is a deliberate exception to CLAUDE.md
            # rule 1 which the operator authorised on 2026-10-22. The views
            # resolve by `descendant` from a vCenter cluster, so with this off
            # every object is standalone and EVERY dashboard renders nothing --
            # measured, not assumed. The mitigations that make it acceptable:
            # this is now the only pack writing foreign child lists (netstats
            # 2.0.2 emits 0 of 77 parent links, MemoryTierAdvanced 2.2.0 emits
            # 0 foreign children, both measured in-image by digest), and the
            # read-modify-write race needs two concurrent writers. Setting the
            # parameter to false stops the writing immediately with no
            # reinstall; the cost is blank dashboards, which is visible and
            # reversible, unlike silent relationship loss.
            attach_vc = _cfg(adapter_instance, VC_ATTACH_PARAM,
                             "true").strip().lower() == "true"
            if not attach_vc:
                logger.info("not attaching to vCenter objects (%s=false). "
                            "Our objects are standalone; nothing writes child "
                            "lists on objects this pack does not own.",
                            VC_ATTACH_PARAM)

            total_problems: List[str] = []
            scope = _scope_for(adapter_instance)
            # One cluster that returns nothing -- Performance Service off, or
            # a fault -- used to raise out of this loop and lose every other
            # cluster's data with it. Each cluster now stands alone; the
            # cycle fails only if none answered. A failed cluster cannot be
            # shown in the UI without failing the cycle (with_error drops
            # every object), so it is logged as an ERROR every cycle instead.
            # Every cluster is queried; "no data" from one whose vSAN config
            # says disabled is its normal state and is logged at INFO.
            failed: List[str] = []
            no_vsan: List[str] = []
            collected = 0
            for cluster in clusters:
                cname = "?"
                try:
                    cname = _cluster_label(cluster)
                    objs, problems = perfsvc.collect(perf, cluster, scope=scope)
                except Exception as exc:            # noqa: BLE001
                    if _not_vsan(cluster):
                        no_vsan.append(cname)
                        logger.info("cluster %s has vSAN disabled; nothing "
                                    "collected (%s)", cname,
                                    perfsvc.fault_text(exc))
                        continue
                    logger.error("cluster %s not collected: %s", cname,
                                 perfsvc.fault_text(exc),
                                 exc_info=not isinstance(exc, perfsvc.PerfSvcError))
                    failed.append(f"{cname}: {perfsvc.fault_text(exc)}")
                    continue
                collected += 1
                total_problems.extend(f"{cname}: {p}" for p in problems)
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

                    if spec["kind"] in perfsvc.DISK_HARDWARE_KINDS:
                        hw = disk_hw.get(dict(key.idents).get("disk_uuid", ""))
                        for field, val in (hw or {}).items():
                            obj.with_property(field, val)

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
                        if not attach_vc:
                            break
                        parent = _vc_parent(vc_cache, parents, bucket, value)
                        if parent is not None:
                            parent.add_child(obj)
                            linked += 1
                        break

            if not collected:
                if failed:
                    raise perfsvc.PerfSvcError(
                        f"No cluster returned vSAN data ({len(failed)} of "
                        f"{len(clusters)} failed): " + "; ".join(failed[:3]))
                raise perfsvc.PerfSvcError(
                    f"{len(clusters)} cluster(s) visible, none with vSAN "
                    f"enabled: {', '.join(sorted(no_vsan))}.")
            total_problems.extend(f"cluster not collected: {f}" for f in failed)

            # Re-attach the children that already belonged to each vCenter
            # object before adding it to our result.
            #
            # THIS IS NOT OPTIONAL. The SDK serialises relationships
            # parent-centric -- one {"parent": key, "children": [...]} entry per
            # object in the result -- and the swagger contract describes that as
            # "the relationship of all objects", not a delta. So the moment a
            # vCenter object enters our result, we are asserting its COMPLETE
            # child set. Before this, we asserted it had only our children, and
            # Operations believed us: the cluster lost its four hosts and a
            # resource pool on every collection, and each host lost its VMs,
            # pods and datastores, until the vCenter adapter's next cycle put
            # them back. Measured, with timestamps -- our collect at 21:22:08
            # dropped them, vCenter's at 21:25:43 restored them.
            #
            # That damaged the whole instance, not just this pack's dashboards.
            #
            # There is no additive mode in the API, so the only way to add a
            # child without removing the others is to state the others too.
            # Fail CLOSED: if we cannot read an object's existing children we
            # leave that object out of the result entirely, losing our own
            # relationship for a cycle rather than destroying someone else's.
            kept = (_preserve_existing_children(adapter_instance, vc_cache)
                    if attach_vc else [])
            for parent in kept:
                result.add_object(parent)
            logger.info("linked %d objects to %d vCenter parents "
                        "(%d parents skipped: existing children unreadable)",
                        linked, len(kept), len(vc_cache) - len(kept))

            # Orphaning everything must not be silent. Without a parent, no
            # view can resolve from a host or cluster and every panel reports
            # the selected object as not applicable -- which reads as broken
            # content rather than a broken collection, and has sent several
            # investigations in the wrong direction.
            if not linked:
                total_problems.append(
                    "No vSAN object could be attached to any vCenter object. "
                    "Views will report the selected object as not applicable "
                    "and dashboards will be empty. Check the vCenter account "
                    "can read host and cluster configuration, and that this "
                    "adapter and the vCenter adapter point at the SAME "
                    "vCenter.")
                logger.error("ORPHANED: 0 of the collected objects attached "
                             "to a vCenter parent")

            if total_problems:
                # Loud on purpose. A silently dropped sample is how the io_type
                # collision survived a green test suite.
                logger.warning("%d collection problem(s); first few: %s",
                               len(total_problems), total_problems[:5])
        except Exception as exc:                    # noqa: BLE001
            # The template catches here and this adapter had dropped it, so
            # every PerfSvcError below -- bad password, untrusted certificate,
            # no clusters -- vanished. with_error puts the adapter instance in
            # an error state carrying this text.
            logger.exception("Collection failed")
            result.with_error(perfsvc.fault_text(exc))
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
        # No sys.exit(0) here. The generated template has one, and it is safe
        # there only because the template's collect() catches; a sys.exit in a
        # finally REPLACES an in-flight exception, so the process exited 0
        # with no result and no traceback, and Operations reported a generic
        # failure with nothing in adapter.log to say why.
        logger.info(Timer.graph())


if __name__ == "__main__":
    main(sys.argv[1:])
