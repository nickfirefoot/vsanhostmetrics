#!/usr/bin/env python3
"""Say exactly why vSAN objects are not attaching to vCenter objects.

    VC_HOST=vc.example.com VC_USER=svc@vsphere.local VC_PASS=... \
      python3 tools/diagnose_parents.py

Run it from anywhere that can reach the vCenter, with the SAME credentials the
adapter instance uses. It makes no changes and writes nothing.

WHY THIS EXISTS. Every vSAN object this pack creates is attached to the vCenter
host, VM or cluster it belongs to. When that attachment fails the object is
still created, still collects, still carries correct metrics -- and is an
orphan. Downstream that presents as "The selected Object is not applicable" on
every view, empty panels on every dashboard, and a Topology tab showing a single
node with no edges. All of which read as broken CONTENT and are nothing of the
kind.

Worse, the attachment has a single point of failure. Every parent lookup needs
the vCenter instance UUID, so if that one property is unreadable, every object
is orphaned at once -- cluster-scoped and host-scoped alike -- and until now
nothing said so.

This checks each step and names the one that failed.
"""
from __future__ import annotations

import os
import ssl
import sys

sys.path.insert(0, "app")
sys.path.insert(0, "app/vendor")


def main() -> int:
    for var in ("VC_HOST", "VC_USER", "VC_PASS"):
        if not os.environ.get(var):
            sys.exit(f"set {var}")

    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim

    host = os.environ["VC_HOST"]
    si = SmartConnect(host=host, user=os.environ["VC_USER"],
                      pwd=os.environ["VC_PASS"],
                      sslContext=ssl._create_unverified_context())
    fail = []
    try:
        content = si.RetrieveContent()

        # 1. the single point of failure
        vcid = getattr(content.about, "instanceUuid", "") or ""
        print(f"1. vCenter instanceUuid     : {vcid or '*** EMPTY ***'}")
        if not vcid:
            fail.append("instanceUuid is empty, so EVERY object will be orphaned")
        print(f"   vCenter                  : {content.about.name} "
              f"{content.about.version} build {content.about.build}")

        # 2. clusters, which is what cluster-scoped objects attach through
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.ClusterComputeResource], True)
        clusters = list(view.view)
        view.Destroy()
        print(f"\n2. clusters visible         : {len(clusters)}")
        if not clusters:
            fail.append("no clusters visible -- the account likely lacks "
                        "read-only propagated from the vCenter root")

        vsan_clusters = 0
        for cluster in clusters:
            cuuid = None
            why = ""
            try:
                cfg = getattr(getattr(cluster, "configurationEx", None),
                              "vsanConfigInfo", None)
                cuuid = getattr(getattr(cfg, "defaultConfig", None), "uuid", None)
            except Exception as exc:                      # noqa: BLE001
                why = f" ({type(exc).__name__})"
            state = cuuid or f"*** NO vSAN CLUSTER UUID ***{why}"
            print(f"   {cluster.name:<28} vsan uuid = {state}")
            if cuuid:
                vsan_clusters += 1
        if clusters and not vsan_clusters:
            fail.append("no cluster exposed a vSAN cluster UUID via "
                        "configurationEx.vsanConfigInfo -- cluster-scoped "
                        "objects cannot attach")

        # 3. hosts, which is what host-scoped objects attach through
        print()
        total_hosts = resolved = 0
        for cluster in clusters:
            for h in (getattr(cluster, "host", None) or []):
                total_hosts += 1
                node = None
                why = ""
                try:
                    node = h.configManager.vsanSystem.config.clusterInfo.nodeUuid
                except Exception as exc:                  # noqa: BLE001
                    why = f" ({type(exc).__name__})"
                if node:
                    resolved += 1
                print(f"3. {h.name:<28} vsan nodeUuid = "
                      f"{node or '*** UNREADABLE ***' + why}")
        print(f"   hosts resolved           : {resolved} of {total_hosts}")
        if total_hosts and not resolved:
            fail.append("no host exposed a vSAN node UUID via "
                        "configManager.vsanSystem -- host-scoped objects "
                        "cannot attach")
    finally:
        Disconnect(si)

    print()
    if fail:
        print("ORPHANING WILL OCCUR. Causes found:")
        for f in fail:
            print(f"   - {f}")
        print("\nObjects will still be created and still collect metrics. They "
              "will have no parent, so every view reports the selected object "
              "as not applicable and every dashboard panel is empty.")
        return 1
    print("Parent resolution looks healthy: objects should attach to their "
          "vCenter host, VM and cluster.")
    print("\nIf objects are STILL orphaned with this passing, the identifiers "
          "are resolving but not MATCHING. Compare the VMEntityVCID on a "
          "HostSystem object in Operations against the instanceUuid above -- "
          "they must be identical, which requires this adapter and the vCenter "
          "adapter to point at the same vCenter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
