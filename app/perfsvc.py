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
import hashlib
import logging
import os
import re
import socket
import ssl
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

# Vendored vSAN bindings must be importable before pyVmomi types are used.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

# perfsvc logs through the adapter's root logger. This was MISSING while
# two call sites already used it, so the orphan diagnostic at
# build_parent_map would have raised NameError exactly when it fired --
# a crash in place of the message explaining the crash.
logger = logging.getLogger(__name__)

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
from pyVmomi import vim, vmodl                       # noqa: E402
from pyVmomi.Security import ThumbprintMismatchException  # noqa: E402

try:
    from . import perfsvc_model as _model            # type: ignore
except ImportError:                                  # flat, as the container runs
    import perfsvc_model as _model                   # type: ignore

MODEL = _model

# Entity types the live model omits because they returned nothing on the
# cluster it was generated against -- every OSA family is silent on ESA. Merged
# in so they are queried wherever they exist; absent ones simply return no
# data. See app/perfsvc_model_extra.py, which is explicitly provisional.
try:
    from . import perfsvc_model_extra as _extra      # type: ignore
except ImportError:                                  # flat, as the container runs
    try:
        import perfsvc_model_extra as _extra         # type: ignore
    except ImportError:
        _extra = None                                # type: ignore
if _extra is not None:
    for _e, _spec in _extra.ENTITIES.items():
        MODEL.ENTITIES.setdefault(_e, _spec)         # live model always wins

# Placeholder for an identity component an entityRefId does not carry.  See
# parse_ref: entity types mix aggregate and scoped refs.
AGGREGATE = "(all)"


# Short, readable suffix per entity type, appended when an object's identity
# yields a bare name. Without it every host-scoped kind renders as just the
# hostname -- a dozen children of one host, all reading "esxi02.example.com",
# distinguishable only by icon. The generated model labels are title-cased
# from the entity id ("Cmmds Net", "Vsan Esa Disk Layer"), so they are
# overridden here rather than shown.
KIND_SUFFIX = {
    "cluster-domclient": "DOM Client", "cluster-domcompmgr": "DOM Comp Mgr",
    "cluster-domowner": "DOM Owner", "cluster-rdt-network-latency": "RDT Latency",
    "cluster-zdom-top-stats": "ZDOM Top Stats", "vsan-cluster-capacity": "Capacity",
    "vsan-dp-historical-stats": "Data Protection",
    "cmmds-net": "CMMDS Network", "host-domclient": "DOM Client",
    "host-domcompmgr": "DOM Comp Mgr", "host-domowner": "DOM Owner",
    "host-vsansparse": "vSAN Sparse", "host-zdom-top-stats": "ZDOM Top Stats",
    "rdt-net": "RDT Network", "rdt-network-latency": "RDT Latency",
    "system-mem": "System Memory", "vsan-cpu": "CPU",
    "vsan-host-net": "Host Network", "vsan-memory": "Memory",
    "vsan-esa-disk-layer": "ESA Disk Layer", "vsan-esa-disk-scsifw": "ESA Disk SCSI",
    "virtual-disk": "Virtual Disk", "virtual-machine": "VM",
    "vnic-rdt-network-latency": "vNIC RDT Latency",
    # host-cpu carries a cpu identifier on scoped refs but arrives bare on the
    # per-host aggregate; zdom-vtx is bare always. Without these two the
    # aggregate collides with zdom-vtx on the plain hostname.
    "host-cpu": "CPU (all)", "zdom-vtx": "ZDOM VTX",
    "vsan-tcpip-stats": "TCP/IP", "vsan-vnic-net": "vNIC",
    "cluster-resync": "Resync", "disk-group": "Disk Group",
    "cache-disk": "Cache Disk", "capacity-disk": "Capacity Disk",
    "vsan-pnic-net": "pNIC", "vsan-host-net": "Host Network",
}


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
        if rest:
            return f"{head} [{'/'.join(rest)}]"
        suffix = KIND_SUFFIX.get(self.entity)
        return f"{head} — {suffix}" if suffix else head


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


def split_host(value: str) -> Tuple[str, int]:
    """The vCenter field as typed -> (host, port).

    The field is documented as a hostname, and people paste URLs into it:
    " https://vc01.example.com/ui " became https://https://... in the
    certificate prompt and an unresolvable host in SmartConnect, which also
    takes no port from the host string. One normaliser, used by the endpoint
    Operations fetches the certificate from AND by the connection, so the
    certificate accepted is the one the connection meets.
    """
    raw = (value or "").strip()
    if not raw:
        raise PerfSvcError("No vCenter Server configured.")
    try:
        parts = urlsplit(raw if "//" in raw else f"//{raw}")
        host, port = parts.hostname, parts.port or 443
    except ValueError as exc:
        raise PerfSvcError(f"vCenter Server {raw!r} is not a host name, "
                           f"IP address or URL: {exc}") from exc
    if not host:
        raise PerfSvcError(f"vCenter Server {raw!r} has no host name in it.")
    return host, port


def endpoint_url(host: str, port: int = 443) -> str:
    """https URL for the certificate prompt, IPv6-safe."""
    name = f"[{host}]" if ":" in host else host
    return f"https://{name}" if port == 443 else f"https://{name}:{port}"


# Seconds pyVmomi waits on any single HTTP request to vCenter -- the
# connect, or the reply to one call -- before giving up. The Cloud Proxy puts
# no timeout on a collection, so without one a vCenter that accepts the
# connection and then stalls holds that collection forever. A whole
# collection of the lab's ESA cluster (33 entity-type queries plus the
# inventory reads) takes about a minute, so no single request should come
# near two.
HTTP_TIMEOUT_S = 120


def usable_certificates(pems: Sequence[str]) -> List[Tuple[bytes, str]]:
    """[(der, sha256 hex)] for every received certificate that parses.

    Operations sends this account's accepted certificates PLUS every CA the
    cluster trusts globally, one PEM each. One that does not parse -- an
    empty or "None" entry, stray whitespace, a truncated body -- is logged
    and skipped, so a good certificate later in the list is still used.
    Parsed by OpenSSL itself, the same parser the trust store uses.
    """
    out: List[Tuple[bytes, str]] = []
    pems = list(pems or ())
    for i, pem in enumerate(pems, 1):
        try:
            der = ssl.PEM_cert_to_DER_cert(str(pem).strip())
            ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(
                cadata=der)
        except Exception as exc:                          # noqa: BLE001
            logger.warning("received certificate %d of %d is not a usable "
                           "certificate (%s); skipped", i, len(pems),
                           type(exc).__name__)
            continue
        out.append((der, hashlib.sha256(der).hexdigest()))
    return out


def _anchored_context(certs: Sequence[Tuple[bytes, str]]) -> ssl.SSLContext:
    """The container's CA bundle plus every received certificate as a trust
    anchor, hostname checking on.

    A CA Operations trusts globally then validates vCenter's chain the way
    it does for Operations itself; an accepted leaf validates too, while its
    name matches and it is in date. PARTIAL_CHAIN lets an intermediate or a
    leaf act as an anchor; without it OpenSSL accepts only a self-signed
    root, and an issuing CA on its own would not verify.
    """
    ctx = ssl.create_default_context()
    for der, _ in certs:
        ctx.load_verify_locations(cadata=der)
    if certs:
        ctx.verify_flags |= getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    return ctx


def presented_sha256(host: str, port: int) -> Optional[str]:
    """SHA-256 of the leaf vCenter presents, read without trusting it.

    Only a TLS handshake: nothing is sent on the connection. Used to choose
    the certificate to pin, and to put both sides of a mismatch in the error.
    """
    ctx = ssl._create_unverified_context()
    try:
        with socket.create_connection((host, port), timeout=HTTP_TIMEOUT_S) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
    except Exception as exc:                              # noqa: BLE001
        logger.warning("could not read the certificate %s:%d presents: %s",
                       host, port, fault_text(exc))
        return None


def fault_text(exc: BaseException) -> str:
    """Readable text for an exception: a pyVmomi fault's msg, not its repr.

    str() of a vmodl fault is a multi-line dump (dynamicType = <unset>,
    dynamicProperty = [] ...), which is what the UI showed.
    """
    if isinstance(exc, vmodl.MethodFault):
        name = getattr(type(exc), "__name__", "fault")
        msg = getattr(exc, "msg", None)
        return f"{name}: {msg}" if msg else name
    return f"{type(exc).__name__}: {exc}"


def connect(host: str, user: str, password: str, verify: bool = True,
            accepted_pems: Sequence[str] = (), port: int = 443):
    """Returns (service_instance, clusters, vsan_mos).

    `accepted_pems` is what Operations passes as certificate_config: the
    leaves the user accepted for this account (Review and accept stores the
    presented leaf only), plus every CA the Operations cluster trusts
    globally. Where Operations already trusts vCenter through such a CA, no
    accept dialog appears and only the CAs arrive. Certificate handling,
    with verify on:

    1. Normal verification, hostname included, against the container's CA
       bundle plus every received certificate as an anchor. A vCenter whose
       CA Operations trusts, or whose accepted leaf matches its name, passes
       here.
    2. Otherwise the leaf vCenter presents must EXACTLY match a received
       certificate (SHA-256), pinned with pyVmomi's thumbprint. That is what
       accepting a certificate means in Operations: the pin replaces the
       chain, hostname and expiry checks, so an accepted VMCA certificate, an
       IP address in the server field and an accepted certificate that has
       expired all work. pyVmomi checks the pin on each connection before
       anything -- the login included -- is sent on it.

    Before this, the received certificates were never read: the prompt was
    shown, the answer ignored, and the default (verify on) failed against
    every VMCA-signed vCenter.

    With verify off, nothing is checked. That is the operator's explicit
    choice, and the only path that uses an unverified connection.
    """
    if not verify:
        ctx = ssl._create_unverified_context()
        return _inventory(_login(host, port, user, password, ctx, None),
                          ctx, None)

    certs = usable_certificates(accepted_pems)
    ctx = _anchored_context(certs)
    try:
        si = _login(host, port, user, password, ctx, None)
    except ssl.SSLCertVerificationError as exc:
        untrusted = exc
    else:
        return _inventory(si, ctx, None)

    why = getattr(untrusted, "verify_message", None) or str(untrusted)
    accepted = [sha for _, sha in certs]
    presented = presented_sha256(host, port)
    if presented and presented in accepted:
        # The version probe SmartConnect makes before logging in
        # (vimServiceVersions.xml) runs on this context and is NOT pinned; it
        # carries no credential. The login and every call after it go
        # through stubs that check the pin first.
        ctx = ssl._create_unverified_context()
        try:
            si = _login(host, port, user, password, ctx, presented)
        except _PinMismatch as exc:
            # vCenter presented a different certificate to the login than
            # to the look a moment earlier.
            presented = exc.actual or presented
        else:
            logger.info("%s: certificate not trusted by chain (%s); matched "
                        "the certificate accepted in Operations (sha256 %s)",
                        host, why, presented)
            return _inventory(si, ctx, presented)

    seen = presented or "unreadable"
    if not accepted:
        raise PerfSvcError(
            f"vCenter certificate for {host} is not trusted "
            f"({why}; presented sha256 {seen}) and "
            f"Operations passed no certificate for this account. Edit the "
            f"account in Operations and click Validate Connection; it shows "
            f"vCenter's certificate for review. Accept it and the adapter "
            f"trusts exactly that certificate."
        ) from untrusted
    raise PerfSvcError(
        f"vCenter certificate for {host} is not trusted "
        f"({why}) and matches none of the "
        f"{len(accepted)} certificate(s) Operations passed for this account. "
        f"Presented sha256 {seen}; received sha256 {', '.join(accepted)}. "
        f"If vCenter's certificate was renewed or replaced, edit the account "
        f"in Operations, click Validate Connection and accept the new "
        f"certificate."
    ) from untrusted


class _PinMismatch(Exception):
    """The certificate presented is not the pinned one."""
    def __init__(self, actual: Optional[str]):
        super().__init__(f"presented sha256 {actual}")
        self.actual = actual


def _pin_mismatch(exc: Optional[BaseException]):
    """The ThumbprintMismatchException behind `exc`, or None.

    pyVmomi raises it from the first call on the stub -- RetrieveContent,
    before the login -- and SmartConnect re-raises it wrapped in
    vim.fault.HostConnectFault. Look through the chain rather than reading
    the message, which reported it as a login failure."""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, ThumbprintMismatchException):
            return exc
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


def _login(host, port, user, password, ctx, thumbprint):
    # SmartConnect's API-version probe opens its own connection with no
    # timeout argument; the socket default covers it. The adapter is a
    # one-shot process, but restore it anyway.
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(HTTP_TIMEOUT_S)
    try:
        return SmartConnect(host=host, port=port, user=user, pwd=password,
                            sslContext=ctx, thumbprint=thumbprint,
                            httpConnectionTimeout=HTTP_TIMEOUT_S)
    except ssl.SSLCertVerificationError:
        raise                                    # connect() decides
    except Exception as exc:
        mismatch = _pin_mismatch(exc)
        if mismatch is not None:
            raise _PinMismatch(getattr(mismatch, "actual", None)) from exc
        raise PerfSvcError(
            f"vCenter login failed for {user}@{host}: {fault_text(exc)}. "
            f"Check the credential and that the account has at least the "
            f"Read-only role propagated from the vCenter root."
        ) from exc
    finally:
        socket.setdefaulttimeout(previous)


def _inventory(si, ctx, thumbprint):
    """(si, clusters, vsan_mos) for a logged-in session, which is logged out
    again if this fails -- the caller never receives it to disconnect."""
    try:
        return _read_inventory(si, ctx, thumbprint)
    except Exception:
        try:
            Disconnect(si)
        except Exception:                                # noqa: BLE001
            pass
        raise


def _read_inventory(si, ctx, thumbprint):
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

    # The vSAN API version is taken from the bindings rather than probed.
    # vsanapiutils.GetLatestVmodlVersion fetched vsanServiceVersions.xml with
    # TLS verification switched off for the whole process, returned the
    # newest vsan version for anything but vSAN 6.6, and on any error fell
    # back to the plain vim version, after which vSAN calls failed with a
    # version error rather than the real cause.
    mos = vsanapiutils.GetVsanVcMos(
        si._stub, context=ctx,
        version=VmomiSupport.newestVersions.Get("vsan"),
        thumbprint=thumbprint, httpConnectionTimeout=HTTP_TIMEOUT_S)
    return si, clusters, mos


DISK_HARDWARE_KINDS = ("VsanEsaDiskLayer", "VsanEsaDiskScsifw",
                       "VsanCacheDisk", "VsanCapacityDisk")


def build_disk_hardware(service_instance, clusters,
                        _health_system=None) -> Dict[str, Dict[str, str]]:
    """vSAN disk uuid -> {firmware, model, vendor, driver}.

    The Performance Service returns counters only -- nothing in its 1,035
    metrics carries a firmware or driver level. These come from the vCenter
    connection this pack already holds, so no new credential or endpoint.

    The join that makes it possible: `vsanSystem.QueryDisksForVsan()` returns,
    on ONE object, both the `vsanUuid` this pack already keys disks by and the
    `ScsiDisk` carrying model, vendor and `revision` (the firmware level).
    Verified against the lab 2026-10-22: 7 vsanUuids across 4 hosts, matching
    this pack's 7 VsanEsaDiskLayer objects exactly, 1:1.

    Driver is one hop further out, because it belongs to the controller rather
    than the drive: scsiTopology maps an adapter to its LUNs, and
    hostBusAdapter carries the driver name. A drive whose topology cannot be
    walked keeps its firmware and simply has no driver, rather than being
    dropped.

    Best effort throughout, like build_name_map: a host that raises is skipped
    and the rest still report. Firmware on three of four hosts beats a
    collection that fails because one host is unreachable.
    """
    out: Dict[str, Dict[str, str]] = {}
    hosts = []
    for cluster in clusters:
        hosts.extend(getattr(cluster, "host", []) or [])

    # Controller driver VERSION, which hostBusAdapter does not carry -- it
    # gives the module NAME only ("nvme_pcie"). The version lives in the HCL
    # section of the cluster health summary, keyed by controller device name,
    # so it joins to a disk through the same scsiTopology walk used below.
    #
    # QueryClusterHealthSummary is a READ. GetClusterHclInfo looks like the
    # obvious call and is not: its hostResults is empty until the HCL health
    # check has been RUN, which is an action on the cluster.
    version_for_hba: Dict[str, str] = {}
    if _health_system is not None:
        for cluster in clusters:
            try:
                summary = _health_system.VsanQueryVcClusterHealthSummary(
                    cluster=cluster, includeObjUuids=False, fields=["hclInfo"])
                for host_result in (getattr(
                        getattr(summary, "hclInfo", None),
                        "hostResults", None) or []):
                    for ctrl in (getattr(host_result, "controllers", None) or []):
                        dev = getattr(ctrl, "deviceName", "") or ""
                        ver = getattr(ctrl, "driverVersion", "") or ""
                        if dev and ver:
                            version_for_hba[dev] = ver
            except Exception as exc:                        # noqa: BLE001
                logger.info("HCL driver versions unavailable: %s",
                            type(exc).__name__)

    for host in hosts:
        try:
            vsan = host.configManager.vsanSystem
            disks = vsan.QueryDisksForVsan()
        except Exception as exc:                            # noqa: BLE001
            logger.info("disk hardware unavailable on %s: %s",
                        getattr(host, "name", "?"), type(exc).__name__)
            continue

        # lun key -> driver, by walking adapter -> target -> lun
        driver_for_lun: Dict[str, str] = {}
        hba_for_lun: Dict[str, str] = {}
        try:
            sd = host.config.storageDevice
            hba = {a.key: (getattr(a, "driver", "") or "",
                           getattr(a, "device", "") or "")
                   for a in (sd.hostBusAdapter or [])}
            for adapter in (sd.scsiTopology.adapter or []):
                drv, dev = hba.get(adapter.adapter, ("", ""))
                for target in (adapter.target or []):
                    for lun in (target.lun or []):
                        if drv:
                            driver_for_lun[lun.scsiLun] = drv
                        if dev:
                            hba_for_lun[lun.scsiLun] = dev
        except Exception as exc:                            # noqa: BLE001
            logger.debug("no scsi topology on %s: %s",
                         getattr(host, "name", "?"), type(exc).__name__)

        for entry in disks:
            uuid = (getattr(entry, "vsanUuid", "") or "").strip()
            if not uuid:
                continue            # a disk vSAN has not claimed has no uuid
            disk = entry.disk
            info = {
                "firmware": (getattr(disk, "revision", "") or "").strip(),
                "model": (getattr(disk, "model", "") or "").strip(),
                "vendor": (getattr(disk, "vendor", "") or "").strip(),
                "driver": driver_for_lun.get(getattr(disk, "key", ""), ""),
                "driver_version": version_for_hba.get(
                    hba_for_lun.get(getattr(disk, "key", ""), ""), ""),
            }
            out[uuid] = {k: v for k, v in info.items() if v}

    logger.info("resolved hardware detail for %d vSAN disks", len(out))
    return out


def build_name_map(service_instance, clusters, perf,
                   _mos: Optional[Dict] = None) -> Dict[str, str]:
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

            # virtual-disk refs are "<namespace-uuid>/<file>.vmdk", which is
            # the datastore path with the "[datastore] " prefix stripped. The
            # attached VM's backing fileName is the same path, so inventory
            # resolves them without any extra privilege.
            #
            # The obvious route -- vStorageObjectManager.ListVStorageObject --
            # returns NoPermission for a read-only account (verified
            # 2026-09-23). Using it would raise this pack's required privilege
            # above read-only for cosmetics, which is the wrong trade for a
            # monitoring tool.
            for dev in (getattr(getattr(cfg, "hardware", None), "device", None) or []):
                if not isinstance(dev, vim.vm.device.VirtualDisk):
                    continue
                backing = getattr(dev, "backing", None)
                filename = getattr(backing, "fileName", None)
                if not filename:
                    continue
                path = _DS_PREFIX.sub("", filename)
                label = (getattr(getattr(dev, "deviceInfo", None), "label", None)
                         or f"key{dev.key}")
                display = f"{vm.name} [{label}]"
                # perfsvc emits the path with and without a leading slash --
                # one disk in 60 arrived as "/<uuid>/name.vmdk". Register both
                # rather than guessing which form a given ref will use.
                names[path] = display
                names["/" + path.lstrip("/")] = display
    except Exception:                                    # noqa: BLE001
        pass
    finally:
        if view is not None:
            try:
                view.DestroyView()
            except Exception:                            # noqa: BLE001
                pass

    # Physical disks: vsanUuid -> device display name. ESA presents disks via
    # storage POOLS, not disk groups, which is why the disk-group entity type
    # returns nothing on an ESA cluster.
    try:
        dms = _mos.get("vsan-disk-management-system") if _mos else None
        if dms is not None:
            for cluster in clusters:
                for host in getattr(cluster, "host", []) or []:
                    try:
                        managed = dms.QueryVsanManagedDisks(host)
                    except Exception:                    # noqa: BLE001
                        continue
                    for pool in (getattr(managed, "storagePools", None) or []):
                        for entry in (getattr(pool, "storagePoolDisks", None) or []):
                            uuid = getattr(entry, "vsanUuid", None)
                            label = _disk_label(getattr(entry, "disk", None))
                            if uuid and label:
                                names[uuid] = f"{label} ({host.name})"
    except Exception:                                    # noqa: BLE001
        pass

    return names


# t10.NVMe____Micron_7450_MTFDKCB1T9TFR_______________FCD815400175A000
#     ^bus    ^vendor/model tokens       ^padding     ^serial
_DS_PREFIX = re.compile(r"^\[[^\]]+\]\s*")
_T10 = re.compile(r"^t10\.(?P<bus>[A-Za-z0-9]+)_+(?P<body>.+)$")


def _disk_label(scsi) -> Optional[str]:
    """Readable disk name.

    displayName is "Local NVMe Disk (<canonical>)" and the canonical name pads
    the model field out to a fixed width with underscores, so the raw name runs
    ~94 characters of which twenty are padding.  Collapse the padding and drop
    the wrapper; keep the full serial, because a host can hold several disks of
    the same model and the serial is the only thing separating them.
    """
    display = getattr(scsi, "displayName", None)
    canonical = (getattr(scsi, "canonicalName", None)
                 or getattr(scsi, "deviceName", None))
    if not canonical:
        return display
    match = _T10.match(canonical)
    if not match:                        # naa.*/eui.* -- nothing to compact
        return display or canonical
    tokens = [t for t in match.group("body").split("_") if t]
    return " ".join([match.group("bus")] + tokens)


def _host_aliases(name):
    """Every spelling of a host name worth matching on.

    vCenter and the Performance Service do not have to agree on whether a host
    is "esxi01.example.com", "esxi01" or "ESXI01.", and an exact match on the
    wrong one yields no relationship rather than an error.
    """
    if not name:
        return []
    raw = str(name).strip().rstrip(".")
    low = raw.lower()
    out = [low]
    short = low.split(".", 1)[0]
    if short and short != low:
        out.append(short)
    return out


def build_parent_map(service_instance, clusters, perf,
                     _mos: Optional[Dict] = None) -> Dict[str, Dict[str, str]]:
    """Identity of the vCenter objects our objects should hang off.

    Operations already holds HostSystem, VirtualMachine and
    ClusterComputeResource objects from the built-in VMWARE adapter. Attaching
    to those is far more useful than inventing parents of our own: vSAN metrics
    then appear under the host an operator is already looking at, and traversal
    works without a custom traversal spec.

    The join, verified 2026-09-23 against the live instance: those objects are
    uniquely identified by `VMEntityObjectID` (the managed object reference,
    e.g. `host-27`) plus `VMEntityVCID` (the vCenter instance UUID). Both are
    readable through pyVmomi -- `_moId` and `content.about.instanceUuid` -- and
    the instanceUuid matched Operations' VMEntityVCID exactly.

    Returns {"vcid": <uuid>, "hosts": {vsan_host_uuid: moid},
             "vms": {vm_uuid: moid}, "clusters": {vsan_cluster_uuid: moid}}.

    Best effort: anything unresolved simply yields no relationship, never a
    failed collection.
    """
    out: Dict[str, Dict[str, str]] = {"hosts": {}, "vms": {}, "clusters": {},
                                      "disks": {}, "vdisks": {},
                                      # moid -> the object's REAL name in
                                      # vCenter. Without this the adapter
                                      # supplies a name of its own and
                                      # Operations overwrites the vCenter
                                      # object's, renaming every host to its
                                      # managed object reference.
                                      "names": {}}
    vcid = ""
    try:
        content = service_instance.RetrieveContent()
        vcid = getattr(content.about, "instanceUuid", "") or ""
    except Exception:                                    # noqa: BLE001
        content = None
    out["vcid"] = vcid                                   # type: ignore[assignment]
    if not vcid:
        # SINGLE POINT OF FAILURE, and it used to be silent. Every parent
        # lookup requires this value, so an empty one orphans EVERY object --
        # cluster-scoped and host-scoped alike -- with no error anywhere.
        # Downstream that presents as "the selected Object is not applicable"
        # on every view and empty panels on every dashboard, which looks like a
        # content problem and is not one. Days were lost to that.
        logger.error(
            "vCenter instanceUuid is empty (content.about unreadable). EVERY "
            "object will be orphaned: no vSAN object will attach to a host, VM "
            "or cluster, and every view will report the selected object as not "
            "applicable. This is a collection failure, not a content problem.")
        return out

    for cluster in clusters:
        # vSAN cluster uuid -> cluster MoRef
        try:
            cfg = getattr(getattr(cluster, "configurationEx", None),
                          "vsanConfigInfo", None)
            cuuid = getattr(getattr(cfg, "defaultConfig", None), "uuid", None)
            if cuuid:
                out["clusters"][cuuid] = cluster._moId
            out["names"][cluster._moId] = cluster.name
        except Exception:                                # noqa: BLE001
            pass

        # vSAN node uuid -> host MoRef.
        #
        # This used to join on HOSTNAME STRING EQUALITY, vCenter's host.name
        # against the Performance Service's node.hostname, and that is why the
        # pack worked on one lab and produced no host relationships at all on
        # every other one. The two agree only when a host was added to vCenter
        # by exactly the name vSAN reports. Added by IP, or by short name, or
        # with any difference in spelling or case, and the lookup misses, no
        # parent is resolved, every host-scoped object is orphaned, and every
        # host-scoped view reports it is not applicable for the selected
        # object. Cluster-scoped views keep working, because those join on the
        # vSAN cluster uuid and never touch a hostname.
        #
        # vCenter knows each host's vSAN node uuid directly, so the join needs
        # no string matching:
        #     host.configManager.vsanSystem.config.clusterInfo.nodeUuid
        # Verified against a live vCenter: all four hosts returned it.
        by_name: Dict[str, str] = {}
        for host in (getattr(cluster, "host", None) or []):
            try:
                moid = host._moId
                out["names"][moid] = host.name
                try:
                    node_uuid = (host.configManager.vsanSystem.config
                                 .clusterInfo.nodeUuid)
                except Exception:                        # noqa: BLE001
                    node_uuid = None
                if node_uuid:
                    out["hosts"][node_uuid] = moid
                for alias in _host_aliases(host.name):
                    by_name.setdefault(alias, moid)
            except Exception:                            # noqa: BLE001
                pass

        # Fallback for any host whose vsanSystem is unreadable: the old
        # hostname join, but case-insensitive and tolerant of short name
        # against FQDN, which covers most of the ways the two disagree.
        try:
            for node in (perf.VsanPerfQueryNodeInformation(cluster) or []):
                uuid = getattr(node, "vsanNodeUuid", None)
                if not uuid or uuid in out["hosts"]:
                    continue
                for alias in _host_aliases(getattr(node, "hostname", None)):
                    moid = by_name.get(alias)
                    if moid:
                        out["hosts"][uuid] = moid
                        break
        except Exception:                                # noqa: BLE001
            pass

    # Physical disks belong to the host that owns the storage pool. Same
    # QueryVsanManagedDisks walk that resolves their display names.
    try:
        dms = _mos.get("vsan-disk-management-system") if _mos else None
        if dms is not None:
            for cluster in clusters:
                for host in (getattr(cluster, "host", None) or []):
                    try:
                        managed = dms.QueryVsanManagedDisks(host)
                    except Exception:                    # noqa: BLE001
                        continue
                    for pool in (getattr(managed, "storagePools", None) or []):
                        for entry in (getattr(pool, "storagePoolDisks", None) or []):
                            uuid = getattr(entry, "vsanUuid", None)
                            if uuid:
                                out["disks"][uuid] = host._moId
                                out["names"][host._moId] = host.name
    except Exception:                                    # noqa: BLE001
        pass

    if content is not None:
        view = None
        try:
            view = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.VirtualMachine], True)
            for vm in view.view:
                cfg = getattr(vm, "config", None)
                if not cfg:
                    continue
                for attr in ("uuid", "instanceUuid"):
                    value = getattr(cfg, attr, None)
                    if value:
                        out["vms"][value] = vm._moId
                out["names"][vm._moId] = vm.name
                # A virtual-disk object is identified by its datastore path,
                # which is the attached VM's backing fileName. Both slash
                # forms, as in build_name_map.
                for dev in (getattr(getattr(cfg, "hardware", None), "device", None) or []):
                    if not isinstance(dev, vim.vm.device.VirtualDisk):
                        continue
                    filename = getattr(getattr(dev, "backing", None), "fileName", None)
                    if not filename:
                        continue
                    path = _DS_PREFIX.sub("", filename)
                    out["vdisks"][path] = vm._moId
                    out["vdisks"]["/" + path.lstrip("/")] = vm._moId
        except Exception:                                # noqa: BLE001
            pass
        finally:
            if view is not None:
                try:
                    view.DestroyView()
                except Exception:                        # noqa: BLE001
                    pass
    return out


# Metrics the Performance Service reports in PER-MILLE (parts per thousand),
# converted to percent on collection.
#
# Confirmed twice over: the service schema marks these permille, and
# tcpRcvdupackRate read 1-2 here while an independent host scrape measured
# 0.122 percent for the same quantity. Broadcom publish thresholds in PERCENT
# (out-of-order warning 0.1, critical 1.0), so a raw value of 1 sits on the
# warning line while looking like a count of one.
#
# Emitting percent means the number disagrees with the vSphere UI, which shows
# per-mille. That is the deliberate trade: a correct number that differs from
# the UI beats an ambiguous one that matches it. Labels carry "(%)" so the
# unit is visible without consulting documentation.
PERMILLE = {
    "ip6Errs",
    "ipErrs",
    "pauseCount",
    "pctMemUsed",
    "portRxDrops",
    "portTxDrops",
    "rxCrcErr",
    "rxErr",
    "rxFifoErr",
    "rxMissErr",
    "rxOvErr",
    "rxPacketsLossRate",
    "tcpErrs",
    "tcpHalfopenDropRate",
    "tcpRcvdupackRate",
    "tcpRcvduppackRate",
    "tcpRcvoopackRate",
    "tcpSackRcvBlocksRate",
    "tcpSackRexmitsRate",
    "tcpSackSendBlocksRate",
    "tcpTimeoutDropRate",
    "txCarErr",
    "txErr",
    "txPacketsLossRate",
}


def to_percent(metric: str, value: float) -> float:
    """Per-mille -> percent. Parts per thousand over ten is parts per hundred."""
    return value / 10.0 if metric in PERMILLE else value


def metrics_for(entity: str) -> List[str]:
    """Metrics worth collecting for an entity type.

    Drops every `<name>Actual` whose `<name>` is also present. Measured across
    a full collection: 201 such pairs, 201 identical values, zero differences.
    They are the same measurement under two names, so collecting both doubles
    the attribute count on the busiest entity types and puts two identical
    panels in front of an operator.

    `<name>Raw` is NOT dropped -- it differs from its base in practice
    (pauseCountRaw 224 against pauseCount 0) because it is the cumulative
    since-boot counter rather than the per-interval value.
    """
    metrics = set(MODEL.ENTITIES[entity]["metrics"])
    return sorted(m for m in metrics
                  if not (m.endswith("Actual") and m[:-6] in metrics))


def parse_ref(ref: str) -> Optional[ObjectKey]:
    """'<entity>:<uuid>|<part>' -> ObjectKey, or None if unmodeled."""
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


def vsan_enabled(cluster) -> Optional[bool]:
    """True/False from the cluster's vSAN config, None if it cannot be read.

    connect() returns every ClusterComputeResource, vSAN or not, and a
    compute-only cluster has no Performance Service to ask. None is treated
    as "try it" by the caller, so an unreadable config never hides a cluster.
    """
    try:
        cfg = getattr(getattr(cluster, "configurationEx", None),
                      "vsanConfigInfo", None)
        enabled = getattr(cfg, "enabled", None)
    except Exception:                                    # noqa: BLE001
        return None
    return None if enabled is None else bool(enabled)


PROBE_ENTITY = "cluster-domclient"


def probe(perf, cluster, entity: str = PROBE_ENTITY,
          window_minutes: int = 15) -> Tuple[int, Optional[str]]:
    """One query against one entity type. For Validate Connection ONLY.

    `collect` issues a separate VsanPerfQueryPerf per modelled entity type --
    69 round trips. That is right for a collection and badly wrong for a
    connection test: measured on a four-host lab, connecting and listing
    clusters takes 0.08 s and the full collection takes 13.1 s, so 99% of the
    test was work nobody asked for. On a large cluster that overruns the UI's
    Validate Connection timeout and the user is told the connection timed out
    when the credentials, privileges and network path are all fine.

    One query against a cluster-scoped entity proves the same three things:
    we authenticated, the account can see the cluster, and the Performance
    Service answers.

    Returns (result_count, problem). A problem of None means the service
    answered. An entity type being unsupported is NOT a problem -- it still
    proves the service is there.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(minutes=window_minutes)
    spec = vim.cluster.VsanPerfQuerySpec(
        entityRefId=f"{entity}:*", startTime=start, endTime=now)
    try:
        results = perf.VsanPerfQueryPerf([spec], cluster) or []
    except (vmodl.fault.InvalidArgument, vmodl.fault.NotSupported):
        return 0, None
    except Exception as exc:                             # noqa: BLE001
        return 0, fault_text(exc)
    return len(results), None


def collect(perf, cluster, window_minutes: int = 15,
            scope: Optional[Dict[str, Set[str]]] = None
            ) -> Tuple[Dict[ObjectKey, Grouped], List[str]]:
    """Query modeled entity types; return the most recent sample of each.

    Operations collects on its own schedule and wants a point value, while
    perfsvc returns a series.  We take the last non-empty sample -- looking back
    a window rather than an instant, because the 5-minute buckets will not line
    up with the collection cycle.

    `scope` is {entity: {metric, ...}}.  None means every entity and every
    metric, which is what the adapter passes when the instance asks for all
    metrics.  Otherwise only the listed entities are QUERIED -- and that is the
    only part that saves time, because the vSAN perf API returns every metric
    of an entity type in a single call.  Narrowing the metric set within an
    entity saves Operations storage, not a round trip.

    Returns (objects, problems).  `problems` is non-empty when an entity type
    errors; it is reported rather than swallowed.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(minutes=window_minutes)
    out: Dict[ObjectKey, Grouped] = {}
    problems: List[str] = []
    unsupported: List[str] = []

    wanted = sorted(MODEL.ENTITIES if scope is None
                    else (e for e in MODEL.ENTITIES if e in scope))
    if scope is not None:
        logger.info("querying %d of %d entity types (%d skipped: no shipped "
                    "view references them)", len(wanted), len(MODEL.ENTITIES),
                    len(MODEL.ENTITIES) - len(wanted))
    specs = [
        vim.cluster.VsanPerfQuerySpec(
            entityRefId=f"{ent}:*", startTime=start, endTime=now)
        for ent in wanted
    ]
    for spec in specs:
        try:
            results = perf.VsanPerfQueryPerf([spec], cluster) or []
        except (vmodl.fault.InvalidArgument, vmodl.fault.NotSupported):
            # Two ways an entity type says "not here": InvalidArgument when it
            # rejects a wildcard query, NotSupported when the feature is absent
            # (PMem on a cluster without it). Both are properties of the
            # deployment, not faults. Every advertised entity type is modelled
            # so any supported configuration is covered, so these are expected
            # on any given cluster -- reporting each one every cycle would
            # drown the real problems this list exists to surface.
            unsupported.append(spec.entityRefId.split(":")[0])
            continue
        except Exception as exc:
            problems.append(f"{spec.entityRefId}: {type(exc).__name__}: {exc}")
            continue
        for res in results:
            ref = getattr(res, "entityRefId", "") or ""
            # An entity type with no objects echoes the query back verbatim --
            # "disk-group:*". Parsing that yields an object whose identifier is
            # literally "*". Skip it; it is an empty result, not an object.
            if "*" in ref:
                continue
            key = parse_ref(ref)
            if key is None:
                problems.append(f"unmodeled entityRefId: {res.entityRefId}")
                continue
            g = out.setdefault(key, Grouped())
            keep = set(MODEL.ENTITIES[key.entity]["metrics"])
            if scope is not None:
                keep &= scope.get(key.entity, set())
            for val in (getattr(res, "value", []) or []):
                mid = getattr(val, "metricId", None)
                label = getattr(mid, "label", None)
                raw = (getattr(val, "values", "") or "").strip()
                if not label or not raw:
                    continue
                if label.endswith("Actual") and label[:-6] in keep:
                    continue                     # identical to its base
                last = _last_number(raw)
                if last is not None:
                    g.gauges[label] = to_percent(label, last)
            for name, value in key.idents:
                if value:
                    g.props[name] = value

    if unsupported:
        # One summary line, not one per entity per cycle.
        problems.append(
            f"{len(unsupported)} entity type(s) not available on this "
            f"cluster (feature absent or wildcard unsupported): "
            f"{', '.join(sorted(unsupported))}")

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
