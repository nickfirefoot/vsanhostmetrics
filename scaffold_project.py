"""
Non-interactive replacement for `mp-init` on this build host.

WHY THIS EXISTS: `mp-init` cannot complete here.  Its final step calls
venv.create(..., with_pip=True), and this host has no ensurepip (Debian splits
it into python3.12-venv, which is not installed and needs sudo).  That raises
SystemExit, which mp-init catches in a broad `except (KeyboardInterrupt,
Exception, SystemExit)` and responds to by rmtree-ing the project it just
generated -- so a plain `mp-init` run leaves nothing behind.

This script drives the same generator (PythonAdapter) directly with the answers
mp-init would have prompted for, calls create_project(), and writes
requirements.txt -- while SKIPPING create_virtual_environment().  That venv is
only an IDE convenience; `mp-test` runs the adapter in a Docker container built
from adapter_requirements.txt, so nothing downstream needs it.

If you later install python3.12-venv, plain `mp-init` will work normally.
"""
import os, sys, traceback
from vmware_aria_operations_integration_sdk.adapter_configurations.adapter_templates.python.python_adapter import PythonAdapter

PROJECT = "/home/vsanmp/vsan-host-metrics"

a = PythonAdapter(
    project_path=PROJECT,
    display_name="vSAN Host Metrics",
    adapter_key="VsanHostMetrics",
    adapter_description=(
        "Collects vSAN host TCP/IP networking counters directly from ESXi hosts "
        "via the host /vsanmetrics endpoint. Beta scope: the nine "
        "vmware_esx_tcppkt_* counters, as one resource kind."
    ),
    vendor="Denick Lab",
    eula_file_path="",
    icon_file_path="",
)

print("templates available:", [(os.path.basename(p), n) for p, n in a.templates])

# normally set by prompt_config_values(); we set it directly (non-interactive)
tmpl = dict((os.path.basename(p), p) for p, _ in a.templates)["new_adapter"]
a.response_values["adapter_template_path"] = tmpl
print("using template:", tmpl)

a.create_project()
print("create_project OK")

# requirements.txt is normally written by create_virtual_environment(); write it
# WITHOUT building the venv (ensurepip is unavailable on this host).
req = a._build_requirements_file()
print("requirements.txt written:", req)
