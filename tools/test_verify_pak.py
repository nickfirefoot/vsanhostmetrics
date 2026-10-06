#!/usr/bin/env python3
"""Prove verify_pak.py actually catches things, by breaking a pak on purpose.

    python3 tools/test_verify_pak.py build/VsanHostMetrics_1.4.4.pak

Each case mutates a copy of a real pak and asserts the verifier fails. The
important part is the line nobody thinks to write:

    ASSERT THE MUTATION CHANGED THE FILE BEFORE TRUSTING THE RESULT.

netstats hit this while testing for the same defect class. Their first attempt
anchored on an exact attribute-order string, matched nothing, mutated nothing,
and the verifier passed -- which reads as "the check is broken" when it means
"the test did nothing". A negative test that cannot prove it perturbed the
artefact is not evidence of anything.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile


def rebuild(src: str, dst: str, mutate) -> bool:
    """Copy the pak through `mutate`. Returns True if anything actually changed."""
    changed = False
    zin = zipfile.ZipFile(src)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            new = mutate(item.filename, data)
            if new is not None and new != data:
                changed = True
                data = new
            zout.writestr(item, data)
    return changed


def run(pak: str) -> int:
    r = subprocess.run([sys.executable, "tools/verify_pak.py", pak],
                       capture_output=True, text=True)
    return r.returncode


def unbind_a_widget(name, data):
    if "/dashboards/" in name and name.endswith(".json"):
        doc = json.loads(data)
        for w in doc["dashboards"][0]["widgets"]:
            if w["type"] == "View" and w["config"].get("viewDefinitionId"):
                del w["config"]["viewDefinitionId"]
                return json.dumps(doc, indent=1).encode()
    return None


def plant_a_hostname(name, data):
    if "/reports/" in name and name.endswith(".xml"):
        return data.replace(b"<Description />", b"<Description>esxi01.denick.lab</Description>", 1)
    return None


def unshare_a_dashboard(name, data):
    if "/dashboards/" in name and name.endswith(".json"):
        doc = json.loads(data)
        doc["dashboards"][0]["shared"] = False
        return json.dumps(doc, indent=1).encode()
    return None


def overlap_two_widgets(name, data):
    if "/dashboards/" in name and name.endswith(".json"):
        doc = json.loads(data)
        ws = [w for w in doc["dashboards"][0]["widgets"] if w.get("gridsterCoords")]
        if len(ws) >= 2:
            ws[1]["gridsterCoords"] = dict(ws[0]["gridsterCoords"])
            return json.dumps(doc, indent=1).encode()
    return None


CASES = [
    ("a widget loses its view binding", unbind_a_widget),
    ("a lab hostname is planted in a view", plant_a_hostname),
    ("a dashboard is left unshared", unshare_a_dashboard),
    ("two widgets are made to overlap", overlap_two_widgets),
]


def main() -> int:
    src = sys.argv[1]
    baseline = run(src)
    print("unmutated pak -> exit %d  %s" % (baseline, "(expected 0)" if baseline == 0 else "*** BASELINE ALREADY FAILS ***"))
    if baseline != 0:
        return 1
    bad = 0
    tmp = tempfile.mkdtemp()
    for label, fn in CASES:
        dst = f"{tmp}/mutated.pak"
        changed = rebuild(src, dst, fn)
        if not changed:
            print("   %-42s MUTATION DID NOTHING -- test proves nothing" % label)
            bad += 1
            continue
        code = run(dst)
        ok = code != 0
        print("   %-42s mutated=yes  verifier exit=%d  %s"
              % (label, code, "caught" if ok else "*** NOT CAUGHT ***"))
        if not ok:
            bad += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("%d of %d defects caught" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
