#!/usr/bin/env python3
"""
Build an XLSX catalogue of every metric exposed by an ESXi /vsanmetrics scrape.

Groups metrics by the source "branch" that each HELP string names -- e.g.
'[from /net/nics $getVsanNetworkStats]' -- so the sheet can be filtered one
API branch at a time.

Usage:
    source ~/.mp/bin/activate          # needs openpyxl
    python3 tools/build_metric_catalog.py <scrape.txt> <out.xlsx>

To refresh the scrape (read-only GET, the only host call this project makes):
    curl -sk -H "Authorization: Bearer $TOK" https://<esxi>/vsanmetrics -o scrape.txt

Notes on the source data, both verified against a live ESXi 9.1.1 host:
  * The exposition emits NO '# TYPE' lines, so counter-vs-gauge is INFERRED
    from the '_total' suffix. Treat the Type column as a strong guess.
  * Several families are split into multiple series by a label (io_type being
    the important one). The "Splitting labels" column flags those, because a
    consumer that keys only on host/stack will silently collapse them.
"""
from __future__ import annotations

import os
import re
import sys
from collections import OrderedDict, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import vsanmetrics as vm  # noqa: E402  (for TCP_COUNTERS / ID_LABELS)

HELP_RE = re.compile(r"^#\s*HELP\s+(?P<name>\S+)\s+(?P<desc>.*)$")
SOURCE_RE = re.compile(r"\s*\[from\s+(?P<src>[^\]]+)\]\s*$")
SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)"
)
LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')

# Verified on a live host: these two HELP strings are crossed relative to their
# metric names. The names and the values are mutually consistent; the prose is
# what is wrong. See BUGS-UPSTREAM / REPORT.md.
SWAPPED_HELP = {
    "vmware_esx_tcppkt_sack_send_blocks_total",
    "vmware_esx_tcppkt_sack_rexmits_total",
}


def parse(path: str):
    """-> OrderedDict name -> {desc, branch, samples:[(labels_dict, value)]}"""
    families: "OrderedDict[str, dict]" = OrderedDict()
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        m = HELP_RE.match(line)
        if m:
            name, desc = m.group("name"), m.group("desc").strip()
            branch = ""
            sm = SOURCE_RE.search(desc)
            if sm:
                branch = sm.group("src").strip()
                desc = SOURCE_RE.sub("", desc).strip()
            families.setdefault(
                name, {"desc": desc, "branch": branch, "samples": []}
            )
            continue
        if not line or line.startswith("#"):
            continue
        sm2 = SAMPLE_RE.match(line)
        if not sm2:
            continue
        fam = families.get(sm2.group("name"))
        if fam is None:                      # sample with no HELP line
            fam = families.setdefault(
                sm2.group("name"), {"desc": "", "branch": "", "samples": []}
            )
        try:
            value = float(sm2.group("value"))
        except ValueError:
            continue
        fam["samples"].append((dict(LABEL_RE.findall(sm2.group("labels") or "")), value))
    return families


def analyse(families):
    rows = []
    for name, fam in families.items():
        samples = fam["samples"]
        label_keys, varying = [], []
        if samples:
            for k in samples[0][0]:
                label_keys.append(k)
            for k in label_keys:
                if len({s[0].get(k) for s in samples}) > 1:
                    varying.append(k)

        notes = []
        if varying:
            notes.append(
                f"Split into {len(samples)} series by {', '.join(varying)} -- a "
                f"consumer keying only on host_uuid/stack will collapse these and "
                f"silently keep just one."
            )
        if name in SWAPPED_HELP:
            notes.append(
                "UPSTREAM BUG (verified): this HELP text is swapped with the other "
                "sack_* metric. Trust the metric NAME, not the description."
            )
        if name in vm.TCP_COUNTERS:
            notes.append(f"Beta scope -> Ops metric key '{vm.TCP_COUNTERS[name]}'.")

        rows.append({
            "branch": fam["branch"] or "(none declared)",
            "name": name,
            "desc": fam["desc"],
            "type": "Counter (cumulative)" if name.endswith("_total") else "Gauge",
            "series": len(samples),
            "varying": ", ".join(varying),
            "labels": ", ".join(label_keys),
            "example": samples[0][1] if samples else None,
            "beta": "Yes" if name in vm.TCP_COUNTERS else "",
            "ops_key": vm.TCP_COUNTERS.get(name, ""),
            "notes": "  ".join(notes),
        })
    rows.sort(key=lambda r: (r["branch"], r["name"]))
    return rows


def write_xlsx(rows, families, out_path, scrape_path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HDR_FILL = PatternFill("solid", fgColor="1F3864")
    HDR_FONT = Font(bold=True, color="FFFFFF")
    wrap = Alignment(vertical="top", wrap_text=True)
    top = Alignment(vertical="top")

    wb = Workbook()

    def style_header(ws, widths):
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for c in ws[1]:
            c.fill, c.font = HDR_FILL, HDR_FONT
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"

    # ---- Sheet: About -----------------------------------------------------
    ws = wb.active
    ws.title = "About"
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 112
    about = [
        ("Document", "ESXi /vsanmetrics metric catalogue"),
        ("Generated from", os.path.basename(scrape_path)),
        ("Metric families", len(families)),
        ("API branches", len({r['branch'] for r in rows})),
        ("Total series", sum(r["series"] for r in rows)),
        ("Families split by a label",
         f"{sum(1 for r in rows if r['varying'])} of {len(rows)} "
         f"-- see 'Splitting labels'. This is the dominant shape of this API, "
         f"not an exception."),
        ("Largest fan-out",
         ", ".join(f"{r['name']} ({r['series']} series)"
                   for r in sorted(rows, key=lambda x: -x["series"])[:3])),
        ("", ""),
        ("How to use", "Go to the 'All Metrics' sheet and filter the Branch column to "
                       "walk one API branch at a time. 'By Branch' has the counts."),
        ("", ""),
        ("CAVEAT: no TYPE lines",
         "The exposition emits no '# TYPE' lines at all, so the Type column is "
         "INFERRED from the '_total' suffix. It is a strong guess, not authoritative."),
        ("CAVEAT: split series",
         "Some families are split into several series by a label (io_type rx/tx being "
         "the important case). See the 'Splitting labels' column. A collector that "
         "keys only on host_uuid/stack will silently keep one series and drop the rest."),
        ("CAVEAT: swapped HELP",
         "sack_send_blocks_total and sack_rexmits_total have their HELP strings "
         "crossed. Verified against live counter values; trust the NAMES. Flagged "
         "in the Notes column."),
        ("Cumulative counters",
         "Every '_total' is cumulative since host boot. Rates must be derived by "
         "the consumer from successive scrapes."),
        ("Scope note",
         "Only 9 of these are in the current beta management pack; see the "
         "'Beta Scope' sheet."),
    ]
    for r, (k, v) in enumerate(about, start=1):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v).alignment = wrap

    # ---- Sheet: All Metrics ----------------------------------------------
    ws = wb.create_sheet("All Metrics")
    headers = ["Branch (API source)", "Metric name", "What it is (HELP)", "Type",
               "Series", "Splitting labels", "All labels", "Example value",
               "Beta", "Ops metric key", "Notes / flags"]
    ws.append(headers)
    for r in rows:
        ws.append([r["branch"], r["name"], r["desc"], r["type"], r["series"],
                   r["varying"], r["labels"], r["example"], r["beta"],
                   r["ops_key"], r["notes"]])
    style_header(ws, [40, 52, 66, 20, 8, 16, 46, 18, 7, 22, 74])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap if c.column in (3, 7, 11) else top
    ws.auto_filter.ref = ws.dimensions

    # ---- Sheet: By Branch -------------------------------------------------
    ws = wb.create_sheet("By Branch")
    ws.append(["Branch (API source)", "Metric families", "Total series",
               "In beta scope", "Metric names"])
    by = defaultdict(list)
    for r in rows:
        by[r["branch"]].append(r)
    for branch in sorted(by, key=lambda b: (-len(by[b]), b)):
        items = by[branch]
        ws.append([branch, len(items), sum(i["series"] for i in items),
                   sum(1 for i in items if i["beta"]),
                   ", ".join(i["name"] for i in items)])
    style_header(ws, [46, 16, 14, 14, 100])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap if c.column == 5 else top
    ws.auto_filter.ref = ws.dimensions

    # ---- Sheet: Beta Scope ------------------------------------------------
    ws = wb.create_sheet("Beta Scope")
    ws.append(["Metric name (wire)", "Ops metric key", "What it is", "Series",
               "Splitting labels", "Notes"])
    for r in rows:
        if r["beta"]:
            ws.append([r["name"], r["ops_key"], r["desc"], r["series"],
                       r["varying"], r["notes"]])
    style_header(ws, [46, 24, 62, 8, 16, 80])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap if c.column in (3, 6) else top

    # ---- Sheet: Flags -----------------------------------------------------
    ws = wb.create_sheet("Flags")
    ws.append(["Metric name", "Branch", "Flag"])
    for r in rows:
        if r["notes"] and (r["varying"] or r["name"] in SWAPPED_HELP):
            ws.append([r["name"], r["branch"], r["notes"]])
    style_header(ws, [46, 40, 100])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap if c.column == 3 else top

    wb.save(out_path)


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    scrape, out = sys.argv[1], sys.argv[2]
    families = parse(scrape)
    rows = analyse(families)
    write_xlsx(rows, families, out, scrape)
    print(f"{len(families)} metric families, "
          f"{len({r['branch'] for r in rows})} branches, "
          f"{sum(r['series'] for r in rows)} series -> {out}")


if __name__ == "__main__":
    main()
