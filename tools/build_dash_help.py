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
INTRO = {
 "Rapid vSAN Overview": [
   ("vSAN overview &mdash; which layer is broken?",
    ["The pager went off and you do not yet know where to look. Each table below is a "
     "<b>layer of the IO path</b>, top to bottom, and the job of this screen is to point at "
     "one of them inside a minute. Then move to the matching detail screen.",
     "<b>Normal is front end above back end.</b> The front end carries network hops, owner "
     "coordination and policy work the disks never see, so it should read higher. "
     "<b>The two converging, or inverting, is the anomaly</b> &mdash; not either number on its own.",
     "The owner row between them is new. It is the layer that coordinates each write across "
     "its replicas, so it holds the cost of making a write durable in more than one place. "
     "When the front end is slow and the back end is not, the owner row is usually where the "
     "difference went."]),
 ],
 "Rapid vSAN Network": [
   ("vSAN network &mdash; is any layer losing frames right now?",
    ["Four layers carry vSAN traffic and each fails independently: <b>RDT</b>, vSAN's own "
     "transport; <b>TCP</b> beneath it; the <b>vmknic</b>, the kernel port; and the "
     "<b>physical NIC</b>. One panel per layer, top to bottom. <b>This is a triage screen, "
     "not a root-cause tool</b> &mdash; it answers whether and where, not why.",
     "<b>Read down and stop at the first unhappy layer.</b> Latency at RDT but not TCP is "
     "vSAN's own queueing. Loss at the vmknic but not the NIC is the host, not the fabric. "
     "A clean NIC proves nothing about RDT, and a clean RDT proves nothing about the NIC.",
     "<b>Every rate column is the period maximum, not the current value.</b> That is "
     "deliberate and measured: an error burst lands inside one five-minute bucket and is "
     "gone. A current value misses it almost every time you look.",
     "<b>Throughput is deliberately not on this screen.</b> A NIC discarding a fraction of "
     "a percent of frames still moves traffic at line rate, so a throughput panel stays "
     "green through the exact fault this exists to find.",
     "<b>Where a threshold is the vendor's, it says so; where it is ours, it says that "
     "too.</b> The per-mille bands on the pNIC error columns are vCenter's own: "
     "<code>alarm-261</code>, \"High pNic error rate detected\", fires at 1 per mille on "
     "eight counters. Everything else here is this pack's judgement, not a published "
     "standard.",
     "<b>The two pNIC panels are not duplicates.</b> <b>High pNIC error rate</b> carries "
     "only those eight alarm counters, so the screen matches what vCenter would alarm on. "
     "<b>pNIC stats &mdash; every counter</b> adds the drops, ioChain and lifetime columns "
     "the alarm ignores. The narrow one tells you vCenter agrees; the wide one tells you "
     "what else the NIC reports.",
     "<b>Lifetime counters answer a different question from rates.</b> The rate columns say "
     "whether it is happening now; <code>rxMissErrRaw</code> says whether this NIC has ever "
     "been bad. A uplink reading zero today with tens of thousands of lifetime missed "
     "errors has a history worth knowing before you call it healthy.",
     "<b>What this screen cannot see.</b> This pack measures only uplinks carrying vSAN "
     "traffic, which on a typical host is two of four, so a standby uplink going bad is "
     "invisible here &mdash; which is why the last panel comes from vCenter and counts every "
     "uplink. Pause-frame counts carry no direction, so a non-zero value cannot separate "
     "\"this host is drowning\" from \"the fabric is congested\", and a zero means nothing at "
     "all unless flow control is enabled on that uplink."]),
 ],
 "Rapid vSAN Storage": [
   ("vSAN storage &mdash; is it the disk or the queue?",
    ["This screen descends from the vSAN view of a disk to the device itself, then back up to "
     "what a guest experiences. The useful comparison is <b>between the layers</b>, not "
     "against any fixed threshold.",
     "<b>Compare disks against their peers, not against a number.</b> A cluster of disks at "
     "40 microseconds and one at 500 is the finding, whatever the absolute values are. One "
     "disk here was measured at 495 microseconds of device latency against 38 to 58 for its "
     "peers, with kernel latency flat &mdash; which is a slow device, not contention.",
     "The guest tables at the bottom come in two forms: per vSCSI controller, which is how "
     "vSAN accounts for IO, and per virtual machine, which is the unit a ticket gets raised "
     "about."]),
 ],
 "Rapid vSAN DOM": [
   ("DOM &mdash; the three layers of a vSAN write",
    ["DOM is the distributed object manager, and it has three layers. The <b>client</b> is the "
     "host a guest is running on. The <b>owner</b> is the host that coordinates a given "
     "object's writes, which may be a different host entirely. The <b>component manager</b> "
     "is what talks to the disks.",
     "A write passes through all three, so latency accumulates downward and should read "
     "highest at the client. Reading the same column across the three tables localises a "
     "problem to one layer in a way no single table can.",
     "<b>The owner layer was previously absent from every screen in this pack.</b> It returns "
     "272 metrics and 87 of them move on an idle cluster. Its latency maximum was measured at "
     "14.9 milliseconds against a 957 microsecond average, a fifteenfold tail that the "
     "averages everywhere else hide completely.",
     "The last table is vSAN's own congestion controller. It bands hosts by observed latency "
     "and throttles rebuild traffic to protect guest IO. The band counters say whether it is "
     "intervening, which nothing else here can show."]),
 ],
 "Rapid vSAN Backpressure": [
   ("Backpressure &mdash; is vSAN throttling itself, and which layer is doing it?",
    ["Congestion is vSAN telling you it has deliberately slowed something down to protect "
     "itself. It is not an error and it is not a failure &mdash; it is a control signal, and "
     "the useful question is never <b>is there congestion</b> but <b>which layer raised it "
     "and why</b>.",
     "<b>Read this screen top down.</b> The cluster tables say whether the whole cluster is "
     "under pressure. The per-host tables say whether it is one host. The RDT tables at the "
     "bottom say whether the problem is the network transport rather than the storage at "
     "all &mdash; which is the single most commonly misdiagnosed case, because every layer "
     "above reports congestion when the transport underneath is starved.",
     "<b>The congestion TYPE is the diagnosis.</b> Read congestion and write congestion "
     "point at different causes and different fixes. Unmap congestion is space reclamation "
     "competing with guest IO. Resync read congestion means rebuild traffic is the source, "
     "which is usually correct behaviour and self-clearing &mdash; the cluster is choosing "
     "redundancy over latency, and it will stop when the rebuild does.",
     "<b>Component congestion against shared congestion is the host-versus-device call.</b> "
     "Component congestion isolated to one object points at a device; shared congestion "
     "across a host points at the host. Acting on the wrong one replaces healthy hardware.",
     "On the RDT tables, <b>kaReset deserves attention out of proportion to its size</b>. "
     "Keepalive resets mean the transport dropped and re-established, and they survive a NIC "
     "that looks perfectly healthy on every error counter. Small buffer minima "
     "(txSbSpaceMin, rxSbSpaceMin) next to a rising queue latency is the signature of a "
     "transport running out of room rather than a disk running slow."]),
 ],
 "Rapid vSAN Resync": [
   ("Resync &mdash; how much risk is outstanding, and who is paying for it?",
    ["A resync means some data is below the redundancy its policy asks for. Two questions "
     "matter and they are different: <b>how much work is left</b>, and <b>what is that work "
     "costing the guests</b>.",
     "<b>Zero across the top table is the normal and desirable reading.</b> Nothing is "
     "rebuilding, so nothing is at reduced redundancy. The IO columns beside the job counts "
     "are there so that a screen of zeros can be told apart from a screen that is not "
     "collecting.",
     "If jobs are pending but not running, look at the scheduler table. vSAN deliberately "
     "throttles rebuild traffic when guest latency rises, so a deep queue with low "
     "parallelism is usually correct behaviour rather than a stall &mdash; but it does mean "
     "the cluster stays at reduced redundancy for longer, and that is a risk decision "
     "somebody should be making knowingly.",
     "Segment cleaning sits at the bottom because on ESA it competes with rebuild work for "
     "the same disks."]),
 ],
 "Rapid vSAN ESA Write Path": [
   ("ESA write path &mdash; the log, and the cost of keeping it tidy",
    ["ESA does not write in place. It appends to a log, acknowledges the write once it is "
     "logged, and later reclaims space by cleaning partially-used segments. That makes writes "
     "fast and makes <b>housekeeping a first-class source of latency</b>.",
     "This screen exists because none of that work was visible anywhere in this pack. Worst "
     "case segment cleaning latency was measured at <b>370 milliseconds against a 1.3 "
     "millisecond average</b> on an otherwise idle cluster.",
     "Read it top down: the zDOM tables give the layer's own latency and throughput, the "
     "write path internals show how hard the metadata and caching machinery is working, and "
     "segment cleaning shows the reclamation cost. The log fill percentage is the leading "
     "indicator &mdash; as it rises, cleaning has to work harder and write amplification "
     "goes up with it.",
     "<b>One caveat, stated plainly.</b> The zDOM maximum latency columns read in whole "
     "seconds, which is not credible as an interval maximum and is very likely a since-boot "
     "high-water mark that the Performance Service does not document as such. Use the average "
     "columns for decisions until that is confirmed."]),
 ],
 "Rapid vSAN Host Resources": [
   ("Host resources &mdash; is vSAN slow, or is the host out of road?",
    ["Every latency figure on every other screen is only meaningful if the host had capacity "
     "to spare. This screen answers that question first, so the others can be trusted.",
     "<b>Start with service health.</b> A daemon that is not answering explains more than any "
     "latency number will. This pack can measure how much memory clomd and cmmdsd consume but "
     "has no way to tell whether they are responding, and vCenter checks exactly that, so the "
     "two halves are on the same screen deliberately.",
     "<b>CPU contention matters more than CPU usage.</b> A host can be busy without anything "
     "waiting, and can make things wait while looking only moderately busy. Memory swap-in is "
     "the hard stop: any sustained non-zero value means memory was overcommitted far enough "
     "to page, and no latency figure anywhere else is reliable while it continues.",
     "The physical CPU table is listed per CPU rather than per host, so a single hot core is "
     "visible instead of averaged away."]),
 ],
}


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
        body = [f'<div style="{WRAP}">']
        for heading, paras in intro:
            body.append(f'<h2 style="{H2}">{heading}</h2>')
            for para in paras:
                para = style_inline(para)
                body.append(f'<p style="{P}">{para}</p>')
        # Two house rules every screen needs, stated once per panel rather than
        # hedged through the prose. A reader who only reads one panel still
        # gets them.
        body.append(f'<h3 style="{H3}">Reading any column here</h3>')
        for para in (
            "<b>A blank cell is not a zero.</b> Where a driver refuses a read, or a rate "
            "has no previous sample, this pack emits nothing rather than a zero &mdash; "
            "because a zero would claim the thing was measured and was fine.",
            "<b>Rate columns are the maximum over the interval, counters marked Raw are "
            "cumulative since boot.</b> They are not two views of one number: a Raw column "
            "beside its rate is a history beside a present reading, and neither is a "
            "duplicate of the other.",
        ):
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
