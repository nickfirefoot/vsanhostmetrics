"""Tests for the vCenter-parent resolution path.

Two defects shipped here in a row, both invisible to the existing suites:
the suite-api client was used without a `with`, so every request was
unauthenticated; and the identifier filter it relied on does not exist, so a
request that DID authenticate answered with the whole resource kind. The
second was hidden by the first for three releases.

Run: python3 test_adapter.py
"""
import sys
from unittest.mock import patch

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


def test_vcenter_attach_has_a_working_kill_switch():
    """CLAUDE.md rule 1, as it stands after 2026-10-22.

    Asserting children on an object another adapter owns REPLACES that
    object's whole child list. It did: 26 of 28 VMs lost their HostSystem
    parent on 2026-10-21.

    The default is now "true", which the operator authorised explicitly,
    because every dashboard resolves its views by descendant from a vCenter
    cluster and with attach off they all render nothing -- measured against
    the lab, not assumed. This test therefore no longer pins the DEFAULT. It
    pins the two things that still protect the inventory:

      * the switch exists at all, so there is always a way to stop the
        writing without a reinstall, and
      * the gate is wired, so "false" actually prevents BOTH the attach and
        the read-modify-write child merge.

    If the switch is ever removed, rule 1 has no off position and this fails.
    """
    import re, pathlib
    src = pathlib.Path("app/adapter.py").read_text(encoding="utf-8")
    m = re.search(r"VC_ATTACH_PARAM,\s*\n\s*values=\[([^\]]+)\],"
                  r"\s*\n\s*default=\"([^\"]+)\"", src)
    assert m, "the vCenter attach parameter is gone -- rule 1 has no switch"
    assert "false" in m.group(1), "'false' is no longer selectable"
    assert m.group(2) in ("true", "false"), m.group(2)
    assert "if not attach_vc:" in src, "the attach is no longer gated"
    assert "if attach_vc else []" in src, \
        "the child-merge still runs when not attaching, which reads and " \
        "re-asserts foreign child lists"


def test_committed_manifest_matches_the_last_released_tag():
    """manifest.txt tracks the last RELEASE, not the last tag.

    CI overwrites the version from the git tag before mp-build, so a published
    pak is always labelled by its tag. The committed value only matters for a
    HAND build, which would otherwise emit a pak labelled with a stale version
    from current source -- two places disagreeing by discipline, which the
    netstats session had bite them for real in an INSTALL.md.

    The rule is in a workflow comment, so encode it here: the committed version
    equals the highest non-prerelease tag. Prereleases (vX.Y.Z-rc.N) do not
    advance it, which is why 1.4.6 is correct while rc tags carry 1.4.7.
    """
    import json
    import re
    import subprocess

    version = json.load(open("manifest.txt"))["version"]
    # CI runs these tests INSIDE the adapter image, which has no git binary and
    # no .git directory -- only /src is copied in. Skip loudly rather than
    # erroring, and say so, because a silent skip is the vacuous pass this
    # repository keeps relearning. Nothing is lost: the only failure this
    # guards is a HAND build mislabelling a pak, which happens on a developer
    # machine, and that has git.
    try:
        proc = subprocess.run(["git", "tag", "--list", "v*"],
                              capture_output=True, text=True)
    except FileNotFoundError:
        print("    (skipped: no git binary -- runs on a dev machine, "
              "not inside the adapter image)")
        return
    if proc.returncode != 0:
        print("    (skipped: not a git work tree)")
        return
    tags = proc.stdout.split()
    released = sorted(
        (tuple(int(p) for p in m.group(1).split(".")) for t in tags
         if (m := re.fullmatch(r"v(\d+\.\d+\.\d+)", t))))
    if not released:                       # shallow clone: nothing to compare
        return
    expected = ".".join(str(p) for p in released[-1])
    assert version == expected, (
        f"manifest.txt says {version}; last released tag is {expected}. "
        f"A hand build would mislabel the pak.")


def test_pack_description_counts_match_the_model():
    """The solution description is shown in Operations beside the pack name.
    It carried 69 kinds / 1636 metrics / 439 collected while the pack defined
    1595 and collected 451 -- and the configuration form said 253 of 1636. A
    count typed into prose is wrong the first time a view changes, so check it
    against the model."""
    import perfsvc
    import metric_scope
    ents = perfsvc.MODEL.ENTITIES
    defined = sum(len(perfsvc.metrics_for(e)) for e in ents)
    kind_to_ent = {sp["kind"]: e for e, sp in ents.items()}
    scoped = sum(len(set(m) & set(perfsvc.metrics_for(kind_to_ent[k])))
                 for k, m in metric_scope.COVERED.items() if k in kind_to_ent)
    desc = [l for l in open("resources/resources.properties").read().splitlines()
            if l.startswith("DESCRIPTION=")][0]
    assert f"{len(ents)} resource kinds" in desc, desc[:120]
    assert f"{defined} metrics" in desc, (defined, desc[:160])
    assert f"collects the {scoped} metrics" in desc, (scoped, desc[:260])
    readme = open("README.md").read()
    assert f"{defined:,} metrics across {len(ents)} resource kinds" in readme


def test_collect_reports_exception_and_disconnects():
    """A collect that raises must reach Operations as an error, not vanish.

    collect() had try/finally and no except, and main() ended in
    `finally: sys.exit(0)`, which replaces an in-flight exception: the process
    exited 0, wrote no result, and logged no traceback. Every PerfSvcError
    message this adapter composes was lost that way."""
    session = object()
    with patch.object(adapter, "_connect", return_value=(session, [object()], {})), \
         patch.object(adapter, "_safe_disconnect") as disconnect:
        result = adapter.collect(object())
    assert "KeyError" in result.get_json()["errorMessage"]
    disconnect.assert_called_once_with(session)


def test_collect_reports_a_login_failure_in_its_own_words():
    import perfsvc
    with patch.object(adapter, "_connect",
                      side_effect=perfsvc.PerfSvcError("vCenter login failed")):
        result = adapter.collect(object())
    assert "vCenter login failed" in result.get_json()["errorMessage"]


def test_main_does_not_mask_dispatch_failure():
    with patch.object(adapter.logging, "setup_logging"), \
         patch.object(adapter.logging, "rotate"), \
         patch.object(adapter.AdapterInstance, "from_input", side_effect=RuntimeError("dispatch failed")):
        try:
            adapter.main(["collect", "input", "output"])
        except RuntimeError as exc:
            assert str(exc) == "dispatch failed"
        else:
            raise AssertionError("dispatch failure was masked")


def test_main_unknown_method_exits_nonzero():
    with patch.object(adapter.logging, "setup_logging"), \
         patch.object(adapter.logging, "rotate"):
        try:
            adapter.main(["unknown", "input", "output"])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("unknown method did not fail")



class _Cert:
    def __init__(self, pem): self.pem = pem
    def get_certificate_string(self): return self.pem


class _Instance:
    """Stands in for AdapterInstance: identifiers, credential, certificates."""
    def __init__(self, idents, creds=None, certs=()):
        self.idents = idents; self.creds = creds or {}; self.certs = list(certs)
    def get_identifier_value(self, key, default=None):
        return self.idents.get(key, default)
    def get_credential_value(self, key):
        return self.creds.get(key)
    def get_certificates(self):
        return self.certs


def test_connect_passes_the_accepted_certificates_and_a_clean_host():
    """The platform hands the accepted certificate to every test and collect;
    it was never read. And the host field is trimmed before it is used."""
    seen = {}
    def _fake(host, user, password, **kw):
        seen.update(host=host, **kw)
        return None, [], {}
    inst = _Instance({"vcenter_host": " https://vc01.example.com:8443/ui ",
                      "vcenter_user": "u@vsphere.local"},
                     {"vcenter_password": "x"},
                     [_Cert("PEM-1"), _Cert(""), _Cert("PEM-2")])
    with patch.object(adapter.perfsvc, "connect", side_effect=_fake):
        adapter._connect(inst)
    assert seen["host"] == "vc01.example.com" and seen["port"] == 8443, seen
    assert seen["accepted_pems"] == ["PEM-1", "PEM-2"], seen
    assert seen["verify"] is True, "verification must default on"


def test_certificate_prompt_only_when_verifying_and_never_doubled():
    on = _Instance({"vcenter_host": "https://vc01.example.com/"})
    urls = adapter.get_endpoints(on).get_json()["endpointUrls"]
    assert urls == ["https://vc01.example.com"], urls
    off = _Instance({"vcenter_host": "vc01.example.com", "verify_certs": "false"})
    assert adapter.get_endpoints(off).get_json()["endpointUrls"] == []


def test_an_unreadable_certificate_entry_is_skipped_not_fatal():
    class _Bad:
        def get_certificate_string(self): raise KeyError("certPemString")
    inst = _Instance({}, {}, [_Bad(), _Cert("None"), _Cert("PEM-OK")])
    with patch.object(adapter.logger, "warning") as warn:
        assert adapter._accepted_pems(inst) == ["PEM-OK"]
    assert warn.called


class _Cluster:
    def __init__(self, name): self.name = name


def _collect_with(clusters, enabled, outcome, enabled_fn=None):
    """Run adapter.collect against fake clusters.

    enabled: {name: True/False/None}; outcome: {name: "ok" | Exception}."""
    import perfsvc
    key = perfsvc.parse_ref("host-domclient:6a46db86-350f-f7e5-653d-9c6b00c512b6")

    def _collect(perf, cluster, scope=None):
        out = outcome[cluster.name]
        if isinstance(out, Exception):
            raise out
        g = perfsvc.Grouped(); g.gauges["readCount"] = 1.0
        return {key: g}, []

    inst = _Instance({"vcenter_host": "vc01.example.com",
                      "attach_to_vcenter": "false"})
    with patch.object(adapter, "_connect",
                      return_value=(None, clusters, {"vsan-performance-manager": None})), \
         patch.object(perfsvc, "build_name_map", return_value={}), \
         patch.object(perfsvc, "build_parent_map", return_value={}), \
         patch.object(perfsvc, "build_disk_hardware", return_value={}), \
         patch.object(perfsvc, "vsan_enabled",
                      side_effect=enabled_fn or (lambda c: enabled[c.name])), \
         patch.object(perfsvc, "collect", side_effect=_collect):
        return adapter.collect(inst).get_json()


def test_one_failing_cluster_does_not_discard_the_others():
    """A cluster without data raised out of the loop and lost every other
    cluster's results with it -- silently, before collect() caught."""
    import perfsvc
    clusters = [_Cluster("compute-only"), _Cluster("broken"), _Cluster("good")]
    with patch.object(adapter.logger, "error") as err:
        out = _collect_with(
            clusters, {"compute-only": False, "broken": True, "good": None},
            {"compute-only": perfsvc.PerfSvcError("no data"),
             "broken": perfsvc.PerfSvcError("Performance Service returned no data"),
             "good": "ok"})
    assert "errorMessage" not in out, out.get("errorMessage")
    assert len(out["result"]) == 1, out["result"]
    # vSAN disabled and no data: normal. vSAN enabled and no data: reported.
    logged = " ".join(str(c) for c in err.call_args_list)
    assert "broken" in logged and "compute-only" not in logged, logged


def test_every_cluster_is_queried_even_with_vsan_disabled():
    """A compute cluster mounting a remote vSAN datastore may report vSAN
    disabled and still have data; 1.4.7 queried it, so this must too."""
    out = _collect_with([_Cluster("client")], {"client": False}, {"client": "ok"})
    assert "errorMessage" not in out, out.get("errorMessage")
    assert len(out["result"]) == 1, out["result"]


def test_every_cluster_failing_is_an_error():
    import perfsvc
    out = _collect_with(
        [_Cluster("a"), _Cluster("b")], {"a": True, "b": None},
        {"a": perfsvc.PerfSvcError("no data"), "b": RuntimeError("boom")})
    assert "No cluster returned vSAN data (2 of 2 failed)" in out["errorMessage"], out


def test_no_vsan_cluster_at_all_is_an_error():
    import perfsvc
    out = _collect_with([_Cluster("a")], {"a": False},
                        {"a": perfsvc.PerfSvcError("no data")})
    assert "none with vSAN enabled" in out["errorMessage"], out


def test_a_cluster_deleted_mid_cycle_does_not_sink_the_others():
    """cluster.name is a call to vCenter; a cluster removed since the
    inventory was listed raises ManagedObjectNotFound, which getattr's
    default does not catch."""
    import perfsvc

    class _Gone:
        _moId = "domain-c99"
        @property
        def name(self):
            raise perfsvc.vmodl.fault.ManagedObjectNotFound()
    gone = _Gone()
    out = _collect_with([gone, _Cluster("good")], {"good": True},
                        {"good": "ok"},
                        enabled_fn=lambda c: None if c is gone else True)
    assert "errorMessage" not in out, out.get("errorMessage")
    assert len(out["result"]) == 1, out["result"]


def _test_with(clusters, enabled, problems, found=3, answers=()):
    import perfsvc
    probed = []
    def _probe(perf, cluster):
        probed.append(cluster.name)
        if enabled[cluster.name] is False and cluster.name not in answers:
            return (0, problems.get(cluster.name))
        return (0, problems[cluster.name]) if problems.get(cluster.name) else (found, None)
    inst = _Instance({"vcenter_host": "vc01.example.com"})
    with patch.object(adapter, "_connect",
                      return_value=(None, clusters, {"vsan-performance-manager": None})), \
         patch.object(perfsvc, "vsan_enabled", side_effect=lambda c: enabled[c.name]), \
         patch.object(perfsvc, "probe", side_effect=_probe):
        return adapter.test(inst).get_json(), probed


def test_validate_probes_every_cluster_not_just_the_first():
    clusters = [_Cluster("compute-only"), _Cluster("a"), _Cluster("b")]
    enabled = {"compute-only": False, "a": True, "b": True}
    out, probed = _test_with(clusters, enabled, {})
    assert out == {}, out
    assert probed == ["compute-only", "a", "b"], probed
    out, _ = _test_with(clusters, enabled, {"b": "NotFound: service disabled"})
    assert "1 of 3" in out["errorMessage"] and "b (" in out["errorMessage"], out
    # a vSAN-disabled cluster that does not answer is not a failure
    out, _ = _test_with(clusters, enabled, {"compute-only": "InvalidArgument"})
    assert out == {}, out


def test_validate_counts_a_vsan_disabled_cluster_that_answers():
    """A compute cluster on a remote vSAN datastore can report vSAN disabled
    and still return data; it is a working cluster, not 'none with vSAN'."""
    out, probed = _test_with([_Cluster("client")], {"client": False}, {},
                             answers=("client",))
    assert out == {}, out


def test_validate_with_no_vsan_cluster_says_so():
    out, probed = _test_with([_Cluster("c1")], {"c1": False}, {})
    assert "none with vSAN enabled: c1" in out["errorMessage"], out
    assert probed == ["c1"]


def test_attach_off_is_not_reported_as_orphaned_every_cycle():
    """With attach_to_vcenter false nothing is attached by choice; it was
    still logged as ORPHANED and counted as a collection problem."""
    with patch.object(adapter.logger, "error") as err, \
         patch.object(adapter.logger, "warning") as warn:
        out = _collect_with([_Cluster("good")], {"good": True}, {"good": "ok"})
    assert "errorMessage" not in out
    assert not err.called, err.call_args_list
    assert not warn.called, warn.call_args_list


def test_username_comes_from_the_credential():
    """The username was a plain account field, part of the account's
    identity, so a credential was never a complete login."""
    inst = _Instance({"vcenter_user": "old@vsphere.local"},
                     {"vcenter_username": " new@vsphere.local ",
                      "vcenter_password": "x"})
    with patch.object(adapter.logger, "warning") as warn:
        assert adapter._username(inst) == "new@vsphere.local"
    assert not warn.called


def test_an_account_from_before_the_move_keeps_working_and_is_told():
    inst = _Instance({"vcenter_user": "old@vsphere.local"},
                     {"vcenter_password": "x"})
    with patch.object(adapter.logger, "warning") as warn:
        assert adapter._username(inst) == "old@vsphere.local"
    assert warn.called and "deprecated" in warn.call_args[0][0]


def test_no_username_anywhere_is_reported_in_words():
    import perfsvc
    inst = _Instance({"vcenter_host": "vc01.example.com"}, {"vcenter_password": "x"})
    try:
        adapter._username(inst)
        raise AssertionError("expected PerfSvcError")
    except perfsvc.PerfSvcError as exc:
        assert "credential" in str(exc), exc
    assert "credential" in adapter.test(inst).get_json()["errorMessage"]


def test_credential_carries_the_username_and_the_old_field_is_optional():
    d = adapter.get_adapter_definition().to_json()
    cred = {c["key"]: c for c in d["credential_types"]}["vsan_vc_credential"]
    keys = [f["key"] for f in cred["fields"]]
    assert keys == ["vcenter_username", "vcenter_password"], keys
    old = {i["key"]: i for i in d["adapter_instance"]["identifiers"]}["vcenter_user"]
    assert old["required"] is False, old
    # Same identity bit as before, so existing accounts keep their identity.
    assert old["ident_type"] == 1, old


def test_a_differing_old_username_is_noted_and_ignored():
    inst = _Instance({"vcenter_user": "old@vsphere.local"},
                     {"vcenter_username": "new@vsphere.local"})
    with patch.object(adapter.logger, "info") as info:
        assert adapter._username(inst) == "new@vsphere.local"
    assert any("ignored" in c[0][0] for c in info.call_args_list), info.call_args_list


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
