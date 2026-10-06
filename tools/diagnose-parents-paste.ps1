# Condensed form of Diagnose-VsanParents.ps1, for sites that cannot reach
# GitHub to fetch the full script. Paste straight into a PowerCLI prompt that
# is already Connect-VIServer'd to the vCenter the ADAPTER uses, as the account
# the ADAPTER uses. Read-only.
#
# Values print inside [brackets] so an empty one is unmistakable: [] not blank.
#   1 empty -> every object orphaned, cluster and host alike
#   2 empty -> cluster-scoped objects cannot attach
#   3 empty -> host-scoped objects cannot attach (the join 1.4.4 changed)

$a = $global:DefaultVIServer.ExtensionData.Content.About
"1. instanceUuid = [{0}]  ({1} build {2})" -f $a.InstanceUuid, $a.Version, $a.Build

foreach ($c in Get-Cluster) {
  "2. {0,-26} vsanClusterUuid = [{1}]" -f $c.Name,
    $c.ExtensionData.ConfigurationEx.VsanConfigInfo.DefaultConfig.Uuid
}

foreach ($h in Get-VMHost) {
  $n = $null
  $m = $h.ExtensionData.ConfigManager.VsanSystem
  if ($m) { try { $n = (Get-View $m).Config.ClusterInfo.NodeUuid } catch { } }
  "3. {0,-26} vsanNodeUuid    = [{1}]" -f $h.Name, $n
}
