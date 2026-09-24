"""GENERATED -- do not edit by hand.

Regenerate:
    python3 tools/build_model_extra.py

Entity types the LIVE model omits because they returned no data on the
cluster it was generated against -- principally every OSA family, which is
silent on ESA. Without these the pack never queries them, so an OSA cluster
collects nothing for its disk groups or cache and capacity disks.

PROVISIONAL. Metrics are the ADVERTISED set, which understates what the
service returns; identity is INFERRED from the entity name and the
equivalent ESA families. Model a real OSA cluster properly with
tools/model_from_perfsvc.py and fold the result into perfsvc_model.py.
"""

from typing import Any, Dict

ENTITIES: Dict[str, Dict[str, Any]] = {
    'cache-disk': {
        'kind': 'VsanCacheDisk',
        'label': 'vSAN Cache Disk (OSA)',
        'identity': ['disk_uuid'],
        'objects_observed': 0,
        'metrics': [
            'iopsDevRead',
            'iopsDevWrite',
            'latencyDevDAvg',
            'latencyDevGAvg',
            'latencyDevRead',
            'latencyDevWrite',
            'throughputDevRead',
            'throughputDevWrite',
        ],
    },
    'capacity-disk': {
        'kind': 'VsanCapacityDisk',
        'label': 'vSAN Capacity Disk (OSA)',
        'identity': ['disk_uuid'],
        'objects_observed': 0,
        'metrics': [
            'deleteCongestion',
            'iopsDevRead',
            'iopsDevWrite',
            'iopsRead',
            'iopsWrite',
            'latencyDevDAvg',
            'latencyDevGAvg',
            'latencyDevRead',
            'latencyDevWrite',
            'latencyRead',
            'latencyWrite',
            'throughputDevRead',
            'throughputDevWrite',
        ],
    },
    'cluster-resync': {
        'kind': 'VsanClusterResync',
        'label': 'vSAN Cluster Resync',
        'identity': ['cluster_uuid'],
        'objects_observed': 0,
        'metrics': [
            'iopsResyncReadDecom',
            'iopsResyncReadFixComp',
            'iopsResyncReadPolicy',
            'iopsResyncReadRebalance',
            'iopsResyncWriteDecom',
            'iopsResyncWriteFixComp',
            'iopsResyncWritePolicy',
            'iopsResyncWriteRebalance',
            'latResyncReadDecom',
            'latResyncReadFixComp',
            'latResyncReadPolicy',
            'latResyncReadRebalance',
            'latResyncWriteDecom',
            'latResyncWriteFixComp',
            'latResyncWritePolicy',
            'latResyncWriteRebalance',
            'tputResyncReadDecom',
            'tputResyncReadFixComp',
            'tputResyncReadPolicy',
            'tputResyncReadRebalance',
            'tputResyncWriteDecom',
            'tputResyncWriteFixComp',
            'tputResyncWritePolicy',
            'tputResyncWriteRebalance',
        ],
    },
    'disk-group': {
        'kind': 'VsanDiskGroup',
        'label': 'vSAN Disk Group (OSA)',
        'identity': ['disk_uuid'],
        'objects_observed': 0,
        'metrics': [
            'componentCongestionReadSched',
            'componentCongestionWriteSched',
            'diskgroupCongestionReadSched',
            'diskgroupCongestionWriteSched',
            'iopsDelayPctSched',
            'iopsDirectSched',
            'iopsResyncRead',
            'iopsResyncReadDecom',
            'iopsResyncReadFixComp',
            'iopsResyncReadPolicy',
            'iopsResyncReadRebalance',
            'iopsResyncWrite',
            'iopsResyncWriteDecom',
            'iopsResyncWriteFixComp',
            'iopsResyncWritePolicy',
            'iopsResyncWriteRebalance',
            'latResyncRead',
            'latResyncReadDecom',
            'latResyncReadFixComp',
            'latResyncReadPolicy',
            'latResyncReadRebalance',
            'latResyncWrite',
            'latResyncWriteDecom',
            'latResyncWriteFixComp',
            'latResyncWritePolicy',
            'latResyncWriteRebalance',
            'latencySched',
            'outstandingBytesSched',
            'tputResyncRead',
            'tputResyncReadDecom',
            'tputResyncReadFixComp',
            'tputResyncReadPolicy',
            'tputResyncReadRebalance',
            'tputResyncWrite',
            'tputResyncWriteDecom',
            'tputResyncWriteFixComp',
            'tputResyncWritePolicy',
            'tputResyncWriteRebalance',
        ],
    },
    'lsom-world-cpu': {
        'kind': 'VsanLsomWorldCpu',
        'label': 'vSAN LSOM World CPU',
        'identity': ['host_uuid', 'world_name', 'world_id'],
        'objects_observed': 0,
        'metrics': [
            'readyPct',
            'usedPct',
        ],
    },
}
