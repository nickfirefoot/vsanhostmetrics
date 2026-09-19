"""
Pure-logic layer for the vSAN host-metrics management pack.

Deliberately imports NOTHING from the VCF Operations SDK, so that:
  * it is unit-testable on any machine with plain python
  * SDK API churn cannot break the parsing or rate math
adapter.py is the only file that touches the SDK.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Beta scope: the nine TCP counters from /net/nics $getVsanNetworkStats.
# Left column = name on the wire.  Right column = Operations metric key.
# ---------------------------------------------------------------------------
TCP_COUNTERS: Dict[str, str] = {
    "vmware_esx_tcppkt_total":                  "tcpPacketsTotal",
    "vmware_esx_tcppkt_bytes_total":            "tcpBytesTotal",
    "vmware_esx_tcppkt_rcvoopack_total":        "rcvOutOfOrderPackets",
    "vmware_esx_tcppkt_rcvdupack_total":        "rcvDuplicateAcks",
    "vmware_esx_tcppkt_rcvduppack_total":       "rcvDuplicatePackets",
    "vmware_esx_tcppkt_sndrexmitpack_total":    "sndRetransmitPackets",
    "vmware_esx_tcppkt_sack_rcv_blocks_total":  "sackRcvBlocks",
    # NOTE: the HELP strings for the next two are swapped on the host relative
    # to the underlying BSD TCP MIB fields.  Trust the metric NAME:
    #   sack_send_blocks = SACK blocks this host emitted
    #   sack_rexmits     = retransmits this host performed due to SACK
    "vmware_esx_tcppkt_sack_send_blocks_total": "sackSendBlocks",
    "vmware_esx_tcppkt_sack_rexmits_total":     "sackRetransmits",
}

# Labels that identify WHICH thing a sample belongs to (become resource
# identifiers).  Everything else on the sample is discarded.
ID_LABELS = ("host_uuid", "hostname", "stack", "vsan_cluster_uuid")

_SAMPLE_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][A-Za-z0-9_:]*)'
    r'(?:\{(?P<labels>[^}]*)\})?'
    r'\s+(?P<value>[^\s]+)'
)
_LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Sample:
    name: str
    labels: Tuple[Tuple[str, str], ...]   # sorted, so it is hashable + stable
    value: float

    def label(self, k: str, default: str = "") -> str:
        return dict(self.labels).get(k, default)


def parse(text: str, keep: Optional[Dict[str, str]] = None) -> Iterator[Sample]:
    """Parse Prometheus text exposition.  If `keep` is given, only yield
    samples whose name is a key of it."""
    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        m = _SAMPLE_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if keep is not None and name not in keep:
            continue
        raw = m.group("value")
        try:
            value = float(raw)
        except ValueError:
            continue                      # NaN / +Inf / malformed
        labels = tuple(sorted(_LABEL_RE.findall(m.group("labels") or "")))
        yield Sample(name, labels, value)


def scrape(host: str,
           token: str,
           *,
           cafile: Optional[str] = None,
           verify: bool = True,
           timeout: int = 30) -> str:
    """GET https://<host>/vsanmetrics with a bearer token.

    verify=False is for bring-up only.  In the pak, get_endpoints() hands the
    host certificate to Operations, which puts it in the trust store; then
    leave verify=True and pass cafile=None.
    """
    ctx = ssl.create_default_context(cafile=cafile)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f"https://{host}/vsanmetrics",
        headers={"Authorization": f"Bearer {token}",
                 "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
        gzipped = (resp.headers.get("Content-Encoding") == "gzip")
    if gzipped or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


@dataclass
class RateCache:
    """Cumulative-counter -> per-second rate.

    Every /vsanmetrics `_total` is cumulative since boot, so the adapter owns
    the delta.  Three cases this handles:

      first observation   no baseline yet -> emit nothing for that series
      counter reset       dv < 0          -> skip that series
      host reboot         every counter resets at once -> drop the whole host
                          for this interval rather than emitting garbage

    State MUST outlive the process.  commands.cfg runs
    `python app/adapter.py collect` per collection, so a fresh interpreter
    starts every interval and an in-memory baseline is always empty -- the
    adapter would never emit a single rate.  Set `path` and the baseline is
    persisted there instead, surviving for as long as the container does.

    `time.monotonic()` is CLOCK_MONOTONIC on Linux, which is kernel-wide, so
    timestamps stay comparable across those separate processes and are immune
    to NTP steps.  Leave `path` unset (the default) and behaviour is purely
    in-memory, which is what the unit tests use.
    """
    _prev: Dict[tuple, Tuple[float, float]] = field(default_factory=dict)
    path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.path:
            self._load()

    def _load(self) -> None:
        """Best-effort.  A missing or corrupt cache just costs one interval."""
        try:
            with open(self.path) as fh:                  # type: ignore[arg-type]
                raw = json.load(fh)
        except (OSError, ValueError):
            return
        for entry in raw.get("series", []):
            try:
                key = (entry["scope"], entry["name"],
                       tuple((k, v) for k, v in entry["labels"]))
                self._prev[key] = (float(entry["t"]), float(entry["v"]))
            except (KeyError, TypeError, ValueError):
                continue

    def _save(self) -> None:
        """Atomic replace, so a killed collection cannot leave a torn file."""
        if not self.path:
            return
        payload = {"series": [
            {"scope": k[0], "name": k[1], "labels": [list(p) for p in k[2]],
             "t": t, "v": v}
            for k, (t, v) in self._prev.items()
        ]}
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def rates(self,
              scope: str,
              samples: List[Sample],
              now: Optional[float] = None) -> Tuple[Dict[tuple, float], int]:
        """Returns ({series_key: rate_per_second}, reset_count).

        `scope` namespaces the cache so two hosts never collide.
        """
        now = time.monotonic() if now is None else now
        staged: Dict[tuple, Tuple[float, float]] = {}
        out: Dict[tuple, float] = {}
        resets = 0

        for s in samples:
            key = (scope, s.name, s.labels)
            prev = self._prev.get(key)
            staged[key] = (now, s.value)
            if prev is None:
                continue
            dt = now - prev[0]
            dv = s.value - prev[1]
            if dt <= 0:
                continue
            if dv < 0:
                resets += 1
                continue
            out[key] = dv / dt

        # A reboot zeroes every since-boot counter simultaneously.  If a
        # majority went backwards, this is not one bad counter -- discard.
        if resets and resets >= max(2, len(staged) // 2):
            out = {}

        self._prev.update(staged)
        self._save()
        return out, resets

    def forget(self, scope: str) -> None:
        """Drop a host's baselines, e.g. after it leaves the config."""
        for k in [k for k in self._prev if k[0] == scope]:
            del self._prev[k]
        self._save()


def derive_percentages(by_key: Dict[str, float]) -> Dict[str, float]:
    """Ratios Operations can alert on directly, in percent.

    Emit these rather than numerator+denominator: a symptom definition cannot
    divide two metrics, so shipping only the raw rates leaves you unalertable.

    CAVEAT on the denominator.  tcpPacketsTotal is ALL packets processed by
    ESX TCP, almost certainly rx+tx, while rcvOutOfOrderPackets and
    rcvDuplicateAcks are receive-side only.  Broadcom's thresholds
    (<0.1% healthy / 0.1-0.5% warn / >1.0% critical for out-of-order) come
    from the tcprx section of net-stats, i.e. relative to RECEIVED packets.
    Using the combined total understates receive-side rates by roughly 2x.
    Before this pak goes past beta, replace the denominator with an rx-only
    count -- either another name from getVsanNetworkStats or rxPackets from
    the vsan-vnic-net entity via /vsanperf.
    """
    out: Dict[str, float] = {}
    total = by_key.get("tcpPacketsTotal")
    if not total or total <= 0:
        return out
    for src, dst in (
        ("rcvOutOfOrderPackets", "outOfOrderPct"),
        ("sndRetransmitPackets", "retransmitPct"),
        ("rcvDuplicateAcks",     "duplicateAckPct"),
        ("rcvDuplicatePackets",  "duplicatePacketPct"),
    ):
        v = by_key.get(src)
        if v is not None:
            out[dst] = 100.0 * v / total
    return out
