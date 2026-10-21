#!/usr/bin/env python3
"""Verify help-panel text contrast by resolving each foreground against the
background it actually sits on.

    python3 tools/check_contrast.py                  # the repo's dashboards
    python3 tools/check_contrast.py some.pak         # a built pak
    python3 tools/check_contrast.py --min 4.5        # set the failing bar

Exits non-zero if any text node falls below the bar, or inherits the page
colour instead of sitting on a background the panel controls.

Why it works this way: counting hex values in the markup and expecting none is
NOT a valid gate. It fails a correct self-contained-card implementation, where
a deliberate background is supposed to be present, and it passes a panel that
sets no colour at all -- which is the exact defect that shipped in 1.4.6.
Contrast is a property of a PAIR, so the check has to walk the tree and pair
each text node with its nearest ancestor background.
"""
import glob
import html.parser
import json
import os
import re
import sys
import zipfile


def luminance(hexstr):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def decl(style, prop):
    """Last value of `prop` in an inline style, if it is a usable hex."""
    found = None
    for part in style.split(";"):
        name, _, val = part.partition(":")
        if name.strip().lower() != prop:
            continue
        m = HEX.search(val)
        if m and len(m.group(0)) in (4, 7):      # #rgb or #rrggbb only
            found = m.group(0)
    return found


class Walker(html.parser.HTMLParser):
    """Track the nearest ancestor background and the current foreground."""

    VOID = {"br", "hr", "img", "input", "meta", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                 # (tag, fg, bg)
        self.nodes = []                 # (text, fg, bg)

    def _cur(self):
        fg = next((f for _t, f, _b in reversed(self.stack) if f), None)
        bg = next((b for _t, _f, b in reversed(self.stack) if b), None)
        return fg, bg

    def handle_starttag(self, tag, attrs):
        style = dict(attrs).get("style", "") or ""
        fg = decl(style, "color")
        bg = decl(style, "background") or decl(style, "background-color")
        if tag not in self.VOID:
            self.stack.append((tag, fg, bg))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            fg, bg = self._cur()
            self.nodes.append((data.strip()[:48], fg, bg))


def panels_from_json(doc, label):
    """Yield every editorData string anywhere in the document.

    The path is dashboards[].widgets[].config.editorData, but hard-coding it
    is how an earlier version of this check reported PASS on zero panels.
    Walk for the key instead, and the caller refuses an empty result.
    """
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "editorData" and isinstance(v, str) and v.strip():
                    yield f"{label}{path}", v
                else:
                    yield from walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from walk(v, f"{path}[{i}]")

    yield from walk(doc, "")


def sources(argv):
    paks = [a for a in argv if a.endswith(".pak") or a.endswith(".zip")]
    if paks:
        for p in paks:
            z = zipfile.ZipFile(p)
            for n in z.namelist():
                if n.endswith(".zip") or n.endswith(".pak"):
                    import io
                    inner = zipfile.ZipFile(io.BytesIO(z.read(n)))
                    for m in inner.namelist():
                        if m.endswith(".json"):
                            try:
                                d = json.loads(inner.read(m))
                            except Exception:
                                continue
                            if isinstance(d, dict):
                                yield from panels_from_json(
                                    d, os.path.basename(m))
                elif n.endswith(".json"):
                    try:
                        d = json.loads(z.read(n))
                    except Exception:
                        continue
                    if isinstance(d, dict):
                        yield from panels_from_json(d, os.path.basename(n))
        return
    for f in sorted(glob.glob("content/dashboards/*/*.json")):
        yield from panels_from_json(json.load(open(f)), os.path.basename(f))


def main():
    bar = 4.5
    if "--min" in sys.argv:
        bar = float(sys.argv[sys.argv.index("--min") + 1])
    total = bad = inherited = 0
    pairs = {}
    panels = 0

    for label, markup in sources(sys.argv[1:]):
        panels += 1
        w = Walker()
        w.feed(markup)
        for text, fg, bg in w.nodes:
            total += 1
            if bg is None:
                inherited += 1
                print(f"  INHERITS PAGE  {label}: {text!r} (fg={fg})")
                continue
            if fg is None:
                inherited += 1
                print(f"  NO FOREGROUND  {label}: {text!r} (bg={bg})")
                continue
            r = contrast(fg, bg)
            pairs.setdefault((fg, bg), [0, r])[0] += 1
            if r < bar:
                bad += 1
                print(f"  BELOW {bar}  {label}: {fg} on {bg} = {r:.2f} "
                      f"-- {text!r}")

    print(f"\n  {panels} panels, {total} text nodes, bar {bar}:1")
    for (fg, bg), (n, r) in sorted(pairs.items(), key=lambda kv: kv[1][1]):
        flag = "  <-- worst" if r == min(v[1] for v in pairs.values()) else ""
        print(f"    {fg} on {bg}  {r:6.2f}:1  x{n}{flag}")
    print(f"\n  inheriting the page colour : {inherited}")
    print(f"  below {bar}:1                 : {bad}")
    if panels == 0:
        print("  no text panels found -- this check proved NOTHING")
        return 2
    ok = inherited == 0 and bad == 0
    print(f"\n  {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
