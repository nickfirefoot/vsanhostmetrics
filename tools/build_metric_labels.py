#!/usr/bin/env python3
"""Generate app/metric_labels.py -- readable labels and real units.

Two problems this fixes, both found by looking at the deployed pack:

  * Labels were produced by camelCase-splitting the metric id, so txSbSpaceMin
    became "Tx sb space min". Derived from the name, and meaningless: "Sb" is
    socket buffer.
  * Metrics carried no unit at all, so tcpRxThroughput rendered as a bare
    number with no way to tell bytes/s from bits/s.

Units come from HCIBench's Grafana dashboards, which cover 1,523 metric ids
against the same underlying vSAN stats. Labels are expanded here, because
HCIBench's titles are panel-level and shared across several metrics
("Space Available In RX Socket/TX Socket And TX Context Queue").

Usage:
    python3 tools/build_metric_labels.py /tmp/hcib_labels.json
"""
from __future__ import annotations
import json, re, sys, collections

# HCIBench unit -> (SDK Units path, human suffix). None = dimensionless.
UNIT_MAP = {
    "binBps":  ("DATA_RATE.BIBYTE_PER_SECOND", "B/s"),
    "Bps":     ("DATA_RATE.BYTE_PER_SECOND",   "B/s"),
    "bytes":   ("DATA_SIZE.BYTE",              "bytes"),
    "mbytes":  ("DATA_SIZE.MEGABYTE",          "MB"),
    "µs":      ("TIME.MICROSECONDS",           "µs"),
    "us":      ("TIME.MICROSECONDS",           "µs"),
    "ns":      ("TIME.NANOSECONDS",            "ns"),
    "ms":      ("TIME.MILLISECONDS",           "ms"),
    "s":       ("TIME.SECONDS",                "s"),
    "iops":    ("MISC.IO_OPERATIONS_PER_SECOND", "IOPS"),
    "percent": ("RATIO.PERCENT",               "%"),
    "percentunit": ("RATIO.PERCENT",           "%"),
    "short":   (None, ""),
    "none":    (None, ""),
}

# Abbreviations, longest first so "duppack" wins over "pack".
# Applied as SUBSTRING replacements within a token, longest first --
# camelCase splitting yields compounds like "Rcvoopack" that no whole-token
# lookup would match.
ABBREV = [
    ("sbspace", "socket buffer space"), ("oopack", " out-of-order packets"),
    ("dupack", " duplicate ACKs"), ("duppack", " duplicate packets"),
    ("rexmit", " retransmit"), ("ctxq", "context queue"),
    ("qlat", "queue latency"), ("recved", "received"),
    ("ckpt", "checkpoint"), ("sb", "socket buffer"), ("ctx", "context"),
    ("lat", "latency"), ("pkt", "packet"), ("pct", "percent"),
    ("util", "utilization"), ("cnt", "count"),
    ("vmdisk", "VM disk"), ("stddev", "standard deviation"),
    # Upstream ids that arrive as a single unsplittable token.
    ("avglatency", "average latency"),
    # Classic ESXi/Linux NIC counters. These are the grey-state signals for a
    # failing NIC or link, so they are the ones an operator must read at a
    # glance -- "RX lgt err" is not readable.
    ("rxpkts", "RX packets"), ("txpkts", "TX packets"),
    ("rxdrops", "RX drops"), ("txdrops", "TX drops"),
    ("drp", "dropped"), ("err", "errors"), ("errs", "errors"),
    ("frm", "frame alignment"), ("lgt", "length"),
    ("ov", "overrun"), ("abort", "aborted"), ("car", "carrier"),
    # NB no ("miss", "missed"): "miss" is overwhelmingly cache miss,
    # where "missed" is wrong. rxMissErr is handled in OVERRIDE.
    ("heart", "heartbeat"), ("win", "window"), ("ka", "keepalive"),
    ("mcast", "multicast"), ("ucast", "unicast"),
    ("tput", "throughput"), ("oio", "outstanding IO"),
    ("txn", "transaction"), ("rec", "recovery"), ("resync", "resync"),
    ("rcv", "received"), ("snd", "sent"), ("q", "queue"),
]
# Rendered uppercase.
ACRONYMS = {"tcp", "ip", "ip6", "arp", "ecn", "sack", "rdt", "dom", "lsom",
            "cmmds", "clom", "zdom", "esa", "vsan", "cpu", "io", "iops",
            "vm", "pnic", "vnic", "scsi", "vscsi", "nvme", "ssd", "dp",
            "rx", "tx", "id", "uuid", "db", "ack", "acks",
            "crc", "fifo", "pfc", "nic", "pcpu"}
# Safe to replace inside a longer token. Anything that can occur as a
# substring of a real English word must NOT be listed here.
SUBSTRING_SAFE = [
    ("sbspace", "socket buffer space"), ("oopack", " out-of-order packets"),
    ("dupack", " duplicate ACKs"), ("duppack", " duplicate packets"),
    ("rexmit", " retransmit"), ("ctxq", "context queue"),
    ("qlat", "queue latency"), ("rcv", "received "), ("snd", "sent "),
]

QUALIFIER = {"min": "min", "max": "max", "avg": "average",
             "actual": "actual", "rate": "rate", "total": "total"}
# read/write are qualifiers only in TRAILING position. Leading, they read as
# natural English already ("readCacheHitRate" -> "Read cache hit (rate)"), and
# demoting them to a parenthetical would split the noun they belong to.
TRAILING_ONLY = {"read": "read", "write": "write"}


def _unit_from_name(metric: str):
    """Fallback when HCIBench has no entry for this metric id.

    Conservative on purpose: a wrong unit is worse than none, because
    Operations will render and scale it confidently.
    """
    low = metric.lower()
    if "latency" in low or low.endswith("lat") or "qlat" in low:
        return "TIME.MICROSECONDS"
    if "throughput" in low or low.endswith("bytespersec"):
        return "DATA_RATE.BIBYTE_PER_SECOND"
    if "iops" in low:
        return "MISC.IO_OPERATIONS_PER_SECOND"
    if low.endswith("bytes") or "sbspace" in low or "ctxq" in low:
        return "DATA_SIZE.BYTE"
    if low.endswith("pct") or low.endswith("percent") or low.endswith("util"):
        return "RATIO.PERCENT"
    return None


def split_camel(name: str):
    name = name.replace("_", " ")
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", name)
    return [p for p in parts if p]


def _expand(token: str) -> str:
    low = token.lower()
    if low in ACRONYMS:
        return low.upper()
    for abbr, full in ABBREV:
        if low == abbr:
            return full.strip()
    # Substring pass, for compounds like rcvoopack / sndrexmitpack.
    # Only abbreviations that cannot appear inside a longer real word:
    # "lat" is excluded because it sits inside "latency" and produced
    # "Latencyency".
    out = low
    for abbr, full in SUBSTRING_SAFE:
        if abbr in out:
            out = out.replace(abbr, full)
    return " ".join(w.upper() if w in ACRONYMS else w for w in out.split())


# Metrics whose meaning the token rules cannot reach. Keep this small: every
# entry is a hand-maintained claim that has to stay true.
# These outrank even the official schema name, so keep the list short and the
# reason explicit: each one adds meaning the official name leaves out.
OVERRIDE = {
    # Official name is "pNIC RX Missed Error", which does not say what was
    # missed. The NIC ring buffer had no free descriptor, so the packet was
    # dropped before the driver ever saw it -- distinct from rxDrp (dropped
    # higher up) and rxErr (arrived damaged), and the single most useful
    # counter for "is this NIC being overrun".
    "rxMissErr": "pNIC RX missed error (ring buffer full)",
}
OVERRIDE.update({f"{k}Actual": f"{v} (actual)" for k, v in list(OVERRIDE.items())})
OVERRIDE.update({f"{k}Raw": f"{v} (raw)" for k, v in list(OVERRIDE.items())
                 if not k.endswith("Actual")})


def label_for(metric: str) -> str:
    if metric in OVERRIDE:
        return OVERRIDE[metric]
    parts = split_camel(metric)
    trailing = []
    both = {**QUALIFIER, **TRAILING_ONLY}
    while parts and parts[-1].lower() in both and len(parts) > 1:
        trailing.insert(0, both[parts.pop().lower()])
    # leading qualifiers too: avgLatency, maxLatency
    while parts and parts[0].lower() in QUALIFIER and len(parts) > 1:
        trailing.append(QUALIFIER[parts.pop(0).lower()])
    words = [_expand(p) for p in parts]
    text = " ".join(words).strip()
    text = re.sub(r"\s+", " ", text)
    text = text[:1].upper() + text[1:] if text else metric
    if trailing:
        text = f"{text} ({', '.join(trailing)})"
    return text


def official_names(path="docs/assets/perfsvc_schema.json"):
    """Broadcom's own metric names, harvested from the Performance Service.

    These beat anything derived from the id, and sometimes contradict it:
    `pauseCount` is officially "pNic 802.3x Pause Rate", described as a
    percentage -- so the id says count and the metric is a rate. No token rule
    could ever recover that.

    Only `name` and `description` are taken. The schema's `unit` hangs off the
    graph rather than the metric; see tools/build_metric_reference.py.
    """
    try:
        raw = json.load(open(path))
    except FileNotFoundError:
        return {}
    out = {}
    for metrics in raw.values():
        for mid, d in metrics.items():
            if d.get("name"):
                out.setdefault(mid, d["name"].strip())
    return out


# Metrics whose unit cannot be settled from the name and which the Performance
# Service does not document. A wrong unit is worse than none -- Operations will
# scale and render it confidently -- so these stay dimensionless.
AMBIGUOUS_UNIT = {
    # "average percent time to peak" or "average time to peak, in percent"?
    # HCIBench charts it in microseconds, the id says percent, and nothing
    # upstream adjudicates. It is the only *Pct metric not resolving to a
    # ratio, which is itself the smell.
    "avgPctTimeToPeak",
}


def permille_metrics():
    """Metrics the service reports in per-mille; see perfsvc.PERMILLE."""
    import json
    try:
        sch = json.load(open("docs/assets/perfsvc_schema.json"))
    except FileNotFoundError:
        return set()
    out = set()
    for metrics in sch.values():
        for mid, d in metrics.items():
            if d.get("unit") == "permille":
                out.add(mid)
    return out


def main() -> None:
    hcib = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else {}
    sys.path.insert(0, "app")
    import perfsvc_model as P
    official = official_names()

    metrics = sorted({m for d in P.ENTITIES.values() for m in d["metrics"]})
    permille = permille_metrics()
    labels, units = {}, {}
    stats = collections.Counter()
    for m in metrics:
        # hand-curated > Broadcom's own > derived from the id
        labels[m] = OVERRIDE.get(m) or official.get(m) or label_for(m)
        # The adapter converts these to percent, so say so in the name --
        # otherwise a bare "1" reads as a count when it means 1%.
        if m in permille:
            if "%" not in labels[m]:
                labels[m] = f"{labels[m]} (%)"
            units[m] = "RATIO.PERCENT"
        raw = (hcib.get(m) or {}).get("unit", "")
        # *Actual twins carry the same unit as their base metric
        if not raw and m.endswith("Actual"):
            raw = (hcib.get(m[:-6]) or {}).get("unit", "")
        mapped = UNIT_MAP.get(raw, (None, ""))
        if not mapped[0]:
            mapped = (_unit_from_name(m), "")
        if mapped[0] and m not in AMBIGUOUS_UNIT:
            units[m] = mapped[0]
            stats[raw] += 1
        else:
            stats["(none)" if not raw else raw] += 1

    with open("app/metric_labels.py", "w") as fh:
        fh.write('"""GENERATED -- do not edit by hand.\n\n')
        fh.write("Regenerate:\n")
        fh.write("    python3 tools/build_metric_labels.py /tmp/hcib_labels.json\n\n")
        fh.write("Units are harvested from HCIBench's Grafana dashboards, which\n")
        fh.write("cover the same underlying vSAN stats. Labels are expanded here\n")
        fh.write("because HCIBench's titles are panel-level and shared across\n")
        fh.write('several metrics.\n"""\n\nfrom typing import Dict\n\n')
        fh.write("LABELS: Dict[str, str] = {\n")
        for m in metrics:
            fh.write(f"    {m!r}: {labels[m]!r},\n")
        fh.write("}\n\n# metric -> dotted path under aria.ops.definition.units.Units\n")
        fh.write("UNITS: Dict[str, str] = {\n")
        for m in sorted(units):
            fh.write(f"    {m!r}: {units[m]!r},\n")
        fh.write("}\n")

    print(f"  {len(metrics)} metrics")
    print(f"  official names used: {sum(1 for m in metrics if m in official)}")
    print(f"  units resolved: {len(units)} ({100*len(units)/len(metrics):.0f}%)")
    print(f"  source units: {dict(stats.most_common(8))}")
    print("  wrote app/metric_labels.py")
    for probe in ("txSbSpaceMin", "tcpRxThroughput", "avgLatency", "txQLatAvg",
                  "tcpRcvoopackRate", "txCtxQMax", "tcpSackRexmitsRateActual"):
        if probe in labels:
            print(f"    {probe:26} -> {labels[probe]!r}  unit={units.get(probe,'-')}")


if __name__ == "__main__":
    main()
