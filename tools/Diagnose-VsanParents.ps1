<#
.SYNOPSIS
    Say exactly why vSAN Host Metrics objects are not attaching to vCenter objects.

.DESCRIPTION
    PowerCLI equivalent of tools/diagnose_parents.py, for running from a Windows
    admin box rather than the build host.

    Every vSAN object this pack creates is attached to the vCenter host, VM or
    cluster it belongs to. When that attachment fails the object is still
    created, still collects, and still carries correct metrics -- and is an
    orphan. Downstream that shows as "The selected Object is not applicable" on
    every view, empty dashboard panels, and a Topology tab with a single node
    and no edges. All of which read as broken CONTENT and are nothing of the
    kind.

    Read-only. Connects, reads four things, disconnects. Changes nothing.

.PARAMETER Server
    vCenter FQDN. Use the SAME one the adapter instance is configured with.

.PARAMETER User
    Use the SAME account the adapter instance uses. A different account with
    more privilege will hide a privilege problem, which is the point of running
    this at all.

.EXAMPLE
    .\Diagnose-VsanParents.ps1 -Server vc01.example.com -User svc@vsphere.local
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$User,
    [string]$Password
)

if (-not $Password) {
    $sec = Read-Host -AsSecureString "Password for $User"
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

if (-not (Get-Module -ListAvailable -Name VMware.PowerCLI, VCF.PowerCLI)) {
    Write-Warning "PowerCLI not found. Install-Module VCF.PowerCLI -Scope CurrentUser"
}

$problems = New-Object System.Collections.Generic.List[string]

Set-PowerCLIConfiguration -InvalidCertificateAction Ignore -Confirm:$false -Scope Session | Out-Null
$vc = Connect-VIServer -Server $Server -User $User -Password $Password -ErrorAction Stop

try {
    # 1. The single point of failure. Every parent lookup needs this value, so
    #    an empty one orphans EVERY object at once, cluster and host alike.
    $si   = $vc.ExtensionData
    $vcid = $si.Content.About.InstanceUuid
    Write-Host ("1. vCenter instanceUuid     : {0}" -f $(if ($vcid) { $vcid } else { "*** EMPTY ***" }))
    Write-Host ("   vCenter                  : {0} {1} build {2}" -f `
        $si.Content.About.Name, $si.Content.About.Version, $si.Content.About.Build)
    if (-not $vcid) { $problems.Add("instanceUuid is empty, so EVERY object will be orphaned") }

    # 2. Clusters, which is how cluster-scoped objects attach.
    $clusters = Get-Cluster -ErrorAction SilentlyContinue
    Write-Host ("`n2. clusters visible         : {0}" -f @($clusters).Count)
    if (-not $clusters) {
        $problems.Add("no clusters visible -- the account likely lacks read-only propagated from the vCenter root")
    }

    $withVsanUuid = 0
    foreach ($c in $clusters) {
        $uuid = $null
        try { $uuid = $c.ExtensionData.ConfigurationEx.VsanConfigInfo.DefaultConfig.Uuid } catch { }
        if ($uuid) { $withVsanUuid++ }
        Write-Host ("   {0,-28} vsan uuid = {1}" -f $c.Name,
            $(if ($uuid) { $uuid } else { "*** NO vSAN CLUSTER UUID ***" }))
    }
    if ($clusters -and $withVsanUuid -eq 0) {
        $problems.Add("no cluster exposed a vSAN cluster UUID via ConfigurationEx.VsanConfigInfo -- cluster-scoped objects cannot attach")
    }

    # 3. Hosts, which is how host-scoped objects attach.
    Write-Host ""
    $total = 0; $resolved = 0
    foreach ($h in Get-VMHost) {
        $total++
        $node = $null
        try { $node = (Get-View $h.ExtensionData.ConfigManager.VsanSystem).Config.ClusterInfo.NodeUuid } catch { }
        if ($node) { $resolved++ }
        Write-Host ("3. {0,-28} vsan nodeUuid = {1}" -f $h.Name,
            $(if ($node) { $node } else { "*** UNREADABLE ***" }))
    }
    Write-Host ("   hosts resolved           : {0} of {1}" -f $resolved, $total)
    if ($total -gt 0 -and $resolved -eq 0) {
        $problems.Add("no host exposed a vSAN node UUID via ConfigManager.VsanSystem -- host-scoped objects cannot attach")
    }
}
finally {
    Disconnect-VIServer -Server $vc -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

Write-Host ""
if ($problems.Count -gt 0) {
    Write-Host "ORPHANING WILL OCCUR. Causes found:" -ForegroundColor Red
    foreach ($p in $problems) { Write-Host ("   - {0}" -f $p) -ForegroundColor Red }
    Write-Host "`nObjects will still be created and still collect metrics. They will have no parent, so every view reports the selected object as not applicable and every dashboard panel is empty."
    exit 1
}

Write-Host "Parent resolution looks healthy: objects should attach to their vCenter host, VM and cluster." -ForegroundColor Green
Write-Host "`nIf objects are STILL orphaned with this passing, the identifiers resolve but do not MATCH. Compare the VMEntityVCID on a HostSystem object in Operations against the instanceUuid above -- they must be identical, which requires this adapter and the vCenter adapter to point at the SAME vCenter."
exit 0
