#!/usr/bin/env python3
"""Verify a built pak, and fail if a check examined nothing.

    python3 tools/verify_pak.py build/VsanHostMetrics_1.4.4.pak

Every check here has been run ad hoc at some point in this project. Collecting
them matters less than the rule they now share:

    A CHECK THAT EXAMINED ZERO THINGS IS A FAILURE, NOT A PASS.

That rule exists because of a real defect. The schema comparison deciding
"install over the top" versus "uninstall first" matched `<ResourceKind key="`,
assuming `key` was the first attribute. It is not -- these elements lead with
`default` -- so the identifier comparison matched **zero of 90** and compared
two empty sets. It reported agreement for months, on the one dimension that
actually forces an uninstall. It was right the whole time by luck.

The netstats pack audited itself for the same class after hearing about it and
found nine loops with the same exposure. So each check below reports the number
of things it looked at, those counts are asserted non-zero, and the totals are
printed on every run. A silent pass is no longer possible.

Two further rules learned the same way:

  * Compare the identifier's **key and identType together**. identType 1 means
    part of uniqueness, 2 means informational. Demoting 1 to 2 leaves the field
    in the schema and silently re-keys every object, so a name-only comparison
    reports no change.
  * If you write a negative test, assert that the mutation actually perturbed
    the artefact before trusting the result. netstats' first attempt to prove
    this check worked changed nothing, and the pass read as "the check is
    broken" when it meant "the test did nothing".
"""
from __future__ import annotations

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

LEAK_PATTERNS = ["denick.lab", "10.10.0.", "VMware23", "claude@vsphere",
                 "esxi0", "ghp_", "github_pat", "Ext.vcops"]


class Checker:
    def __init__(self) -> None:
        self.examined: dict[str, int] = {}
        self.failures: list[str] = []

    def saw(self, what: str, n: int) -> int:
        self.examined[what] = self.examined.get(what, 0) + n
        return n

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    def report(self) -> int:
        print("examined: " + ", ".join(f"{n} {k}" for k, n in sorted(self.examined.items())))
        # the rule this file exists for
        for what, n in sorted(self.examined.items()):
            if n == 0:
                self.fail(f"check for {what!r} examined NOTHING -- vacuous pass")
        if self.failures:
            print()
            for f in self.failures:
                print("FAIL  " + f)
            return 1
        print("all checks passed, and every one of them examined something")
        return 0


def verify(path: str) -> int:
    c = Checker()
    z = zipfile.ZipFile(path)
    manifest = json.loads(z.read("manifest.txt"))
    describe = zipfile.ZipFile(io.BytesIO(z.read("adapter.zip"))).read(
        "VsanHostMetrics/conf/describe.xml").decode("utf-8", "replace")

    def keys(tag: str) -> set[str]:
        # NOT anchored on key being the first attribute. See the module note.
        return set(re.findall(rf'<{tag}\b[^>]*?\bkey="([^"]+)"', describe))

    kinds = keys("ResourceKind")
    attrs = keys("ResourceAttribute")
    c.saw("kinds", len(kinds))
    c.saw("attributes", len(attrs))

    idents = re.findall(
        r'<ResourceIdentifier\b[^>]*?\bkey="([^"]+)"[^>]*?identType="(\d)"', describe)
    c.saw("identifiers", len(idents))
    for key, itype in idents:
        if itype not in ("1", "2"):
            c.fail(f"identifier {key!r} has unknown identType {itype!r}")

    # views
    view_files = [n for n in z.namelist() if "/reports/" in n and n.endswith(".xml")]
    c.saw("views", len(view_files))
    defined: dict[str, str] = {}
    columns = 0
    for n in view_files:
        root = ET.fromstring(z.read(n))
        vd = root.find(".//ViewDef")
        if vd is None:
            c.fail(f"{n}: no ViewDef")
            continue
        defined[vd.get("id")] = vd.findtext("Title") or "?"
        cols = [p for p in root.iter("Property") if p.get("name") == "attributeKey"]
        if not cols:
            c.fail(f"{vd.findtext('Title')!r}: view has no columns")
        columns += len(cols)
    c.saw("view_columns", columns)

    # dashboards
    dash_files = [n for n in z.namelist() if "/dashboards/" in n and n.endswith(".json")]
    c.saw("dashboards", len(dash_files))
    referenced: set[str] = set()
    bindings = 0
    for n in dash_files:
        doc = json.loads(z.read(n))
        db = doc["dashboards"][0]
        boxes = []
        for w in db["widgets"]:
            cfg = w.get("config") or {}
            vid = cfg.get("viewDefinitionId")
            if w["type"] == "View":
                bindings += 1
                if not vid:
                    c.fail(f"{db['name']}: widget {cfg.get('title')!r} has no view bound")
                else:
                    referenced.add(vid)
            if w.get("gridsterCoords"):
                boxes.append((cfg.get("title") or w["type"], w["gridsterCoords"]))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (ta, a), (tb, b) = boxes[i], boxes[j]
                if (a["x"] <= b["x"] + b["w"] - 1 and b["x"] <= a["x"] + a["w"] - 1
                        and a["y"] <= b["y"] + b["h"] - 1
                        and b["y"] <= a["y"] + a["h"] - 1):
                    c.fail(f"{db['name']}: {ta!r} overlaps {tb!r}")
        if not db.get("shared"):
            c.fail(f"{db['name']}: shared is false, visible only to its recorded owner")
    c.saw("bindings", bindings)

    for vid in referenced - set(defined):
        c.fail(f"dashboard references view {vid} that the pak does not define")
    for vid in set(defined) - referenced:
        c.fail(f"view {defined[vid]!r} is shipped but no dashboard uses it")

    # leak scan
    entries = [n for n in z.namelist() if not n.endswith("/")]
    c.saw("pak_entries", len(entries))
    c.saw("leak_patterns", len(LEAK_PATTERNS))
    for n in entries:
        try:
            body = z.read(n).decode("utf-8", "ignore")
        except Exception:                                # noqa: BLE001
            continue
        for pat in LEAK_PATTERNS:
            if pat in body:
                c.fail(f"{n}: contains {pat!r}")

    print(f"{path}  version {manifest['version']}  pak name {manifest['name']}")
    return c.report()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: verify_pak.py <pak>")
    sys.exit(verify(sys.argv[1]))
