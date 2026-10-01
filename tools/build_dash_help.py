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
  * No colour may be left to inherit. The dashboard renders on a dark
    background and unstyled text came out black on near-black -- the
    "help text is invisible" defect. Every element states its colour.
"""
import html
import os
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                        # noqa: E402
import build_dash                                        # noqa: E402
import build_help_html                                   # noqa: E402

OUT = os.path.expanduser("~/ops-content/out/help")
NOTES = build_help_html.NOTES

FG = "#ffffff"
ACCENT = "#8fd3ff"
RULE = "#4a5a66"
WRAP = ("font-family:'Metropolis','Segoe UI',sans-serif;font-size:13px;"
        f"color:{FG};padding:6px 12px")
H2 = f"font-size:15px;color:{FG};margin:4px 0 10px 0"
H3 = (f"font-size:13px;color:{FG};margin:16px 0 6px 0;"
      f"border-bottom:1px solid {RULE};padding-bottom:3px")
P = f"margin:5px 0;line-height:1.45;color:{FG}"
NAME = f"font-weight:600;color:{ACCENT}"

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
   ("vSAN network &mdash; where is the loss?",
    ["Four layers carry vSAN traffic and each can fail independently: <b>RDT</b>, vSAN's own "
     "transport; <b>TCP</b> beneath it; the <b>vmknic</b>, which is the kernel port; and the "
     "<b>physical NIC</b>. A clean NIC proves nothing about RDT, and a clean RDT proves "
     "nothing about the NIC.",
     "Read the layers from the top down and stop at the first one that is unhappy. Latency "
     "that appears at RDT but not at TCP is vSAN's own queueing. Loss that appears at the "
     "vmknic but not at the NIC is the host, not the fabric.",
     "<b>The last two tables are not from this pack.</b> This pack only measures uplinks that "
     "carry vSAN traffic, which on a typical host is two of four, so a standby uplink going "
     "bad is invisible to it. vCenter counts every uplink, so those columns close a gap "
     "rather than repeat one."]),
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
    out.append(f'<p style="{P}">Renders the <b style="color:{FG}">'
               f'{html.escape(view_title)}</b> view.</p>')
    for key, _unit, _tr in columns:
        label = build_view.label_for(kind, key)
        note = NOTES.get(key)
        if not note:
            raise SystemExit(f"no explanation written for {kind}/{key}")
        note = note.replace("<b>", f'<b style="color:{FG};font-weight:700">')
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
                para = para.replace("<b>", f'<b style="color:{FG};font-weight:700">')
                body.append(f'<p style="{P}">{para}</p>')
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
