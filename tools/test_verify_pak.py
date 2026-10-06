#!/usr/bin/env python3
"""Prove verify_pak.py catches things, by breaking a real pak on purpose.

    python3 tools/test_verify_pak.py build/VsanHostMetrics_1.4.4.pak

The rule this file exists for, from the netstats pack:

    ASSERT THE MUTATION ACTUALLY LANDED BEFORE TRUSTING THE RESULT.

A negative test that cannot prove it perturbed the artefact is not evidence. A
passing verifier and a test that did nothing look identical.

And the refinement, which cost two more attempts between us: **byte inequality
of the container is not proof.** Rebuilding `adapter.zip` to edit the
`describe.xml` inside it changes the outer bytes whether or not the edit
matched, so `new != old` reported success for a mutation that did nothing. Where
a case can state what it meant to change, it supplies a `confirm` that reads the
rebuilt pak and checks for THAT, not for movement.

netstats reached the same place by a different route: their assertion compared
lengths, which silently excused every same-length mutation -- one UUID for
another, identType 1 for 2. Both of our wrong versions produced reassuring
output, which is the dangerous property.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def rebuild(src: str, dst: str, mutate) -> bool:
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
    return subprocess.run([sys.executable, "tools/verify_pak.py", pak],
                          capture_output=True, text=True).returncode


def describe_of(pak: str) -> str:
    z = zipfile.ZipFile(pak)
    return zipfile.ZipFile(io.BytesIO(z.read("adapter.zip"))).read(
        "VsanHostMetrics/conf/describe.xml").decode("utf-8", "replace")


# ---- mutations -----------------------------------------------------------
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
        return data.replace(b"<Description />",
                            b"<Description>esxi01.denick.lab</Description>", 1)
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


def demote_an_object_identifier(name, data):
    """SAME LENGTH: identType 1 -> 2 on a real object identifier."""
    if not name.endswith("adapter.zip"):
        return None
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            b = zin.read(it.filename)
            if it.filename.endswith("describe.xml"):
                txt = b.decode("utf-8", "replace")
                km = re.search(
                    r'<ResourceKind\b[^>]*?\bkey="VsanPnic"[^>]*>.*?</ResourceKind>',
                    txt, re.S)
                if km:
                    block = re.sub(
                        r'(<ResourceIdentifier\b[^>]*?\bkey="vmnic"[^>]*?identType=")1(")',
                        r"\g<1>2\g<2>", km.group(0), count=1)
                    txt = txt[:km.start()] + block + txt[km.end():]
                    b = txt.encode()
            zo.writestr(it, b)
    return out.getvalue()


def swap_the_owner_uuid(name, data):
    """SAME LENGTH: one owner uuid for another."""
    if "/dashboards/" in name and name.endswith(".json"):
        return data.replace(b"833b693b-0960-4d05-b868-f14446488fc3",
                            b"deadbeef-0000-4000-8000-000000000000")
    return None


# ---- confirmations: did the edit actually land? --------------------------
def confirm_identifier_demoted(pak):
    km = re.search(r'<ResourceKind\b[^>]*?\bkey="VsanPnic"[^>]*>.*?</ResourceKind>',
                   describe_of(pak), re.S)
    if not km:
        return False
    im = re.search(r'<ResourceIdentifier\b[^>]*?\bkey="vmnic"[^>]*?identType="(\d)"',
                   km.group(0))
    return bool(im) and im.group(1) == "2"


def confirm_owner_swapped(pak):
    z = zipfile.ZipFile(pak)
    body = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                   if "/dashboards/" in n and n.endswith(".json"))
    return "deadbeef-0000-4000-8000-000000000000" in body


CASES = [
    ("a widget loses its view binding", unbind_a_widget, None),
    ("a lab hostname is planted in a view", plant_a_hostname, None),
    ("a dashboard is left unshared", unshare_a_dashboard, None),
    ("two widgets are made to overlap", overlap_two_widgets, None),
    ("an object identifier is demoted [same length]", demote_an_object_identifier,
     confirm_identifier_demoted),
    ("the dashboard owner uuid is swapped [same length]", swap_the_owner_uuid,
     confirm_owner_swapped),
]


def main() -> int:
    src = sys.argv[1]
    baseline = run(src)
    print("unmutated pak -> exit %d %s"
          % (baseline, "(expected 0)" if baseline == 0 else "*** BASELINE FAILS ***"))
    if baseline != 0:
        return 1
    bad = 0
    tmp = tempfile.mkdtemp()
    for label, fn, confirm in CASES:
        dst = f"{tmp}/mutated.pak"
        landed = rebuild(src, dst, fn)
        if confirm is not None:
            landed = confirm(dst)          # container bytes moving proves nothing
        if not landed:
            print("   %-50s MUTATION DID NOT LAND -- proves nothing" % label)
            bad += 1
            continue
        code = run(dst)
        print("   %-50s landed  exit=%d  %s"
              % (label, code, "caught" if code else "*** NOT CAUGHT ***"))
        if code == 0:
            bad += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d of %d defects caught" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
