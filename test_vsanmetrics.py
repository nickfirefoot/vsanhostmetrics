"""
Offline tests for the parser and rate cache.  No SDK, no network, no host.

    python -m pytest test_vsanmetrics.py -v
      or
    python test_vsanmetrics.py

Run these before you ever touch mp-test.  If the rate math is wrong here it
will be wrong in Operations, and it is far cheaper to find out now.
"""
import sys
sys.path.insert(0, "app")

import vsanmetrics as vm

LABELS = (
    'host_uuid="6a46db86-350f-f7e5-653d-9c6b00c512b6",'
    'stack="defaultTcpipStack",'
    'hostname="esxi01.example.com",'
    'vsan_cluster_uuid="5deb636e-91b5-11f1-aef5-000c296fd50e",'
    'sink_type="cold"'
)


def snapshot(total, ooo, rexmit, dupack):
    return "\n".join([
        "# HELP vmware_esx_tcppkt_total Total Packets processed by ESX TCP since boot.",
        f'vmware_esx_tcppkt_total{{{LABELS}}} {total}.000000',
        f'vmware_esx_tcppkt_rcvoopack_total{{{LABELS}}} {ooo}.000000',
        f'vmware_esx_tcppkt_sndrexmitpack_total{{{LABELS}}} {rexmit}.000000',
        f'vmware_esx_tcppkt_rcvdupack_total{{{LABELS}}} {dupack}.000000',
        '# a comment, and an unrelated metric that must be filtered out',
        f'vmware_vsan_dom_iops_read{{{LABELS}}} 1234.000000',
    ])


def test_parse_filters_and_labels():
    samples = list(vm.parse(snapshot(1000, 1, 5, 20), keep=vm.TCP_COUNTERS))
    names = {s.name for s in samples}
    assert "vmware_vsan_dom_iops_read" not in names
    assert len(samples) == 4
    s = next(s for s in samples if s.name == "vmware_esx_tcppkt_total")
    assert s.value == 1000.0
    assert s.label("hostname") == "esxi01.example.com"
    assert s.label("stack") == "defaultTcpipStack"


def test_first_interval_emits_nothing():
    c = vm.RateCache()
    rates, resets = c.rates("esxi01", list(vm.parse(snapshot(1000, 1, 5, 20),
                                                    keep=vm.TCP_COUNTERS)), now=0.0)
    assert rates == {} and resets == 0


def test_second_interval_gives_rates():
    c = vm.RateCache()
    c.rates("esxi01", list(vm.parse(snapshot(1000, 1, 5, 20),
                                    keep=vm.TCP_COUNTERS)), now=0.0)
    rates, resets = c.rates("esxi01", list(vm.parse(snapshot(4000, 4, 15, 80),
                                                    keep=vm.TCP_COUNTERS)), now=300.0)
    assert resets == 0
    by = {vm.TCP_COUNTERS[k[1]]: v for k, v in rates.items()}
    assert by["tcpPacketsTotal"] == (4000 - 1000) / 300.0   # 10.0/s
    assert by["rcvOutOfOrderPackets"] == 3 / 300.0          # 0.01/s

    pct = vm.derive_percentages(by)
    assert abs(pct["outOfOrderPct"] - 0.1) < 1e-9           # 3/3000 = 0.1%
    assert abs(pct["retransmitPct"] - (10 / 3000 * 100)) < 1e-9


def test_reboot_discards_whole_host():
    c = vm.RateCache()
    c.rates("esxi01", list(vm.parse(snapshot(9000, 40, 90, 400),
                                    keep=vm.TCP_COUNTERS)), now=0.0)
    # every counter back to near zero: reboot
    rates, resets = c.rates("esxi01", list(vm.parse(snapshot(50, 0, 0, 2),
                                                    keep=vm.TCP_COUNTERS)), now=300.0)
    assert resets >= 3
    assert rates == {}, "a reboot must not emit rates for any counter"
    # and the new baseline is in place, so the next interval works
    rates, resets = c.rates("esxi01", list(vm.parse(snapshot(3050, 3, 10, 62),
                                                    keep=vm.TCP_COUNTERS)), now=600.0)
    assert resets == 0 and rates


def test_hosts_do_not_collide():
    c = vm.RateCache()
    snap = list(vm.parse(snapshot(1000, 1, 5, 20), keep=vm.TCP_COUNTERS))
    c.rates("esxi01", snap, now=0.0)
    # esxi02's first observation, despite identical label text
    rates, _ = c.rates("esxi02", snap, now=0.0)
    assert rates == {}, "scope must namespace the cache per host"


def test_zero_denominator_is_safe():
    assert vm.derive_percentages({"rcvOutOfOrderPackets": 1.0}) == {}
    assert vm.derive_percentages({"tcpPacketsTotal": 0.0,
                                  "rcvOutOfOrderPackets": 1.0}) == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
