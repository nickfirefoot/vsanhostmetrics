#!/usr/bin/env python3
"""Generate the explanatory HTML that sits beneath each view on a dashboard.

    python3 tools/build_help_html.py      # writes ~/ops-content/out/help/

One file per view, plus one combined file. Generated from `build_view.py`'s
column lists so the text cannot drift out of sync with the tables: a metric
added to a view without a note here fails the build.

Two output forms, because Operations offers two:

  *.inline.html  paste into a Text Display widget's description box
  *.page.html    the shippable form -- a themed, localisable page served from
                 the pak at ContentPack/VsanHostMetrics/conf/pages/<name>/,
                 which is how Broadcom's own Read Me widgets work

Metric names are bold and match the view's column labels exactly.
"""
import html
import os
import sys

sys.path.insert(0, "tools")
sys.path.insert(0, "app")
import build_view                                        # noqa: E402

OUT = os.path.expanduser("~/ops-content/out/help")

# What each column means, why it is on the screen, and what it does NOT tell
# you. Written against measurements from a live cluster where one exists.
NOTES = {
 # ---- physical NIC -------------------------------------------------------
 "rxMissErr": "The NIC's receive ring had no free descriptor, so the packet was dropped before the driver ever saw it. The clearest single sign that a NIC is being overrun. Distinct from a drop (discarded higher up) and an error (arrived damaged).",
 "rxCrcErr": "The frame arrived damaged and failed its checksum. Almost always physical: cable, connector, optic or port. Not a capacity problem.",
 "rxErr": "Receive errors not attributed to a more specific counter. Useful as a catch-all; look to the specific counters first.",
 "rxFifoErr": "The NIC's own on-chip buffer overflowed before it could move packets across PCIe into host memory. The NIC could not hand data over fast enough.",
 "rxOvErr": "Receive buffer overrun. Driver-dependent and often moves with FIFO errors; both mean the receive path could not keep up.",
 "txCarErr": "Carrier lost while transmitting -- a physical link problem. Check the port, cable and link negotiation.",
 "txErr": "Transmit errors not attributed to a more specific counter.",
 "portRxDrops": "The vSwitch discarded inbound packets for this port. A small, constant rate is usually normal: broadcast and multicast traffic the switch has nowhere to deliver. A rate that <i>changes</i> is the signal, not its presence.",
 "portTxDrops": "The vSwitch discarded outbound packets for this port.",
 "pauseCount": "802.3x pause frames. These are flow control -- the host and the switch asking each other to slow down. <b>No direction is available</b>, so a non-zero value cannot distinguish 'this host is drowning' from 'the fabric is congested'. Check flow control is even enabled on the uplink before reading a zero as healthy.",
 "ioChainDrops": "Packets dropped inside the ESXi IO chain, above the NIC and below the vSwitch port.",
 "ioChainRxdrops": "Inbound packets dropped inside the ESXi IO chain.",
 "ioChainTxdrops": "Outbound packets dropped inside the ESXi IO chain.",
 "rxMissErrRaw": "Lifetime count of missed receive errors since the host booted. The rate columns answer <i>is it happening now</i>; this answers <i>has this NIC ever been bad</i>. A NIC reading 0% now with thousands here has a history worth knowing.",
 "rxCrcErrRaw": "Lifetime count of CRC errors since boot.",
 "pfcCountRaw": "Lifetime count of priority flow control frames since boot.",
 "portTxpkts": "Packets transmitted on this vSwitch port. Context, not a fault -- an error count means nothing without knowing the traffic it happened against.",
 # ---- host network -------------------------------------------------------
 "rxPacketsLossRate": "Proportion of inbound packets discarded at the host network layer, across all of this host's vSAN traffic rather than one uplink.",
 "txPacketsLossRate": "Proportion of outbound packets discarded at the host network layer.",
 "rxThroughput": "Inbound throughput for this host's vSAN traffic. Context for the error columns.",
 "txThroughput": "Outbound throughput for this host's vSAN traffic.",
 "rxPackets": "Inbound packets per second.",
 "txPackets": "Outbound packets per second.",
 # ---- TCP ----------------------------------------------------------------
 "tcpTxRexmitRate": "Segments this host had to send again because they were not acknowledged. The cost of loss somewhere on the path, paid in latency.",
 "tcpRxErrRate": "Inbound TCP segments rejected as erroneous.",
 "tcpRcvdupackRate": "Duplicate acknowledgements received. The peer is telling us, repeatedly, that it is still missing something -- an early sign of loss on our outbound path, visible before a retransmit timer fires.",
 "tcpRcvduppackRate": "Duplicate packets received: the same data arrived twice, usually because a peer retransmitted something that was not actually lost.",
 "tcpRcvoopackRate": "Packets arriving out of order. Broadcom treat 0.1% as a warning and 1% as critical. Reordering alone is not loss, but TCP responds to it as though it were.",
 "tcpSackRcvBlocksRate": "SACK blocks <b>received</b>. The peer is reporting holes in what <b>we sent it</b>, so this points at loss on our <b>outbound</b> path. Appears before retransmit timeouts do.",
 "tcpSackSendBlocksRate": "SACK blocks <b>sent</b>. We are reporting holes in what <b>the peer sent us</b> -- loss on our <b>inbound</b> path. The mirror image of the column above, and reading the pair tells you which direction is losing.",
 "tcpSackRexmitsRate": "Retransmissions we performed because SACK information told us precisely which segments were missing.",
 "tcpTimeoutDropRate": "Established connections torn down because the retransmission timer expired. The end state of sustained loss: the stack gave up rather than kept trying.",
 "tcpHalfopenDropRate": "Connections dropped mid-handshake, in SYN_RCVD -- a SYN arrived, the reply went out, the confirmation never came. <b>Reads 7-9% on a healthy cluster here and the denominator is undocumented</b>, so do not treat a non-zero value as a fault until that is understood.",
 "tcpSndZeroWin": "Times this host told a peer to stop sending because its receive buffer was full. <b>Not a network fault</b> -- the network delivered and the host could not consume. Look up the stack at CPU and at the vSAN layers, not at the wire.",
 "tcpErrs": "Total TCP errors recorded by this host's stack since boot.",
 # ---- RDT ----------------------------------------------------------------
 "avgLatency": "Average round-trip latency of vSAN's own transport between hosts. This sits above TCP, so it can be slow while every NIC counter is clean.",
 "maxLatency": "Worst round-trip latency observed. Spikes here matter more than the average -- one stalled transfer blocks whatever was waiting on it.",
 "minLatency": "Best round-trip latency observed. Useful only as a floor to compare the average against.",
 "txQLatAvg": "Average time a message waited in the outbound queue before being sent. Queueing, as opposed to time on the wire.",
 "txQLatMax": "Worst outbound queueing delay observed.",
 "txSbSpaceMin": "Lowest free space seen in the outbound socket buffer. <b>Low is bad</b> -- this measures headroom remaining, so it reads backwards from every other column. Zero means exhaustion and a stalled transport.",
 "rxSbSpaceMin": "Lowest free space seen in the inbound socket buffer. <b>Low is bad</b>, for the same reason.",
 "rxSbSpaceMax": "Highest free space seen inbound. Context for the minimum beside it.",
 "kaReset": "Lifetime count of keepalive resets: RDT gave up on a peer connection and re-established it. <b>Cumulative since boot</b>, so the number itself means little -- watch whether it is <i>increasing</i>.",
 "numReadyDelay": "Lifetime count of delays waiting for a connection to become ready. <b>Cumulative since boot</b>; the trend is the signal.",
 # ---- ESA disk, vSAN layer ----------------------------------------------
 "avgLatReadCapacity": "Read latency as vSAN sees it, above the device. Compare across disks rather than against a fixed number: the signal is one disk diverging from its peers.",
 "avgLatWriteCapacity": "Write latency as vSAN sees it.",
 "avgLatWritePerf": "Write latency at the performance tier.",
 "iopsReadCapacity": "Read operations per second at the vSAN layer. Context -- high latency at high IOPS is a busy disk, high latency at low IOPS is a sick one.",
 "iopsWriteCapacity": "Write operations per second at the vSAN layer.",
 # ---- ESA disk, physical layer ------------------------------------------
 "latencyDevRead": "Read latency at the physical and firmware layer, below vSAN. Compare with the vSAN layer column: if both are high the device is slow, if only the vSAN layer is high the delay is above the disk.",
 "latencyDevWrite": "Write latency at the physical and firmware layer.",
 "latencyDevDAvg": "<b>DAVG</b> -- time spent in the device itself. High DAVG is a slow or failing drive.",
 "latencyDevKAvg": "<b>KAVG</b> -- time spent queued in the VMkernel before reaching the device. High KAVG is contention, not a bad disk.",
 "latencyDevGAvg": "<b>GAVG</b> -- what the guest actually experiences, being DAVG plus KAVG. Read the three together: GAVG tells you it hurts, DAVG and KAVG tell you which to fix.",
 # ---- VM -----------------------------------------------------------------
 "latencyRead": "Read latency for this virtual disk, measured at the vSAN layer.",
 "latencyWrite": "Write latency for this virtual disk, measured at the vSAN layer.",
 "iopsRead": "Read operations per second. Always read beside latency: high latency at high IOPS is a busy VM, high latency at near-zero IOPS is a sick one.",
 "iopsWrite": "Write operations per second.",
}

PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="X-UA-Compatible" content="IE=edge;chrome=1;" />
    <link rel="stylesheet" type="text/css" href="css/main.css">
    <script>
        var cssId = 'themeCss';
        if (!document.getElementById(cssId)) {{
            var head = document.getElementsByTagName('head')[0];
            var link = document.createElement('link');
            link.id = cssId; link.rel = 'stylesheet'; link.type = 'text/css';
            link.href = 'css/' + parent.colorScheme + '.css'; link.media = 'all';
            head.appendChild(link);
        }}
    </script>
</head>
<body>
    <div class="main-div">
{body}
    </div>
</body>
</html>
"""


def body_for(title, kind, columns):
    out = [f"        <h3>{html.escape(title)}</h3>"]
    for key, _unit, _tr in columns:
        label = build_view.label_for(kind, key)
        note = NOTES.get(key)
        if not note:
            raise SystemExit(f"no explanation written for {kind}/{key}")
        out.append(f'        <p><b>{html.escape(label)}</b> &mdash; {note}</p>')
    return "\n".join(out)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    combined = []
    for title, kind, columns in build_view.VIEWS:
        body = body_for(title, kind, columns)
        combined.append(body)
        name = title.replace(" ", "_")
        open(os.path.join(OUT, f"{name}.inline.html"), "w").write(body + "\n")
        open(os.path.join(OUT, f"{name}.page.html"), "w").write(PAGE.format(body=body))
        print(f"  {name}: {len(columns)} metrics")
    allbody = "\n".join(combined)
    open(os.path.join(OUT, "ALL.inline.html"), "w").write(allbody + "\n")
    open(os.path.join(OUT, "ALL.page.html"), "w").write(PAGE.format(body=allbody))
    print(f"\n  wrote {OUT}")


if __name__ == "__main__":
    main()
