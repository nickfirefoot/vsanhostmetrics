#!/usr/bin/env python3
"""Read host BIOS version AND release date from vCenter, for every host.

    VC_HOST=... VC_USER=... VC_PASS=... python3 tools/host_bios.py

Operations already collects `hardware|biosVersion` as a **property** on every
`VMWARE`/`HostSystem` object, with no configuration and regardless of whether
the host runs vSAN. What it does not surface is `releaseDate`, and that is the
field that matters: a vendor string like `P3.30` cannot tell you whether a BIOS
is current, and a date can.

`vim.host.BIOSInfo` carries eight fields. This reads all of them.

The path, for reference:

    ServiceInstance.RetrieveContent()
      -> content.rootFolder                     vim.Folder
        -> (datacenter, hostFolder, cluster)
          -> host[]                             vim.HostSystem
            -> hardware                         vim.host.HardwareInfo
              -> biosInfo                       vim.host.BIOSInfo
                 biosVersion, releaseDate, vendor,
                 majorRelease, minorRelease,
                 firmwareMajorRelease, firmwareMinorRelease,
                 firmwareType

Walking that tree object by object is the obvious way and the wrong one. This
uses a ContainerView plus one PropertyCollector call with `hardware.biosInfo`
in the path set, so every host comes back in a single round trip.

Read-only: CreateContainerView and RetrieveContents, nothing else.
"""
import os, sys, ssl
sys.path.insert(0, 'app'); sys.path.insert(0, 'app/vendor')
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

ctx = ssl._create_unverified_context()
si = SmartConnect(host=os.environ['VC_HOST'], user=os.environ['VC_USER'],
                  pwd=os.environ['VC_PASS'], sslContext=ctx)
content = si.RetrieveContent()

# One PropertyCollector call for every host, rather than walking the tree.
view = content.viewManager.CreateContainerView(
    content.rootFolder, [vim.HostSystem], True)
spec = vmodl.query.PropertyCollector.FilterSpec(
    objectSet=[vmodl.query.PropertyCollector.ObjectSpec(
        obj=view,
        skip=False,
        selectSet=[vmodl.query.PropertyCollector.TraversalSpec(
            name='viewToHost', type=vim.view.ContainerView,
            path='view', skip=False)])],
    propSet=[vmodl.query.PropertyCollector.PropertySpec(
        type=vim.HostSystem, all=False,
        pathSet=['name', 'hardware.biosInfo',
                 'hardware.systemInfo.vendor',
                 'hardware.systemInfo.model',
                 'summary.config.product.fullName'])])
results = content.propertyCollector.RetrieveContents([spec])

for obj in results:
    p = {x.name: x.val for x in obj.propSet}
    b = p.get('hardware.biosInfo')
    print("host %s" % p.get('name'))
    print("   vendor / model      : %s / %s" % (p.get('hardware.systemInfo.vendor'),
                                                p.get('hardware.systemInfo.model')))
    print("   esxi                : %s" % p.get('summary.config.product.fullName'))
    if b is None:
        print("   hardware.biosInfo   : not returned")
        continue
    print("   biosVersion         : %s" % b.biosVersion)
    print("   releaseDate         : %s" % b.releaseDate)
    print("   vendor              : %s" % b.vendor)
    print("   majorRelease        : %s" % b.majorRelease)
    print("   minorRelease        : %s" % b.minorRelease)
    print("   firmwareMajorRelease: %s" % b.firmwareMajorRelease)
    print("   firmwareMinorRelease: %s" % b.firmwareMinorRelease)
    print("   firmwareType        : %s" % b.firmwareType)
view.Destroy()
Disconnect(si)
