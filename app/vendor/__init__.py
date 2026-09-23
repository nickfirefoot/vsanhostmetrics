"""Vendored vSAN management SDK bindings.

Not on PyPI - Broadcom ships these as loose files in the vSAN Management SDK.
Taken from vmware-archive/vsan-integration-for-prometheus.

KNOWN STALENESS: these are 2021-era bindings (vsan.version.version12) talking
to a 9.1.1 server. They work for VsanPerfQueryPerf, but vim.vsan.MetricProfile
exposes only authToken while the host config store schema has three fields.
Anything inferred about newer structures from these bindings is incomplete.
"""
