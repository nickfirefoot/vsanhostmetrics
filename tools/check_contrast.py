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
RGB = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
                 r"(?:\s*,\s*([\d.]+))?\s*\)")
# Only the names our own generators could plausibly emit. Anything else stays
# unresolvable rather than being guessed at.
NAMED = {"white": "#ffffff", "black": "#000000", "red": "#ff0000",
         "silver": "#c0c0c0", "gray": "#808080", "grey": "#808080"}
UNRESOLVABLE = "?"      # a value we refuse to score, which must fail the check


def _hex(value):
    """Resolve one CSS colour value, or UNRESOLVABLE.

    Returns None when the property is simply absent. Earlier this accepted
    only #rgb/#rrggbb, so `color:white` and `background:rgba(...)` read as
    ABSENT -- false positives, safe but wrong. A gradient or multi-stop value
    is deliberately UNRESOLVABLE rather than "the first hex found": taking the
    first stop let `linear-gradient(#2b3137,#ffffff)` score as a dark card.
    """
    v = value.strip().lower()
    if not v or v in ("none", "transparent", "inherit", "initial", "unset"):
        return None
    if "gradient" in v or "var(" in v or "image" in v:
        return UNRESOLVABLE
    hexes = [h for h in HEX.findall(v) if len(h) in (4, 7)]
    rgbs = RGB.findall(v)
    names = [n for n in NAMED if re.search(rf"\b{n}\b", v)]
    found = []
    for h in hexes:
        found.append("#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h)
    for r, g, b, a in rgbs:
        if a and float(a) < 1:              # translucent: what is behind it
            return UNRESOLVABLE             # decides the result, so refuse
        found.append("#%02x%02x%02x" % (int(r), int(g), int(b)))
    found += [NAMED[n] for n in names]
    if not found:
        # A value is present but nothing recognisable -- never treat that as
        # absent, which would silently credit an ancestor instead.
        return UNRESOLVABLE
    return found[0] if len(set(found)) == 1 else UNRESOLVABLE


def decl(style, prop):
    """Last declaration of `prop` in an inline style, resolved."""
    found = None
    for part in style.split(";"):
        name, _, val = part.partition(":")
        if name.strip().lower() == prop:
            found = _hex(val)
    return found


def opacity(style):
    """Opacity declared on this element, or 1.0."""
    for part in style.split(";"):
        name, _, val = part.partition(":")
        if name.strip().lower() == "opacity":
            try:
                return float(val.strip())
            except ValueError:
                return 0.0                  # unparseable: treat as muted
    return 1.0


class Walker(html.parser.HTMLParser):
    """Track the nearest ancestor background and the current foreground."""

    VOID = {"br", "hr", "img", "input", "meta", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                 # (tag, fg, bg)
        self.nodes = []                 # (text, fg, bg)
        self.root_bg = None             # background of the OUTERMOST element
        self._seen_root = False
        self.opacities = []             # declared opacity, innermost last

    def _cur(self):
        fg = next((f for _t, f, _b in reversed(self.stack) if f), None)
        bg = next((b for _t, _f, b in reversed(self.stack) if b), None)
        return fg, bg

    def handle_starttag(self, tag, attrs):
        style = dict(attrs).get("style", "") or ""
        fg = decl(style, "color")
        bg = decl(style, "background") or decl(style, "background-color")
        op = opacity(style)
        if tag not in self.VOID:
            self.opacities.append((tag, op))
            if not self._seen_root:
                # The outermost element is what sits against the theme. A peer
                # pack found that crediting ANY ancestor background lets a
                # panel with no card pass, because an inner code-span fill
                # scores fine on its own -- while the wrapper, and so the
                # padding and gaps, still show the theme colour.
                self.root_bg = bg
                self._seen_root = True
            self.stack.append((tag, fg, bg))

    def handle_endtag(self, tag):
        for i in range(len(self.opacities) - 1, -1, -1):
            if self.opacities[i][0] == tag:
                del self.opacities[i:]
                break
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            fg, bg = self._cur()
            # Whether the element DIRECTLY holding this text declares its own
            # colour, or is leaning on an inheritance hop. Valid CSS either
            # way, but this editor has broken that hop before -- it is why
            # rc.3 shipped unreadable -- so our own output must not rely on it.
            own = bool(self.stack and self.stack[-1][1])
            # Opacity multiplies down the tree, so a muted ancestor mutes this
            # text however solid its own colour is. A peer pack tests this mode
            # and this checker passed it until they asked.
            eff = 1.0
            for _t, o in self.opacities:
                eff *= o
            self.nodes.append((data.strip()[:48], fg, bg, own, eff))


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
    # content/dashboards/ ONLY -- this is what build_pak ships. Never point
    # this at dist/, which is gitignored and still holds six probe dashboards
    # the builder stopped producing, plus paks back to 1.1.9. A peer pack's
    # first audit reported faults in exactly such stale artefacts.
    for f in sorted(glob.glob("content/dashboards/*/*.json")):
        yield from panels_from_json(json.load(open(f)), os.path.basename(f))


def main():
    bar = 4.5
    if "--min" in sys.argv:
        bar = float(sys.argv[sys.argv.index("--min") + 1])
    total = bad = inherited = rootless = leaning = 0
    muted = unresolved = 0
    pairs = {}
    panels = 0

    for label, markup in sources(sys.argv[1:]):
        panels += 1
        w = Walker()
        w.feed(markup)
        if not w.root_bg or w.root_bg == UNRESOLVABLE:
            rootless += 1
            print(f"  NO CARD        {label}: outermost element declares no "
                  f"background; the wrapper sits on the theme colour")
        for text, fg, bg, own, eff in w.nodes:
            total += 1
            if eff < 0.999:
                muted += 1
                print(f"  OPACITY {eff:.2f}  {label}: {text!r} -- muted text "
                      f"does not deliver its nominal contrast")
                continue
            if fg == UNRESOLVABLE or bg == UNRESOLVABLE:
                unresolved += 1
                print(f"  UNRESOLVABLE   {label}: {text!r} fg={fg} bg={bg} -- "
                      f"gradient, translucency or an unrecognised colour")
                continue
            if bg is None:
                inherited += 1
                print(f"  INHERITS PAGE  {label}: {text!r} (fg={fg})")
                continue
            if fg is None:
                inherited += 1
                print(f"  NO FOREGROUND  {label}: {text!r} (bg={bg})")
                continue
            if not own:
                leaning += 1
                print(f"  INHERITS PARENT {label}: {text!r} -- the tag holding "
                      f"this text sets no colour of its own")
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
    print(f"\n  panels with no card background : {rootless}")
    print(f"  inheriting the page colour : {inherited}")
    print(f"  leaning on a parent colour : {leaning}")
    print(f"  muted by opacity           : {muted}")
    print(f"  unresolvable colour values : {unresolved}")
    print(f"  below {bar}:1                 : {bad}")
    if panels == 0:
        print("  no text panels found -- this check proved NOTHING")
        return 2
    ok = (inherited == 0 and bad == 0 and rootless == 0
          and leaning == 0 and muted == 0 and unresolved == 0)
    print(f"\n  {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
