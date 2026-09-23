"""
vSAN Performance Service collector.

Imports NOTHING from the VCF Operations SDK, so it is unit-testable and SDK
churn cannot break it.  adapter.py is the only file that touches the SDK.

WHY THIS EXISTS, and why there is no RateCache here:

perfsvc returns metrics already reduced into fixed 5-minute buckets --
`tcpTxPackets` reads 934, 1344, 998, ... rising and falling, not accumulating.
They are not cumulative since-boot counters, so there is no delta to compute
and no baseline to persist across processes.  The defect in REPORT.md 3b simply
does not arise on this source.

One source, never two gathering points for the same metric.  The host-scrape
path in vsanmetrics.py is retained but dormant; see docs/COLLECTION-DESIGN.md.
"""
from __future__ import annotations

import datetime
import os
import ssl
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Vendored vSAN bindings must be importable before pyVmomi types are used.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

from pyVmomi import VmomiSupport  # noqa: E402


class _Noop:
    """pyVmomi dropped stableVersions/publicVersions; the 2021 vSAN bindings
    still import them.  They only register a version string."""
    def Add(self, *a, **k) -> None:
        pass


for _n in ("stableVersions", "publicVersions"):
    if not hasattr(VmomiSupport, _n):
        setattr(VmomiSupport, _n, _Noop())

import vsanmgmtObjects        # noqa: E402,F401  registers the vSAN types
import vsanapiutils           # noqa: E402
from pyVim.connect import SmartConnect, Disconnect   # noqa: E402
from pyVmomi import vim                              # noqa: E402

try:
    from . import perfsvc_model as _model            # type: ignore
except ImportError:                                  # flat, as the container runs
    import perfsvc_model as _model                   # type: ignore

MODEL = _model

# Placeholder for an identity component an entityRefId does not carry.  See
# parse_ref: entity types mix aggregate and scoped refs.
AGGREGATE = "(all)"


@dataclass(frozen=True)
class ObjectKey:
    """Identity of one Operations object, parsed from an entityRefId.

    entityRefId is "<entity-type>:<uuid>[|<part>[|<part>]]" -- regular across
    every entity type observed.  The parts are named by the model.
    """
    entity: str
    idents: Tuple[Tuple[str, str], ...]

    def display(self, names: Optional[Dict[str, str]] = None) -> str:
        """Human-readable object name.

        perfsvc identifies everything by UUID and, unlike the host exposition,
        returns no friendly name alongside it. Without resolution every object
        in Operations reads as a bare UUID, which is unusable in a dashboard.
        `names` maps uuid -> label; anything unresolved falls back to the raw
        value rather than being hidden.
        """
        names = names or {}
        vals = [names.get(v, v) for _, v in self.idents]
        head, rest = vals[0], [v for v in vals[1:] if v and v != AGGREGATE]
        return f"{head} [{'/'.join(rest)}]" if rest else head


@dataclass
class Grouped:
    """Metrics for one object.  All gauges -- perfsvc pre-reduces."""
    gauges: Dict[str, float] = field(default_factory=dict)
    props: Dict[str, str] = field(default_factory=dict)


class PerfSvcError(RuntimeError):
    """Raised when the whole source is unusable.

    Deliberately loud.  The failure this guards against is the one observed on
    the host source: every target fails, each is skipped, and Operations is
    handed an empty *successful* collection with no error -- a silently
    non-collecting adapter nobody notices for days.
    """


def connect(host: str, user: str, password: str, verify: bool = False):
    """Returns (service_instance, clusters, vsan_mos)."""
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    try:
        si = SmartConnect(host=host, user=user, pwd=password, sslContext=ctx)
    except Exception as exc:
        raise PerfSvcError(
            f"vCenter login failed for {user}@{host}: {exc}. "
            f"Check the credential and that the account has at least the "
            f"Read-only role propagated from the vCenter root."
        ) from exc

    content = si.RetrieveContent()
    clusters: List = []

    def _walk(folder) -> None:
        for child in getattr(folder, "childEntity", []):
            if isinstance(child, vim.ClusterComputeResource):
                clusters.append(child)
            elif hasattr(child, "childEntity"):
                _walk(child)

    for dc in content.rootFolder.childEntity:
        if isinstance(dc, vim.Datacenter):
            _walk(dc.hostFolder)

    mos = vsanapiutils.GetVsanVcMos(
        si._stub, context=ctx,
        version=vsanapiutils.GetLatestVmodlVersion(host))
    return si, clusters, mos


def build_name_map(service_instance, clusters, perf) -> Dict[str, str]:
    """uuid -> human label, for every identifier type we can resolve.

    Best effort throughout: a lookup that fails leaves the UUID in place rather
    than failing the collection. Unresolvable ids are normal -- perfsvc retains
    entities after they leave inventory, so a deleted VM still has metrics.
    """
    names: Dict[str, str] = {}

    for cluster in clusters:
        try:
            names[cluster.name] = cluster.name          # harmless self-map
            for node in (perf.VsanPerfQueryNodeInformation(cluster) or []):
                uuid = getattr(node, "vsanNodeUuid", None)
                hostname = getattr(node, "hostname", None)
                if uuid and hostname:
                    names[uuid] = hostname
        except Exception:                                # noqa: BLE001
            pass
        try:
            cfg = getattr(getattr(cluster, "configurationEx", None),
                          "vsanConfigInfo", None)
            uuid = getattr(getattr(cfg, "defaultConfig", None), "uuid", None)
            if uuid:
                names[uuid] = cluster.name
        except Exception:                                # noqa: BLE001
            pass

    # ContainerView rather than walking childEntity: folder recursion missed
    # VMs (22 found against 30 referenced by perfsvc), which left vscsi and
    # virtual-machine objects named by bare UUID.
    view = None
    try:
        content = service_instance.RetrieveContent()
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True)
        for vm in view.view:
            cfg = getattr(vm, "config", None)
            if not cfg:
                continue
            # perfsvc references VMs by instanceUuid; config.uuid is the SMBIOS
            # id and matched nothing. Map both, instanceUuid last so it wins.
            for attr in ("uuid", "instanceUuid"):
                value = getattr(cfg, attr, None)
                if value:
                    names[value] = vm.name
    except Exception:                                    # noqa: BLE001
        pass
    finally:
        if view is not None:
            try:
                view.DestroyView()
            except Exception:                            # noqa: BLE001
                pass

    return names


def parse_ref(ref: str) -> Optional[ObjectKey]:
    """'<entity>:<uuid>|<part>' -> ObjectKey, or None if unmodelled."""
    if ":" not in ref:
        return None
    entity, _, tail = ref.partition(":")
    spec = MODEL.ENTITIES.get(entity)
    if spec is None:
        return None
    parts = tail.split("|")
    names = spec["identity"]

    # Arity VARIES within an entity type.  host-cpu returns both
    # "host-cpu:<uuid>" (the host-level aggregate) and
    # "host-cpu:<uuid>|cpu-8" (one per physical CPU) -- 61 objects per host
    # for 60 CPUs.  Operations rejects an object missing a required
    # identifier, so short refs are padded with a sentinel rather than
    # dropped: the aggregate is real data and worth keeping, it just is not
    # scoped to one CPU.
    idents = []
    for i, name in enumerate(names):
        if i < len(parts):
            idents.append((name, parts[i]))
        else:
            idents.append((name, AGGREGATE))
    # Any parts beyond what the model names are kept, so nothing is silently
    # merged into an existing object.
    for i in range(len(names), len(parts)):
        idents.append((f"part{i}", parts[i]))
    return ObjectKey(entity, tuple(idents))


def collect(perf, cluster, window_minutes: int = 15
            ) -> Tuple[Dict[ObjectKey, Grouped], List[str]]:
    """Query every modelled entity type; return the most recent sample of each.

    Operations collects on its own schedule and wants a point value, while
    perfsvc returns a series.  We take the last non-empty sample -- looking back
    a window rather than an instant, because the 5-minute buckets will not line
    up with the collection cycle.

    Returns (objects, problems).  `problems` is non-empty when an entity type
    errors; it is reported rather than swallowed.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(minutes=window_minutes)
    out: Dict[ObjectKey, Grouped] = {}
    problems: List[str] = []

    specs = [
        vim.cluster.VsanPerfQuerySpec(
            entityRefId=f"{ent}:*", startTime=start, endTime=now)
        for ent in sorted(MODEL.ENTITIES)
    ]
    for spec in specs:
        try:
            results = perf.VsanPerfQueryPerf([spec], cluster) or []
        except Exception as exc:
            problems.append(f"{spec.entityRefId}: {type(exc).__name__}: {exc}")
            continue
        for res in results:
            key = parse_ref(getattr(res, "entityRefId", "") or "")
            if key is None:
                problems.append(f"unmodelled entityRefId: {res.entityRefId}")
                continue
            g = out.setdefault(key, Grouped())
            for val in (getattr(res, "value", []) or []):
                mid = getattr(val, "metricId", None)
                label = getattr(mid, "label", None)
                raw = (getattr(val, "values", "") or "").strip()
                if not label or not raw:
                    continue
                last = _last_number(raw)
                if last is not None:
                    g.gauges[label] = last
            for name, value in key.idents:
                if value:
                    g.props[name] = value

    if not out:
        raise PerfSvcError(
            "Performance Service returned no data for any entity type. "
            "Check that the vSAN Performance Service is enabled on the cluster "
            "and that the account can read it."
            + (f" First problems: {problems[:3]}" if problems else "")
        )
    return out, problems


def _last_number(csv: str) -> Optional[float]:
    """Last parseable value in a comma-separated series."""
    for token in reversed(csv.split(",")):
        token = token.strip()
        if not token:
            continue
        try:
            return float(token)
        except ValueError:
            continue
    return None
