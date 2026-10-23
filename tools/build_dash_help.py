#!/usr/bin/env python3
"""Generate each dashboard's help panel from the views that dashboard shows.

    python3 tools/build_dash_help.py       # writes ~/ops-content/out/help/

Replaces five hand-written HTML files. Those were written before the views
were refined and had drifted badly: the Network panel documented every column
in detail at 19 KB while DOM and Resync were 2 KB summaries that named
metrics no longer on the screen. Generating from `build_view.VIEWS` and
`build_help_html.NOTES` means a column cannot appear on a dashboard without
its explanation appearing beneath it, and cannot be removed and leave the
explanation behind.

Two constraints learned the hard way and encoded here:

  * The rich-text editor **discards `<style>` blocks** but keeps inline
    `style=` attributes, so every rule is written inline on every element.
  * The panel must supply its own background as well as its own colour.
    Operations' theme is an application setting, the TextDisplay widget
    hands down no usable foreground, and no single foreground clears 4.5:1
    on both a white and a dark dashboard -- see CARD_BG below for the
    arithmetic. Setting both ends is the only thing correct in both themes.
"""
import html
import re
import os
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                        # noqa: E402
import build_dash                                        # noqa: E402
import build_help_html                                   # noqa: E402

OUT = os.path.expanduser("~/ops-content/out/help")
NOTES = build_help_html.NOTES

# THE PANEL CARRIES ITS OWN BACKGROUND. Two earlier attempts both shipped
# broken, for opposite reasons, and the fix is to stop depending on the theme.
#
#   v1  color:#ffffff on every element -> invisible on a light dashboard.
#   v2  no colour at all, inherit      -> the TextDisplay widget does not hand
#                                         down a usable foreground, so the text
#                                         fell back to black on a dark theme.
#
# Inheriting cannot work here and no single foreground can either. Operations'
# theme is an application setting, so `prefers-color-scheme` does not track it,
# and 4.5:1 against both a white and a dark dashboard is arithmetically
# impossible -- a foreground needs relative luminance <= 0.1833 to clear 4.5:1
# on #ffffff and >= 0.2243 to clear it on #1b1b1b. Those ranges do not overlap.
# The best any fixed colour can do, balanced across both, is 4.15:1, and across
# the three backgrounds Operations actually uses (#ffffff, #1b1b1b, #2a3038)
# the best neutral grey is #848484 at 4.17 / 4.13 / 3.19 -- failing on dark.
#
# So the panel sets BOTH ends and the contrast stops being the theme's to
# decide: #e9edf0 on #2b3137 is 11.17:1, identical in every theme. The card
# reads as a deliberate callout on a light dashboard (13.15:1 against the page)
# and merges into a dark one (1.01-1.31:1), which is the right behaviour both
# ways round. Every colour below is measured against CARD_BG, not against a
# guess about the page.
CARD_BG = "#2b3137"
FG      = "#e9edf0"                  # 11.17:1 on CARD_BG
ACCENT  = "#8fd3ff"                  #  8.10:1 on CARD_BG
RULE    = "rgba(255,255,255,0.18)"   # safe now that what is behind it is known
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
WRAP = (f"font-family:'Metropolis','Segoe UI',sans-serif;font-size:13px;"
        f"padding:12px 14px;background:{CARD_BG};color:{FG};"
        f"border:1px solid {RULE};border-radius:6px")
H2 = f"font-size:15px;font-weight:700;margin:2px 0 10px 0;color:{FG}"
H3 = (f"font-size:13px;font-weight:700;margin:16px 0 6px 0;color:{FG};"
      f"border-bottom:1px solid {RULE};padding-bottom:3px")
P = f"margin:5px 0;line-height:1.45;color:{FG}"
# Metric names get the accent AND the monospace face. Colour alone is never the
# only signal, so the distinction survives if a renderer drops one of them.
NAME = f"font-weight:600;font-family:{MONO};color:{ACCENT}"
BOLD = f"font-weight:700;color:{FG}"
# Inline tags the NOTES and INTRO prose may use. Every one gets an explicit
# colour: <code> and <i> previously shipped bare and relied on inheriting from
# the enclosing <p>, which is valid CSS but is exactly the hop this editor has
# broken before. A peer pack hit the matching bug from the other side -- its
# applier matched only BARE tags, so a fragment that already carried a style
# attribute came out with no colour at all.
INLINE = {
    "b": BOLD,
    "strong": BOLD,
    "i": f"font-style:italic;color:{FG}",
    "em": f"font-style:italic;color:{FG}",
    "code": f"font-family:{MONO};font-size:12px;color:{ACCENT}",
}


def style_inline(markup):
    """Give every inline tag an explicit colour; refuse to guess at the rest.

    Raises on a tag that is not in INLINE, and on one that already carries
    attributes, rather than emitting it bare. Silently passing those through is
    how <code> and <i> reached a shipped pak with no colour of their own.
    """
    def sub(m):
        tag, attrs = m.group(1).lower(), m.group(2).strip()
        if tag not in INLINE:
            raise SystemExit(
                f"build_dash_help: inline tag <{tag}> has no style in INLINE; "
                f"add one rather than shipping it uncoloured")
        if attrs:
            raise SystemExit(
                f"build_dash_help: <{tag} {attrs}> already carries attributes; "
                f"prepend the style instead of substituting the tag")
        return f'<{tag} style="{INLINE[tag]}">'

    return re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)((?:\s[^>]*)?)>", lambda m: (
        m.group(0) if m.group(1).lower() not in INLINE
        and not m.group(0).startswith(tuple(f"<{t}" for t in INLINE))
        else sub(m)), markup)

# The narrative each screen needs and no metric list can supply: what question
# the screen answers, and what "normal" looks like on it.
INTRO = {'Rapid vSAN Overview': [('vSAN overview &mdash; which layer should you look at first?',
                          ['Each table below shows one layer of the vSAN IO path: the front end that virtual '
                           'machines see, the owner that coordinates writes, the back end that talks to the '
                           'disks, and the RDT transport between hosts. Use it to choose a layer, then open '
                           'the matching detail screen.',
                           'The same measures are reported at each layer, so a latency or congestion figure '
                           'can be compared from one layer to the next. Capacity is shown for the cluster, '
                           "and <b>Host health and load</b> is vCenter's view of each host, included for "
                           'context.',
                           "The owner is the host that coordinates a given object's writes across its "
                           'replicas, and it can be a different host from the one a virtual machine runs '
                           'on.'])],
 'Rapid vSAN Network': [('vSAN network &mdash; how is each layer of the network path behaving?',
                         ['vSAN traffic crosses four layers, and each has a panel here from the top down: '
                          "<b>RDT</b>, vSAN's own transport; <b>TCP</b>; the VMkernel network adapter "
                          '(<b>vmknic</b>); and the <b>physical NIC</b>. Two further panels show every '
                          'uplink as vCenter counts it, and cluster membership (CMMDS) traffic.',
                          'Most columns show the highest value in the selected period, so a short burst '
                          'inside a five-minute interval is not averaged away. Columns that behave '
                          'differently, such as minimums, current values and cumulative counts, are '
                          'described in the reference below.',
                          "<b>High pNIC error rate</b> shows the eight counters behind vCenter's built-in "
                          'alarm <i>High pNic error rate detected</i> (alarm-261): <code>rxCrcErr</code>, '
                          '<code>rxErr</code>, <code>rxFifoErr</code>, <code>rxMissErr</code>, '
                          '<code>rxOvErr</code>, <code>txCarErr</code>, <code>txErr</code> and '
                          '<code>pauseCount</code>, with the cumulative <code>rxMissErrRaw</code>. The alarm '
                          'is raised when the vSAN health test for any of those counters reports yellow or '
                          'red. <b>pNIC stats - every counter</b> shows the full set of pNIC columns.',
                          'The pNIC panels list the uplinks the vSAN Performance Service reports on. '
                          '<b>Every uplink - from vCenter</b> shows all uplinks on each host, counted by '
                          'vCenter.'])],
 'Rapid vSAN Storage': [('vSAN storage &mdash; how is each layer of storage performing?',
                         ['This screen follows storage from the vSAN view of each ESA disk, to the physical '
                          'device beneath it, to the back end on each host, and then to what virtual '
                          'machines see: per vSCSI controller and per virtual machine. Cluster capacity is '
                          'shown as well.',
                          'Each drive appears in two panels, at the vSAN layer and at the physical device '
                          'layer, so their latency columns can be read side by side. The physical layer '
                          "panel also lists each drive's model, firmware revision, controller driver and "
                          'driver version. These come from vCenter and are properties rather than metrics, '
                          'so they show the current value only.',
                          'For the latency graphs where the vSAN Performance Service defines thresholds '
                          '(disk device latency, vSCSI latency and virtual machine latency), it uses 15 ms '
                          'as the warning level and 30 ms as the critical level.'])],
 'Rapid vSAN DOM': [('DOM &mdash; how is each layer of a vSAN write performing?',
                     ['DOM is the distributed object manager, and it has three layers. The <b>client</b> is '
                      'the host a guest is running on. The <b>owner</b> is the host that coordinates a given '
                      "object's writes, which may be a different host entirely. The <b>component manager</b> "
                      'is what talks to the disks.',
                      'The same measures are reported at each layer. This screen shows the owner and the '
                      'component manager at cluster level, and the client, the owner and the component '
                      'manager for each host. The cluster-level client table is on the Overview and '
                      'Backpressure screens.'])],
 'Rapid vSAN Backpressure': [('Backpressure &mdash; which layer is reporting congestion?',
                              ["Congestion is vSAN's mechanism for slowing IO when a layer cannot absorb the "
                               'load offered to it. It is reported separately by the client, the owner and '
                               'the component manager, and by type.',
                               'The panels run from the whole cluster to individual hosts. <b>Cluster - '
                               'front end congestion</b> and <b>Cluster - owner congestion</b> are cluster '
                               'level. <b>Back end - device vs host</b> and <b>Owner - reclaim and '
                               'rebuild</b> are per host. <b>Adaptive network shaping</b> shows the network '
                               "scheduler's counters per host. The two transport panels show RDT for the "
                               'cluster and per host.',
                               'Client congestion is reported as <code>congestion</code>, '
                               '<code>readCongestion</code>, <code>writeCongestion</code> and '
                               '<code>unmapCongestion</code>. The owner reports '
                               '<code>segCleanerUnmapCongestion</code> and '
                               '<code>recoveryWriteCongestion</code>. The component manager reports '
                               '<code>componentCongestion</code>, <code>sharedCongestion</code> and '
                               '<code>resyncReadCongestion</code>.',
                               'The transport panels show RDT latency alongside <code>kaReset</code>, '
                               '<code>txSbSpaceMin</code> and <code>rxSbSpaceMin</code>.'])],
 'Rapid vSAN Resync': [('Resync &mdash; how much rebuild work is outstanding?',
                        ['A resync is vSAN restoring data to the redundancy its storage policy asks for. The '
                         'top table counts resync jobs by state: pending, running, suspended and in flight.',
                         '<b>Rebuild IO rates</b> and <b>Back end during rebuild</b> show resync and '
                         "recovery IO and the component manager's latency at cluster level. <b>Segment "
                         "cleaning</b> shows the segment cleaner's operations, latency and throughput for "
                         'each host.'])],
 'Rapid vSAN ESA Write Path': [('ESA write path &mdash; how are the zDOM layer and segment cleaner '
                                'performing?',
                                ['This screen shows the ESA zDOM layer and the segment cleaner. <b>zDOM - '
                                 "cluster</b> and <b>zDOM - per host</b> show the layer's latency and "
                                 'throughput. <b>Write path internals</b> shows its cache and transaction '
                                 'figures. <b>Segment cleaning</b> shows the segment cleaner for each host, '
                                 'and <b>Back end - per host</b> shows the component manager beneath it.'])],
 'Rapid vSAN Host Resources': [('Host resources &mdash; what does vSAN itself consume on each host?',
                                ['This screen shows what vSAN consumes on a host: the memory used by each '
                                 "vSAN daemon, vSAN's CPU figures, and vSAN's network traffic aggregated per "
                                 "host. It does not show the host's total load, which vCenter reports in "
                                 '<b>Host health and load</b> on the Overview screen and <b>Every uplink - '
                                 'from vCenter</b> on the Network screen.',
                                 'The CPU table has one row per host. It shows <code>readyPct</code>, '
                                 '<code>usedPct</code> and <code>runPct</code> and the peak run and used '
                                 'percentages, as reported by the vSAN Performance Service.',
                                 'The memory table lists the memory consumed and reserved by each vSAN '
                                 'daemon. It reports memory use, not whether a daemon is responding.',
                                 "The network table is vSAN's traffic per host, where the Network screen "
                                 'shows the same counters per vmknic.'])]}


HOUSE_RULES = ('<b>A blank cell is not a zero.</b> A blank cell means no value was collected for that column in the selected period.', '<b>Raw columns are cumulative counts.</b> Where a column has a Raw twin, the Raw column is the cumulative count and the other column is a per-interval rate.')


def check_intro(name, panels, byview):
    """Fail the build if a narrative names a metric that is not a column on one
    of the dashboard's own views. A narrative describing a panel that was moved
    or removed is how stale text reaches a customer."""
    cols = set()
    for _title, view_key, _coords in panels:
        entry = byview.get(view_key.replace("_", " "))
        if entry:
            cols |= {c[0] for c in entry[2]}
    text = " ".join(" ".join([h] + ps) for h, ps in INTRO[name])
    for metric in re.findall(r"<code>([^<\s]+)</code>", text):
        if metric not in cols:
            raise SystemExit(f"{name}: narrative names {metric!r}, which is not a "
                             f"column on any of its views")


def panel_block(panel_title, view_title, kind, columns):
    out = [f'<h3 style="{H3}">{html.escape(panel_title)}</h3>']
    out.append(f'<p style="{P}">Renders the <b style="{BOLD}">'
               f'{html.escape(view_title)}</b> view.</p>')
    for key, _unit, _tr in columns:
        label = build_view.label_for(kind, key)
        note = NOTES.get(key)
        if not note:
            raise SystemExit(f"no explanation written for {kind}/{key}")
        note = style_inline(note)
        out.append(f'<p style="{P}"><span style="{NAME}">{html.escape(label)}'
                   f'</span> &mdash; {note}</p>')
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    byview = {e[0]: e for e in build_view.VIEWS}
    for name, help_file, panels in build_dash.DASHBOARDS:
        intro = INTRO.get(name)
        if intro is None:
            raise SystemExit(f"no narrative written for dashboard {name!r}")
        check_intro(name, panels, byview)
        body = [f'<div style="{WRAP}">']
        for heading, paras in intro:
            body.append(f'<h2 style="{H2}">{heading}</h2>')
            for para in paras:
                para = style_inline(para)
                body.append(f'<p style="{P}">{para}</p>')
        # Two reading rules every screen needs, stated once per panel so a
        # reader who only opens one panel still gets them.
        body.append(f'<h3 style="{H3}">Reading any column here</h3>')
        for para in HOUSE_RULES:
            body.append(f'<p style="{P}">{style_inline(para)}</p>')
        seen = set()
        for panel_title, view_key, _coords in panels:
            view_title = view_key.replace("_", " ")
            entry = byview.get(view_title)
            if entry is None:
                raise SystemExit(f"{name}: no view titled {view_title!r}")
            if view_key in seen:
                continue
            seen.add(view_key)
            body += panel_block(panel_title, entry[0], entry[1], entry[2])
        body.append("</div>")
        out = "\n".join(body) + "\n"
        path = os.path.join(OUT, f"{help_file}.EDITOR.html")
        open(path, "w").write(out)
        print(f"  {help_file}.EDITOR.html  {len(out):6d} bytes, "
              f"{len(seen)} panels documented")


if __name__ == "__main__":
    main()
