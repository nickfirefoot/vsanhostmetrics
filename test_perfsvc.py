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


def test_parse_ref_rejects_unmodelled():
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


def test_unmodelled_ref_is_reported_not_dropped():
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
