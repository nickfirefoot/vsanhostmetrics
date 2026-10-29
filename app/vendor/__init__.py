"""Vendored vSAN management SDK bindings.

Not on PyPI - Broadcom ships these as loose files in the vSAN Management SDK.
Taken from vmware-archive/vsan-integration-for-prometheus.

KNOWN STALENESS: these are 2021-era bindings (vsan.version.version12) talking
to a 9.1.1 server. They work for VsanPerfQueryPerf, but vim.vsan.MetricProfile
exposes only authToken while the host config store schema has three fields.
Anything inferred about newer structures from these bindings is incomplete.

SHADOWING: pyVmomi 8.0.3.0.1 also installs a top-level `vsanapiutils` (and
`vsanmgmtObjects`) in site-packages. These copies win only because perfsvc.py
puts this directory first on sys.path. pyVmomi's vsanapiutils still sets
ssl._create_default_https_context to the unverified one in
GetLatestVmodlVersion; this copy no longer does (LOCAL CHANGE, see there).
Dropping this directory for pyVmomi's maintained bindings needs a live
regression run.
"""
