"""
Offline tests for the parser, model grouping and rate cache.
No SDK, no network, no host.

    python -m pytest test_vsanmetrics.py -v
      or
    python test_vsanmetrics.py

Run these before you ever touch mp-test.  If the rate math is wrong here it
will be wrong in Operations, and it is far cheaper to find out now.

A NOTE ON FIXTURES.  The previous suite passed 8/8 while the adapter was
silently discarding half the TCP traffic, because no fixture ever contained two
samples of one metric differing only by a label.  The code and the test data
shared a blind spot.  Fixtures here carry io_type, and
test_io_type_does_not_collide exists specifically to fail if that regresses.
"""
import os
import shutil
import sys
import tempfile
sys.path.insert(0, "app")

import vsanmetrics as vm

HOST_UUID = "6a46db86-350f-f7e5-653d-9c6b00c512b6"
BASE = (
    f'host_uuid="{HOST_UUID}",'
    'stack="defaultTcpipStack",'
    'hostname="esxi01.example.com",'
    'vsan_cluster_uuid="5deb636e-91b5-11f1-aef5-000c296fd50e",'
    'sink_type="cold"'
)
SAMPLE_FILE = os.path.join("docs", "sample-exposition-esxi01.txt")


def snapshot(rx=1000, tx=1200, ooo=1, rexmit=5, dupack=20,
             rx_bytes=10_000, tx_bytes=12_000):
    """A realistic tcppkt snapshot: the two io_type metrics really are split."""
    return "\n".join([
        "# HELP vmware_esx_tcppkt_total Total Packets processed by ESX TCP since boot.",
        f'vmware_esx_tcppkt_total{{{BASE},io_type="rx"}} {rx}.000000',
        f'vmware_esx_tcppkt_total{{{BASE},io_type="tx"}} {tx}.000000',
        f'vmware_esx_tcppkt_bytes_total{{{BASE},io_type="rx"}} {rx_bytes}.000000',
        f'vmware_esx_tcppkt_bytes_total{{{BASE},io_type="tx"}} {tx_bytes}.000000',
        f'vmware_esx_tcppkt_rcvoopack_total{{{BASE}}} {ooo}.000000',
        f'vmware_esx_tcppkt_sndrexmitpack_total{{{BASE}}} {rexmit}.000000',
        f'vmware_esx_tcppkt_rcvdupack_total{{{BASE}}} {dupack}.000000',
        '# a comment, and a metric from another family',
        f'vmware_esx_rdt_latency_us{{{BASE},name="rdt0"}} 42.000000',
    ])


def parsed(text):
    return list(vm.parse(text, keep=vm.ALL_NAMES))


def tcp_object(objs):
    for k in objs:
        if k.family == "vmware_esx_tcppkt":
            return k, objs[k]
    raise AssertionError("no tcppkt object produced")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_parse_keeps_known_metrics_and_labels():
    samples = parsed(snapshot())
    assert len(samples) == 8, samples          # 7 tcppkt + 1 rdt
    s = [x for x in samples if x.name == "vmware_esx_tcppkt_total"]
    assert len(s) == 2                          # rx and tx both survive parsing
    assert {x.label("io_type") for x in s} == {"rx", "tx"}
    assert s[0].label("host_uuid") == HOST_UUID


def test_parse_skips_comments_and_unknown_names():
    text = snapshot() + '\nvmware_totally_made_up_metric{a="b"} 1.0'
    assert all(x.name != "vmware_totally_made_up_metric" for x in parsed(text))


# ---------------------------------------------------------------------------
# Grouping -- the io_type regression the old suite could not catch
# ---------------------------------------------------------------------------
def test_io_type_does_not_collide():
    """rx and tx must become two metrics, not one overwriting the other.

    This is the defect that shipped: collect() keyed metrics by name alone, so
    the tx sample overwrote the rx sample and the adapter reported transmit
    traffic only -- while the percentages divided receive-side events by it.
    """
    objs, unknown = vm.group(parsed(snapshot(rx=1000, tx=1200)))
    assert unknown == [], unknown
    _key, g = tcp_object(objs)
    assert g.counters["total|rx"] == 1000.0
    assert g.counters["total|tx"] == 1200.0
    assert "total" not in g.counters             # the old, ambiguous key is gone


def test_group_places_every_sample():
    samples = parsed(snapshot())
    objs, unknown = vm.group(samples)
    placed = sum(len(g.counters) + len(g.gauges) for g in objs.values())
    assert unknown == []
    assert placed == len(samples), (placed, len(samples))


def test_unknown_label_value_is_reported_not_dropped():
    """A new io_type value must surface, not vanish.

    An ESXi upgrade adding a label value is the exact shape of the original
    bug.  Silence is the failure mode we are guarding against.
    """
    text = snapshot() + f'\nvmware_esx_tcppkt_total{{{BASE},io_type="loopback"}} 7.0'
    objs, unknown = vm.group(parsed(text))
    assert len(unknown) == 1, unknown
    assert "loopback" in unknown[0] or "unknown combination" in unknown[0]
    _key, g = tcp_object(objs)
    assert g.counters["total|rx"] == 1000.0      # the known ones still work


def test_identity_splits_objects_not_metrics():
    """Two stacks are two objects; rx/tx are two metrics on one object."""
    other = BASE.replace('stack="defaultTcpipStack"', 'stack="vmotionStack"')
    text = snapshot() + (
        f'\nvmware_esx_tcppkt_total{{{other},io_type="rx"}} 500.0'
        f'\nvmware_esx_tcppkt_total{{{other},io_type="tx"}} 600.0')
    objs, unknown = vm.group(parsed(text))
    assert unknown == []
    tcp = [k for k in objs if k.family == "vmware_esx_tcppkt"]
    assert len(tcp) == 2, tcp                    # split by stack
    for k in tcp:
        assert {"total|rx", "total|tx"} <= set(objs[k].counters)


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------
def test_first_interval_emits_nothing():
    objs, _ = vm.group(parsed(snapshot()))
    rates, _ = vm.RateCache().rates_for_objects("esxi01", objs, now=0.0)
    assert rates == {}


def test_second_interval_gives_rates():
    c = vm.RateCache()
    o1, _ = vm.group(parsed(snapshot(rx=1000, tx=1200)))
    c.rates_for_objects("esxi01", o1, now=0.0)
    o2, _ = vm.group(parsed(snapshot(rx=1300, tx=1800)))
    rates, _ = c.rates_for_objects("esxi01", o2, now=300.0)
    key, _g = tcp_object(o2)
    assert rates[key]["total|rx"] == (1300 - 1000) / 300.0
    assert rates[key]["total|tx"] == (1800 - 1200) / 300.0


def test_gauges_need_no_baseline():
    """Gauges are point-in-time, so objects appear on the first collection."""
    objs, _ = vm.group(parsed(snapshot()))
    rdt = [k for k in objs if k.family == "vmware_esx_rdt"]
    assert rdt, "expected an rdt object"
    assert objs[rdt[0]].gauges.get("latency_us") == 42.0
    assert objs[rdt[0]].counters == {}


def test_reboot_discards_whole_host():
    c = vm.RateCache()
    o1, _ = vm.group(parsed(snapshot(rx=10_000, tx=12_000, ooo=50,
                                     rexmit=50, dupack=50)))
    c.rates_for_objects("esxi01", o1, now=0.0)
    o2, _ = vm.group(parsed(snapshot(rx=5, tx=6, ooo=0, rexmit=0, dupack=0)))
    rates, resets = c.rates_for_objects("esxi01", o2, now=300.0)
    assert resets > 0
    assert rates == {}


def test_hosts_do_not_collide():
    c = vm.RateCache()
    o, _ = vm.group(parsed(snapshot()))
    c.rates_for_objects("esxi01", o, now=0.0)
    rates, _ = c.rates_for_objects("esxi02", o, now=300.0)
    assert rates == {}, "esxi02 must not inherit esxi01's baseline"


# ---------------------------------------------------------------------------
# Derived percentages -- direction of the denominator
# ---------------------------------------------------------------------------
def test_percentages_use_matching_direction():
    """Receive-side numerators over received packets, transmit over transmit.

    The shipped version divided everything by a denominator that, thanks to
    the collision, held the tx value -- so three of the four were a ratio of
    two unrelated quantities.
    """
    rates = {"total|rx": 1000.0, "total|tx": 2000.0,
             "rcvoopack_total": 10.0, "rcvdupack_total": 20.0,
             "rcvduppack_total": 5.0, "sndrexmitpack_total": 40.0}
    pct = vm.derive_percentages(rates)
    assert pct["outOfOrderPct"] == 1.0            # 10 / 1000 rx
    assert pct["duplicateAckPct"] == 2.0          # 20 / 1000 rx
    assert pct["duplicatePacketPct"] == 0.5       # 5  / 1000 rx
    assert pct["retransmitPct"] == 2.0            # 40 / 2000 tx  <- tx numerator


def test_zero_denominator_is_safe():
    assert vm.derive_percentages({"total|rx": 0.0, "rcvoopack_total": 5.0}) == {}
    assert vm.derive_percentages({}) == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_baseline_survives_a_fresh_process():
    """commands.cfg runs a new interpreter per collection.

    An in-memory baseline is therefore always empty and no rate would ever be
    emitted -- the defect in REPORT.md section 3b.
    """
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "cache.json")
        o1, _ = vm.group(parsed(snapshot(rx=1000, tx=1200)))
        vm.RateCache(path=p).rates_for_objects("esxi01", o1, now=0.0)
        assert os.path.exists(p)

        o2, _ = vm.group(parsed(snapshot(rx=1300, tx=1800)))
        rates, _ = vm.RateCache(path=p).rates_for_objects("esxi01", o2, now=300.0)
        key, _ = tcp_object(o2)
        assert rates[key]["total|rx"] == 1.0
    finally:
        shutil.rmtree(d)


def test_corrupt_cache_costs_one_interval_not_a_crash():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "cache.json")
        with open(p, "w") as fh:
            fh.write("{not json at all")
        o, _ = vm.group(parsed(snapshot()))
        rates, _ = vm.RateCache(path=p).rates_for_objects("esxi01", o, now=0.0)
        assert rates == {}
    finally:
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Real data
# ---------------------------------------------------------------------------
def test_real_exposition_round_trips_with_nothing_dropped():
    """Every sample in a real scrape must land somewhere.

    Synthetic fixtures only prove the code handles what we imagined.  This
    proves it handles what the host actually sent.
    """
    if not os.path.exists(SAMPLE_FILE):
        return                                    # sample not present; skip
    samples = parsed(open(SAMPLE_FILE).read())
    objs, unknown = vm.group(samples)
    placed = sum(len(g.counters) + len(g.gauges) for g in objs.values())
    assert unknown == [], unknown[:5]
    assert placed == len(samples), (placed, len(samples))
    assert len(objs) > 400, len(objs)
    assert len({k.family for k in objs}) == len(vm.MODEL.FAMILIES)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:                    # noqa: BLE001
            fails += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    total = len([n for n in globals() if n.startswith("test_")])
    print(f"\n{total - fails}/{total} passed")
    sys.exit(1 if fails else 0)
