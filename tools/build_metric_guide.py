#!/usr/bin/env python3
"""Generate docs/METRICS-GUIDE.md -- what each family of metrics IS.

    python3 tools/build_metric_guide.py

The metric reference in README.md answers "what does this metric mean". This
answers the question before it: "what is DOM, and why are there three of them".
Without that, 994 attributes across 31 resource kinds is an undifferentiated
wall, and nobody can tell whether `host-domowner` or `host-domclient` is the
one they want.

Section prose is hand-written because it is domain knowledge, not something
derivable from the schema. Counts and tables are generated so they cannot
drift. Anything not confirmed against a live service or Broadcom's own
description is marked [unverified].
"""
import sys

sys.path.insert(0, "app")
import perfsvc  # noqa: E402
import perfsvc_model  # noqa: E402

# (branch, blurb, [entity ids])  -- order is the reading order of the document.
BRANCHES = [
    ("Network — physical and VMkernel",
     """The path a vSAN packet takes, from the wire upwards. These are the
grey-state signals: a NIC losing a fraction of a percent of frames still moves
traffic at line rate, so throughput looks healthy while the cluster suffers.

Read them outside-in. `vsan-pnic-net` is the physical wire, `vsan-vnic-net` the
VMkernel adapter above it, `vsan-tcpip-stats` the TCP/IP stack, and
`vsan-host-net` the host-wide roll-up. An error that appears at the pNIC and
nowhere else is cabling, optics or a switch port; one that appears only higher
up is software or congestion.""",
     ["vsan-pnic-net", "vsan-vnic-net", "vsan-tcpip-stats", "vsan-host-net"]),

    ("Network — RDT, vSAN's own transport",
     """RDT (Reliable Datagram Transport) is the protocol vSAN uses between
hosts, running over TCP. It is *not* the same thing as the NIC counters above:
a perfectly healthy NIC can sit underneath an RDT layer that is stalling.

The socket-buffer and context-queue metrics are the interesting ones.
`txSbSpaceMin` is the minimum free space in the transmit socket buffer over the
interval -- when it reaches zero, vSAN's transport has nowhere to put data and
the IO path blocks. `kaReset` counts keepalive resets, which means RDT
connections are being torn down and rebuilt; that survives a NIC that looks
entirely fine.""",
     ["rdt-net", "rdt-network-latency", "vnic-rdt-network-latency",
      "cluster-rdt-network-latency"]),

    ("Storage — the DOM layers",
     """**DOM** is the Distributed Object Manager: the layer that turns "write
to this VM disk" into "write to these components on these hosts". Every vSAN
object has three DOM roles acting on it simultaneously, on potentially three
different hosts, which is why there are three families rather than one.

| Role | Runs on | Answers |
|---|---|---|
| **DOM Client** | the host where the *VM* runs | what the guest asked for, and what latency it saw |
| **DOM Owner** | one elected host *per object* | coordination, resync, recovery writes, congestion |
| **DOM Component Manager** | every host holding a *component* | the local half -- this host's share of the work |

So a slow VM with clean Component Manager metrics means the problem is not
local disk. High Owner congestion with quiet Client metrics usually means
resync or rebuild work rather than guest IO.

The `cluster-dom*` families are the same three roles aggregated cluster-wide,
useful as a starting point before drilling to a host.""",
     ["host-domclient", "host-domowner", "host-domcompmgr",
      "cluster-domclient", "cluster-domowner", "cluster-domcompmgr"]),

    ("Storage — ZDOM, the log-structured layer (ESA)",
     """**ZDOM** sits between DOM and the disks in vSAN ESA. It is a
log-structured layer: incoming writes are coalesced into a log and written
sequentially, then a segment cleaner later compacts them into their final
position.

That design is why ESA can absorb bursty small writes, and it is also a
distinct failure surface. Segment-cleaning falling behind shows up here before
it shows up as guest latency, so these are leading indicators rather than
symptoms.

`zdom-vtx` covers the transaction layer (71 metrics, the largest network-
adjacent family); the `*-top-stats` families are the summarised view.""",
     ["zdom-vtx", "host-zdom-top-stats", "cluster-zdom-top-stats"]),

    ("Storage — physical disks (OSA)",
     """The OSA disk stack, silent on an ESA cluster and the reason
`perfsvc_model_extra.py` exists -- the live model was generated against ESA, so
these were absent entirely and an OSA cluster would have collected none of it.

A **disk group** is OSA's unit of storage: one cache device fronting several
capacity devices. `cache-disk` and `capacity-disk` are the two tiers;
`disk-group` carries the scheduler and congestion view, which is *richer* than
anything ESA exposes -- `diskgroupCongestionReadSched`, `iopsDelayPctSched`,
`latencySched`, plus resync broken out by cause (evacuation, repair, policy
change, rebalance).

`cluster-resync` is the cluster-wide rebuild picture: how much is outstanding
and why.

**Provisional.** Metrics are the *advertised* set, which understates what the
service returns, and identity is inferred. Model a real OSA cluster with
`tools/model_from_perfsvc.py` and fold the result in.""",
     ["disk-group", "cache-disk", "capacity-disk", "cluster-resync"]),

    ("Storage — physical disks (ESA)",
     """Two views of the same NVMe device, and the distinction matters when
diagnosing.

`vsan-esa-disk-layer` is what the **vSAN layer** asked the disk to do.
`vsan-esa-disk-scsifw` is what the **SCSI framework** actually did. Latency
diverging between the two means time is being spent above the device -- queuing,
scheduling -- rather than in the media.

**There are no media-error counters here.** No SMART data, no reallocated
sectors, no CRC. The Performance Service is a performance service. A failing
NVMe is detected by service-time outliers (`maxWriteTimePerf` spiking while
median latency and IOPS stay flat), not by an error count.""",
     ["vsan-esa-disk-layer", "vsan-esa-disk-scsifw"]),

    ("Cluster services",
     """**CMMDS** (Cluster Monitoring, Membership and Directory Service) is
vSAN's directory: which objects exist, where their components live, which hosts
are in the cluster. `cmmds-net` measures its traffic -- heartbeats, unicast and
multicast updates.

Elevated CMMDS traffic without a corresponding change in workload usually means
membership churn or an object being reconfigured, and it precedes visible
trouble.""",
     ["cmmds-net", "vsan-cluster-capacity", "vsan-dp-historical-stats"]),

    ("Compute and memory",
     """vSAN's own CPU and memory consumption, not the host's. `dom-world-cpu`
is per-world (per-process) detail and is by far the largest object family --
315 objects on a four-host cluster, and it scales per host.

`vsan-memory` covers heap and slab consumption by vSAN's own components. Heap
exhaustion is a classic grey failure: everything works normally until an
allocation fails.""",
     ["vsan-cpu", "host-cpu", "dom-world-cpu", "lsom-world-cpu",
      "vsan-memory", "system-mem"]),

    ("Virtual machines and their disks",
     """The guest-facing view. `vscsi` is the virtual SCSI controller per VM
disk -- the closest measurement to what the guest operating system experiences.
`virtual-disk` objects are the vSAN objects backing those disks.

`host-vsansparse` covers the sparse-snapshot layer, which is in the IO path
only for VMs with snapshots.""",
     ["vscsi", "virtual-disk", "virtual-machine", "host-vsansparse"]),
]


def main() -> None:
    ents = perfsvc_model.ENTITIES
    placed = {e for _, _, es in BRANCHES for e in es}
    missing = sorted(set(ents) - placed)
    total_attrs = sum(len(perfsvc.metrics_for(e)) for e in ents)

    out = [
        "# Metric guide — what each family of metrics is",
        "",
        "Companion to the metric reference in `README.md`. That one answers "
        "*what does this metric mean*; this answers the question before it — "
        "*what is DOM, and why are there three of them*.",
        "",
        f"**{total_attrs} attributes across {len(ents)} resource kinds.** "
        "Generated by `tools/build_metric_guide.py`; the counts come from the "
        "model, the explanations are hand-written.",
        "",
        "Per-metric definitions, including Broadcom's own wording where they "
        "publish it, are in the metric reference at the bottom of `README.md`.",
        "",
    ]

    for branch, blurb, entities in BRANCHES:
        attrs = sum(len(perfsvc.metrics_for(e)) for e in entities if e in ents)
        out += [f"## {branch}", "", blurb, "",
                "| Resource kind | perfsvc entity | Metrics | Objects | Identified by |",
                "|---|---|---|---|---|"]
        for e in entities:
            if e not in ents:
                continue
            s = ents[e]
            ident = ", ".join(f"`{i}`" for i in s["identity"])
            out.append(f"| **{s['kind']}** | `{e}` | "
                       f"{len(perfsvc.metrics_for(e))} | "
                       f"{s['objects_observed']} | {ident} |")
        out += ["", f"*{attrs} attributes in this branch.*", ""]

    if missing:
        out += ["## Not yet categorised", "",
                "Present in the model but not placed in a branch above:", ""]
        for e in missing:
            out.append(f"- `{e}` — {ents[e]['kind']}, "
                       f"{len(perfsvc.metrics_for(e))} metrics")
        out.append("")

    out += [
        "## Reading any of these",
        "",
        "Three things apply across every family and are easy to get wrong:",
        "",
        "**Ratios are percent, converted from per-mille.** The Performance "
        "Service reports 24 of these in parts per thousand. The adapter divides "
        "by ten and labels them `(%)`, so they can be compared directly against "
        "Broadcom's published thresholds — but they will *disagree with the "
        "vSphere UI*, which shows the raw per-mille value.",
        "",
        "**`*Raw` is cumulative since boot; the base metric is per-interval.** "
        "`pauseCountRaw` reads 224 while `pauseCount` reads 0 — the first is a "
        "lifetime total, the second is what happened in the last five minutes.",
        "",
        "**Everything is a point value already reduced into 5-minute buckets.** "
        "There are no counters to difference and no rates to derive; the "
        "service has done that. `*Raw` is the only exception.",
        "",
    ]

    open("docs/METRICS-GUIDE.md", "w").write("\n".join(out) + "\n")
    print(f"  wrote docs/METRICS-GUIDE.md — {len(BRANCHES)} branches, "
          f"{len(placed)}/{len(ents)} entity types placed")
    if missing:
        print(f"  NOT categorised: {missing}")


if __name__ == "__main__":
    main()
