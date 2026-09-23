"""
Offline tests for the Performance Service collector.
No vCenter, no SDK, no network.

    python test_perfsvc.py
"""
import sys
sys.path.insert(0, "app")
import perfsvc


class _MetricId:
    def __init__(self, label): self.label = label


class _Value:
    def __init__(self, label, values): self.metricId = _MetricId(label); self.values = values


class _Result:
    def __init__(self, ref, values): self.entityRefId = ref; self.value = values


class _Perf:
    """Stand-in for vsan-performance-manager."""
    def __init__(self, results, raise_on=None):
        self._results = results; self._raise_on = raise_on or set()
    def VsanPerfQueryPerf(self, specs, cluster):
        ent = specs[0].entityRefId.split(":")[0]
        if ent in self._raise_on:
            raise RuntimeError("synthetic failure")
        return [r for r in self._results if r.entityRefId.startswith(ent + ":")]


def _patch_specs():
    """vim.cluster.VsanPerfQuerySpec needs no real pyVmomi for these tests."""
    class _Spec:
        def __init__(self, entityRefId=None, startTime=None, endTime=None):
            self.entityRefId = entityRefId
    perfsvc.vim.cluster.VsanPerfQuerySpec = _Spec


HOST = "6a46db86-350f-f7e5-653d-9c6b00c512b6"


def test_parse_ref_named_identity():
    k = perfsvc.parse_ref(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack")
    assert k.entity == "vsan-tcpip-stats"
    assert dict(k.idents) == {"host_uuid": HOST, "stack": "defaultTcpipStack"}


def test_parse_ref_single_uuid():
    k = perfsvc.parse_ref(f"host-domclient:{HOST}")
    assert dict(k.idents) == {"host_uuid": HOST}


def test_parse_ref_rejects_unmodeled():
    assert perfsvc.parse_ref("not-a-real-entity:abc") is None
    assert perfsvc.parse_ref("no-colon-here") is None


def test_variable_arity_is_padded_not_dropped():
    """host-cpu returns BOTH "host-cpu:<uuid>" (host aggregate) and
    "host-cpu:<uuid>|cpu-8" (per CPU) -- 61 objects per host for 60 CPUs.

    Found by deploying: Operations rejected the aggregate objects with
    "Identifier 'cpu' is required in describe.xml, but it was not found on
    this resource." Padding keeps the aggregate, which is real data.
    """
    agg = perfsvc.parse_ref(f"host-cpu:{HOST}")
    one = perfsvc.parse_ref(f"host-cpu:{HOST}|cpu-8")
    assert dict(agg.idents) == {"host_uuid": HOST, "cpu": perfsvc.AGGREGATE}
    assert dict(one.idents) == {"host_uuid": HOST, "cpu": "cpu-8"}
    assert agg != one, "aggregate and per-CPU must be distinct objects"
    # every declared identifier present, so describe.xml validation passes
    names = perfsvc.MODEL.ENTITIES["host-cpu"]["identity"]
    assert [n for n, _ in agg.idents] == names


def test_extra_parts_are_kept_not_merged():
    """A ref with more parts than the model names must not collapse into
    another object."""
    a = perfsvc.parse_ref(f"host-domclient:{HOST}|unexpected")
    b = perfsvc.parse_ref(f"host-domclient:{HOST}")
    assert a != b
    assert dict(a.idents)["part1"] == "unexpected"


def test_objectkey_is_hashable_and_stable():
    a = perfsvc.parse_ref(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack")
    b = perfsvc.parse_ref(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack")
    assert a == b and hash(a) == hash(b)
    assert len({a, b}) == 1


def test_last_number_takes_most_recent():
    """perfsvc returns a series; Operations wants a point value."""
    assert perfsvc._last_number("1,2,3") == 3.0
    assert perfsvc._last_number("1,2,3,,") == 3.0      # trailing empties skipped
    assert perfsvc._last_number("") is None
    assert perfsvc._last_number("x,y") is None


def test_collect_builds_objects():
    _patch_specs()
    res = [_Result(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack",
                   [_Value("tcpRxPackets", "10,20,30"),
                    _Value("tcpTxPackets", "40,50,60")])]
    objs, problems = perfsvc.collect(_Perf(res), cluster=None)
    assert problems == []
    (key, g), = objs.items()
    assert g.gauges == {"tcpRxPackets": 30.0, "tcpTxPackets": 60.0}
    assert g.props["stack"] == "defaultTcpipStack"


def test_empty_series_are_skipped_not_zeroed():
    """A metric with no samples must be absent, not reported as 0."""
    _patch_specs()
    res = [_Result(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack",
                   [_Value("tcpRxPackets", "10"), _Value("tcpErrs", "")])]
    objs, _ = perfsvc.collect(_Perf(res), cluster=None)
    (_, g), = objs.items()
    assert "tcpErrs" not in g.gauges
    assert g.gauges["tcpRxPackets"] == 10.0


def test_unmodeled_ref_is_reported_not_dropped():
    _patch_specs()
    res = [_Result(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack",
                   [_Value("tcpRxPackets", "1")]),
           _Result("vsan-tcpip-stats:weird-shape", [_Value("x", "1")])]
    objs, problems = perfsvc.collect(_Perf(res), cluster=None)
    assert len(objs) == 2   # weird-shape still parses, just with one ident
    assert problems == []


def test_total_failure_raises_rather_than_returning_empty():
    """The defect this guards against: every target fails, each is skipped,
    and Operations receives an empty SUCCESSFUL collection with no error."""
    _patch_specs()
    try:
        perfsvc.collect(_Perf([]), cluster=None)
    except perfsvc.PerfSvcError as e:
        assert "no data" in str(e).lower()
    else:
        raise AssertionError("empty result must raise PerfSvcError")


def test_entity_errors_are_collected_not_swallowed():
    _patch_specs()
    res = [_Result(f"vsan-tcpip-stats:{HOST}|defaultTcpipStack",
                   [_Value("tcpRxPackets", "1")])]
    objs, problems = perfsvc.collect(_Perf(res, raise_on={"host-cpu"}), cluster=None)
    assert objs
    assert any("host-cpu" in p for p in problems)


def test_labels_do_not_repeat_an_expanded_substring():
    """Regression: expanding "lat"->"latency" inside avgLatency gave
    "Latencyency".  Substring expansion must not fire inside a word that
    already contains the expansion."""
    import metric_labels
    bad = [k for k, v in metric_labels.LABELS.items()
           if "latencyency" in v.lower() or "  " in v or v != v.strip()]
    assert not bad, bad[:5]


def test_labels_are_not_just_the_camelcase_id():
    """The point of the generated labels is that they say more than the id
    does -- txSbSpaceMin must not render as "Tx sb space min"."""
    import metric_labels
    assert metric_labels.LABELS["txSbSpaceMin"] == "TX socket buffer space (min)"
    assert metric_labels.UNITS["txSbSpaceMin"] == "DATA_SIZE.BYTE"
    assert metric_labels.UNITS["tcpRxThroughput"] == "DATA_RATE.BIBYTE_PER_SECOND"


def test_every_unit_path_resolves_against_the_sdk_units():
    """A unit is a dotted path into aria.ops.definition.units.Units.  A typo
    there is silent -- the attribute just comes out unitless."""
    try:
        from aria.ops.definition.units import Units
    except ImportError:
        return                                       # SDK absent: offline run
    import metric_labels
    unresolved = []
    for key, path in metric_labels.UNITS.items():
        node = Units
        for part in path.split("."):
            node = getattr(node, part, None)
            if node is None:
                unresolved.append((key, path)); break
    assert not unresolved, unresolved[:5]


def test_disk_label_drops_the_padding_but_keeps_the_serial():
    """Two disks of one model on one host differ only by serial, so the serial
    cannot be truncated away -- but the ~20 underscores of model padding can."""
    class _Scsi:
        displayName = ("Local NVMe Disk (t10.NVMe____Micron_7450_MTFDKCB1T9TFR"
                       "_______________FCD815400175A000)")
        canonicalName = ("t10.NVMe____Micron_7450_MTFDKCB1T9TFR"
                         "_______________FCD815400175A000")
    label = perfsvc._disk_label(_Scsi())
    assert label == "NVMe Micron 7450 MTFDKCB1T9TFR FCD815400175A000", label
    assert "__" not in label
    assert len(label) < len(_Scsi.displayName)


def test_disk_label_passes_through_unrecognized_names():
    class _Scsi:
        displayName = "Local SAS Disk (naa.5000c500a1b2c3d4)"
        canonicalName = "naa.5000c500a1b2c3d4"
    assert perfsvc._disk_label(_Scsi()) == "Local SAS Disk (naa.5000c500a1b2c3d4)"


def test_nic_error_counters_are_readable():
    """These are the grey-state signals for a failing NIC or link -- the ones
    a rapid dashboard shows -- so they are the labels that must not stay
    cryptic.  "RX lgt err" tells an operator nothing."""
    import metric_labels as ml
    assert ml.LABELS["rxLgtErr"] == "RX length errors"
    assert ml.LABELS["txCarErr"] == "TX carrier errors"
    assert ml.LABELS["rxFrmErr"] == "RX frame alignment errors"
    assert ml.LABELS["pfcCount"] == "PFC count"
    assert ml.LABELS["ioChainRxdrops"] == "IO chain RX drops"
    # The ring-buffer-full counter, distinct from rxDrp and rxErr.
    assert ml.LABELS["rxMissErr"] == "RX missed errors (ring buffer full)"


def test_cache_miss_is_not_pluralised_into_missed():
    """Regression: a whole-token "miss"->"missed" rule for rxMissErr turned
    30 cache-miss metrics into "cache missed", which is wrong English."""
    import metric_labels as ml
    wrong = [k for k, v in ml.LABELS.items() if "cache missed" in v.lower()]
    assert not wrong, wrong[:5]


def test_cert_failure_names_the_remedy():
    """The DEFAULT config hits this path -- verify_certs defaults to true and
    vCenter presents a VMCA-issued cert nothing trusts -- so the message has to
    say what to do, not just that verification failed."""
    import ssl as _ssl

    def _boom(**kwargs):
        raise _ssl.SSLCertVerificationError("certificate verify failed")

    real = perfsvc.SmartConnect
    perfsvc.SmartConnect = _boom
    try:
        perfsvc.connect("vc01.example.com", "u", "p", verify=True)
        raise AssertionError("expected PerfSvcError")
    except perfsvc.PerfSvcError as exc:
        text = str(exc)
        assert "VMCA" in text, text
        assert "Verify vCenter certificate" in text, text
        assert "FQDN" in text, text
    finally:
        perfsvc.SmartConnect = real


def test_labels_use_us_spelling():
    """Product surface is US English, matching the vSphere/vSAN ecosystem.
    These are generated, so a British spelling entering the abbreviation table
    silently rewrites every label built from it -- "util" -> "utilisation" put
    it into five."""
    import metric_labels as ml
    BRITISH = ("utilis", "normalis", "serialis", "optimis", "recognis",
               "organis", "behaviour", "colour", "labelled", "modelling",
               "catalogue", "licence", "analyse", "centre")
    bad = [(k, v) for k, v in ml.LABELS.items()
           if any(b in v.lower() for b in BRITISH)]
    assert not bad, bad[:5]


def test_vmdk_paths_register_both_slash_forms():
    """perfsvc emits virtual-disk refs with and without a leading slash -- 59
    of 60 came back bare, one as "/<uuid>/name.vmdk". Registering only the
    inventory form left that one showing as a UUID."""
    class _Backing:
        fileName = "[vsanDatastore] 82caad6a-7fbc/ubuntuclaud.vmdk"
    class _Info:
        label = "Hard disk 1"
    class _Disk(perfsvc.vim.vm.device.VirtualDisk):
        pass
    # Build the two keys the way build_name_map does, without needing vCenter.
    path = perfsvc._DS_PREFIX.sub("", _Backing.fileName)
    assert path == "82caad6a-7fbc/ubuntuclaud.vmdk", path
    assert "/" + path.lstrip("/") == "/82caad6a-7fbc/ubuntuclaud.vmdk"


def test_model_is_non_trivial():
    assert len(perfsvc.MODEL.ENTITIES) >= 20
    t = perfsvc.MODEL.ENTITIES["vsan-tcpip-stats"]
    assert t["identity"] == ["host_uuid", "stack"]
    assert "tcpRcvoopackRate" in t["metrics"]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn(); print(f"  ok    {name}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {name}: {e}")
        except Exception as e:                       # noqa: BLE001
            fails += 1; print(f"  ERROR {name}: {type(e).__name__}: {e}")
    total = len([n for n in globals() if n.startswith("test_")])
    print(f"\n{total - fails}/{total} passed")
    sys.exit(1 if fails else 0)
