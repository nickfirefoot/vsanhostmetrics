# Baseline captures, 2026-09-23

Snapshots taken either side of disabling vSAN Performance Service verbose and
network diagnostic mode, to establish what a customer-representative
configuration actually provides.

| File | What |
|---|---|
| `host-exposition-VERBOSE-ON.txt` | `/vsanmetrics` from esxi01, both modes enabled |
| `host-exposition-VERBOSE-OFF.txt` | same, both modes disabled |
| `perfsvc-entities-VERBOSE-ON.json` | `VsanPerfGetSupportedEntityTypes`, modes enabled |
| `perfsvc-entities-VERBOSE-OFF.json` | same, modes disabled |
| `perfsvc-data-availability.json` | which entity types actually returned data, before/after |

Cutover: **2026-09-23 02:41:45 UTC** (`generation_num` 5 -> 6).

## Findings

**Disabling both modes changed nothing.**

```
host    155 names, 1912 series  ->  155 names, 1912 series   (byte-identical)
perfsvc  69 types,  841 metrics ->   69 types,  841 metrics
perfsvc  31/70 types with data  ->   31/70 types with data
```

So this pack's full metric set is available in the configuration Broadcom
recommends. That was a genuine risk -- every HELP string cites a kernel path
rather than the Performance Service, which *suggested* independence, but it is
now measured rather than inferred.

**Schema presence is not data availability.** 39 of 70 entity types are defined
but return nothing on this cluster, because the features are not in use --
iSCSI, file service, ESA dedup, pmem, stretched/remote, ioinsight, and the
disk-group/cache-disk/capacity-disk family (ESA has no disk groups). Notably
`cmmds-workload`, `heap-memory` and `slab-memory` are all defined and all
empty, so those remain host-only in practice.

## Where each source wins

| Verdict | Kinds | obj/host | our metrics |
|---|---|---|---|
| perfsvc richer | 3 | 19 | 23 |
| comparable | 3 | 334 | 12 |
| perfsvc thinner | 5 | 14 | 308 |
| host only, perfsvc empty | 5 | 127 | 42 |

The axes sort cleanly: perfsvc is comparable-or-better on the
**high-cardinality** families and thinner-or-absent on the **metric-dense**
ones.

Suggested hybrid:

* **perfsvc** for `EsxWorld` (267 obj), `HostCpu` (65), `VsanVdisk`, plus
  `EsxTcpIp` and `EsxPnic` where it is genuinely richer -- 16 metrics against
  our 11 and 6, adding TCP errors, congestion, CRC/carrier/FIFO and port drops.
* **host scrape** for `VsanEsa` (162 metrics), `VsanDom` (80), `VsanMemory`
  (62), `VsanCmmds` (33), both heaps and `EsxSlab`.

That takes the host scrape from **494 objects/host to ~160** while *gaining*
network depth. At 500 hosts: 80,000 objects rather than 247,000.

## Caveats

* The `EsxRdt` mapping above points at `rdt-network-latency` (1 metric) when
  `cluster-rdt-network-latency` has 15, including min/max/avg and queue depth.
  RDT is probably "perfsvc richer", not thinner. Re-check before relying on it.
* The AFTER window is only ~20 minutes. An entity collecting on a longer cycle
  could be misread as absent.
* Data availability is specific to this cluster's feature set. A site using
  iSCSI or file services would populate entity types that are empty here.
* The Python vSAN bindings used are from 2021 (`vsanmgmtObjects.py`, archived
  repo) against a 9.1.1 server. `vim.vsan.MetricProfile` exposes only
  `authToken`, while the host config store schema has three fields -- token,
  destination_url and interval. Anything inferred from the API about that
  structure is incomplete.
