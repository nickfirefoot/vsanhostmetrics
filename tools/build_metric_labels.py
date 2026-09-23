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
    ("util", "utilisation"), ("cnt", "count"),
    ("vmdisk", "VM disk"), ("stddev", "standard deviation"),
    ("tput", "throughput"), ("oio", "outstanding IO"),
    ("txn", "transaction"), ("rec", "recovery"), ("resync", "resync"),
    ("rcv", "received"), ("snd", "sent"), ("q", "queue"),
]
# Rendered uppercase.
ACRONYMS = {"tcp", "ip", "ip6", "arp", "ecn", "sack", "rdt", "dom", "lsom",
            "cmmds", "clom", "zdom", "esa", "vsan", "cpu", "io", "iops",
            "vm", "pnic", "vnic", "scsi", "vscsi", "nvme", "ssd", "dp",
            "rx", "tx", "id", "uuid", "db", "ack", "acks"}
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


def label_for(metric: str) -> str:
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


def main() -> None:
    hcib = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else {}
    sys.path.insert(0, "app")
    import perfsvc_model as P

    metrics = sorted({m for d in P.ENTITIES.values() for m in d["metrics"]})
    labels, units = {}, {}
    stats = collections.Counter()
    for m in metrics:
        labels[m] = label_for(m)
        raw = (hcib.get(m) or {}).get("unit", "")
        # *Actual twins carry the same unit as their base metric
        if not raw and m.endswith("Actual"):
            raw = (hcib.get(m[:-6]) or {}).get("unit", "")
        mapped = UNIT_MAP.get(raw, (None, ""))
        if not mapped[0]:
            mapped = (_unit_from_name(m), "")
        if mapped[0]:
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
    print(f"  units resolved: {len(units)} ({100*len(units)/len(metrics):.0f}%)")
    print(f"  source units: {dict(stats.most_common(8))}")
    print("  wrote app/metric_labels.py")
    for probe in ("txSbSpaceMin", "tcpRxThroughput", "avgLatency", "txQLatAvg",
                  "tcpRcvoopackRate", "txCtxQMax", "tcpSackRexmitsRateActual"):
        if probe in labels:
            print(f"    {probe:26} -> {labels[probe]!r}  unit={units.get(probe,'-')}")


if __name__ == "__main__":
    main()
