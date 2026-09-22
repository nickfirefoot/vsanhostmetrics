#!/usr/bin/env python3
"""Classify each metric as counter or gauge, with the evidence recorded.

The exposition carries no `# TYPE` lines (BUGS-UPSTREAM.md item 2), so the
distinction has to be inferred.  It matters: a rate computed from a gauge is
meaningless but looks plausible on a dashboard, whereas a counter shown raw is
an obvious since-boot ramp.  So the default when evidence is weak is GAUGE --
wrong in a visible way rather than an invisible one.

Evidence, strongest first:
  1. observed to DECREASE across samples  -> gauge, definitive
  2. name ends in `_total`                -> counter (no observed contradiction)
  3. HELP text wording                    -> counter or gauge
  4. nothing                              -> gauge, low confidence, backlog it

Usage:
    python3 tools/classify_metrics.py <exposition.txt> [observed.json]
"""
from __future__ import annotations
import re, sys, json, collections

GAUGE_WORDS = re.compile(
    r"point in time|latency|ratio|usage|utilization|utilisation|limit|"
    r"current|percent|level|size|capacity|free|available|outstanding|depth|"
    r"queue|temperature|congestion", re.I)
COUNTER_WORDS = re.compile(
    r"^\s*(number of|total|the count of|count of|cumulative|sum total)", re.I)


def classify(name: str, help_text: str, observed: str | None):
    if observed == "gauge":
        return "gauge", "observed-decrease", "high"
    if name.endswith("_total"):
        return "counter", "name-suffix", "high"
    h = (help_text or "").strip()
    if h.lower().startswith("point in time"):
        return "gauge", "help-point-in-time", "high"
    if COUNTER_WORDS.search(h):
        # "Number of ... latency" style wording exists; gauge words win.
        if GAUGE_WORDS.search(h) and not re.search(r"^\s*(number of|total)\s+\w*\s*(io|packet|byte|update|batch|request|message|hit|miss)", h, re.I):
            return "gauge", "help-gauge-words", "medium"
        return "counter", "help-counter-words", "medium"
    if GAUGE_WORDS.search(h) or GAUGE_WORDS.search(name):
        return "gauge", "help-or-name-gauge-words", "medium"
    if observed == "counter?":
        return "counter", "observed-monotonic", "medium"
    return "gauge", "default-safe", "low"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    helps, names = {}, set()
    for line in open(sys.argv[1]):
        if line.startswith("# HELP "):
            k, _, v = line[7:].strip().partition(" ")
            helps[k] = v
            continue
        if not line.strip() or line[0] == "#":
            continue
        m = re.match(r"([a-zA-Z_:][a-zA-Z0-9_:]*)", line)
        if m:
            names.add(m.group(1))
    observed = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}

    out, tally = {}, collections.Counter()
    for n in sorted(names):
        kind, why, conf = classify(n, helps.get(n, ""), observed.get(n))
        out[n] = {"kind": kind, "evidence": why, "confidence": conf}
        tally[(kind, conf)] += 1

    for (kind, conf), c in sorted(tally.items()):
        print(f"  {kind:8} {conf:7} {c:>4}")
    print(f"\n  total {len(out)}")
    low = [n for n, d in out.items() if d["confidence"] == "low"]
    print(f"  low confidence: {len(low)}  <- review these first")
    for n in low[:12]:
        print(f"     {n:54} {helps.get(n,'(no HELP)')[:48]}")
    if len(low) > 12:
        print(f"     ... {len(low)-12} more")
    json.dump(out, open("docs/metric-kinds.json", "w"), indent=1, sort_keys=True)
    print("\n  wrote docs/metric-kinds.json")


if __name__ == "__main__":
    main()
