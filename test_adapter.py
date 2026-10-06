"""Tests for the vCenter-parent resolution path.

Two defects shipped here in a row, both invisible to the existing suites:
the suite-api client was used without a `with`, so every request was
unauthenticated; and the identifier filter it relied on does not exist, so a
request that DID authenticate answered with the whole resource kind. The
second was hidden by the first for three releases.

Run: python3 test_adapter.py
"""
import sys

# AdapterInstance.from_input defaults to sys.argv[-2], evaluated at class
# definition time, so importing the adapter needs two argv entries.
if len(sys.argv) < 3:
    sys.argv = sys.argv + ["_", "_"]

sys.path.insert(0, "app")
import adapter                                            # noqa: E402
from aria.ops.object import Identifier, Key               # noqa: E402


class _Client:
    """Stands in for SuiteApiClient, counting calls and paging like it does."""

    def __init__(self, by_kind, page=None):
        self.by_kind = by_kind
        self.page = page or adapter._PAGE
        self.calls = []

    def paged_get(self, url, key, **kwargs):
        params = kwargs.get("params", {})
        self.calls.append((url, params.get("resourceKind"), params.get("page")))
        items = self.by_kind.get(params.get("resourceKind"), [])
        start = params.get("page", 0) * self.page
        return {"resourceList": items[start:start + self.page]}


def _res(rid, name, moid, vcid, extra_non_unique=True):
    ids = [{"identifierType": {"name": "VMEntityObjectID",
                               "isPartOfUniqueness": "true"}, "value": moid},
           {"identifierType": {"name": "VMEntityVCID",
                               "isPartOfUniqueness": "true"}, "value": vcid}]
    if extra_non_unique:
        # Operations carries informational identifiers too; they must NOT
        # participate in matching or nothing ever resolves.
        ids.append({"identifierType": {"name": "VMEntityName",
                                       "isPartOfUniqueness": "false"},
                    "value": name})
    return {"identifier": rid, "resourceKey": {"name": name,
                                               "resourceIdentifiers": ids}}


VCID = "a6283d65-9225-4782-a612-35deb597a5a3"
HOSTS = [_res(f"rid-{i}", f"esxi0{i}.lab", f"host-{20+i}", VCID)
         for i in range(1, 5)]


def test_index_keys_on_uniqueness_identifiers_only():
    c = _Client({"HostSystem": HOSTS})
    ix = adapter._resource_index(c, "VMWARE", "HostSystem")
    assert len(ix) == 4, ix
    want = adapter._uniqueness_key({"VMEntityObjectID": "host-23",
                                    "VMEntityVCID": VCID})
    assert ix.get(want) == "rid-3", "informational identifiers broke matching"


def test_a_vc_parent_shaped_key_resolves():
    """The key the adapter builds must match the key the index builds."""
    c = _Client({"HostSystem": HOSTS})
    ix = adapter._resource_index(c, "VMWARE", "HostSystem")
    k = Key(adapter_kind="VMWARE", object_kind="HostSystem", name="esxi02.lab",
            identifiers=[Identifier("VMEntityObjectID", "host-22"),
                         Identifier("VMEntityVCID", VCID)])
    want = adapter._uniqueness_key({n: i.value for n, i in k.identifiers.items()})
    assert ix.get(want) == "rid-2", "the two key shapes disagree"


def test_wrong_vcenter_does_not_match():
    """Two adapters on different vCenters must not cross-attach."""
    c = _Client({"HostSystem": HOSTS})
    ix = adapter._resource_index(c, "VMWARE", "HostSystem")
    want = adapter._uniqueness_key({"VMEntityObjectID": "host-22",
                                    "VMEntityVCID": "a-different-vcenter"})
    assert ix.get(want) is None


def test_index_pages_through_everything():
    many = [_res(f"r{i}", f"vm{i}", f"vm-{i}", VCID) for i in range(2500)]
    c = _Client({"VirtualMachine": many}, page=adapter._PAGE)
    ix = adapter._resource_index(c, "VMWARE", "VirtualMachine")
    assert len(ix) == 2500, f"paging lost objects: {len(ix)}"
    assert len(c.calls) == 3, f"expected 3 pages, made {len(c.calls)}"


def test_one_call_per_kind_not_per_parent():
    """The whole point: 35 parents must not mean 35 queries."""
    c = _Client({"HostSystem": HOSTS})
    adapter._resource_index(c, "VMWARE", "HostSystem")
    assert len(c.calls) == 1, c.calls


def test_a_failing_list_returns_empty_not_garbage():
    class _Broken:
        def paged_get(self, *a, **k):
            raise RuntimeError("suite-api down")
    assert adapter._resource_index(_Broken(), "VMWARE", "HostSystem") == {}


def test_objects_without_uniqueness_identifiers_are_skipped():
    bad = [{"identifier": "x", "resourceKey": {"name": "n",
            "resourceIdentifiers": [{"identifierType": {
                "name": "VMEntityName", "isPartOfUniqueness": "false"},
                "value": "n"}]}}]
    c = _Client({"HostSystem": bad})
    assert adapter._resource_index(c, "VMWARE", "HostSystem") == {}


if __name__ == "__main__":
    fails = 0
    names = [n for n in globals() if n.startswith("test_")]
    for name in sorted(names):
        try:
            globals()[name](); print(f"  ok    {name}")
        except AssertionError as e:
            fails += 1; print(f"  FAIL  {name}: {e}")
        except Exception as e:                   # noqa: BLE001
            fails += 1; print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(names) - fails}/{len(names)} passed")
    sys.exit(1 if fails else 0)
