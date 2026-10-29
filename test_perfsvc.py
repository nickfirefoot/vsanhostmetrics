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
    # Broadcom's own name, which independently confirms the unit: "Bytes", not
    # the rate_bytes the schema's graph-level unit claims.
    assert metric_labels.LABELS["txSbSpaceMin"] == "RDT Network Socket Min Outbound Bytes"
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
    cryptic.  "RX lgt err" tells an operator nothing.

    Three sources feed these, in precedence order, and all three appear here:
    a curated override, Broadcom's own schema name, and our derived label for
    metrics the schema does not document."""
    import metric_labels as ml
    # Curated: the official name omits what was missed.
    assert ml.LABELS["rxMissErr"] == "pNIC RX missed error (ring buffer full)"
    # Official name, with NO "(%)" suffix: the RATIO.PERCENT unit renders
    # beside the value, so a suffix produced "pNIC RX CRC Error (%)  0.1 %".
    assert ml.LABELS["rxCrcErr"] == "pNIC RX CRC Error"
    assert ml.LABELS["txCarErr"] == "pNIC TX Carrier Error"
    assert "%" not in ml.LABELS["rxCrcErr"], "the unit carries it, not the name"
    assert ml.UNITS["rxCrcErr"] == "RATIO.PERCENT"
    # Derived: undocumented upstream, so our token rules have to carry it.
    assert ml.LABELS["rxLgtErr"] == "RX length errors"
    assert ml.LABELS["rxFrmErr"] == "RX frame alignment errors"
    assert ml.LABELS["ioChainRxdrops"] == "IO chain RX drops"
    # Whatever the source, none of them may leave a bare abbreviation.
    for key in ("rxLgtErr", "txCarErr", "rxFrmErr", "rxMissErr", "rxCrcErr"):
        assert " err" not in ml.LABELS[key].lower().replace(" error", ""), key


def test_cache_miss_is_not_pluralised_into_missed():
    """Regression: a whole-token "miss"->"missed" rule for rxMissErr turned
    30 cache-miss metrics into "cache missed", which is wrong English."""
    import metric_labels as ml
    wrong = [k for k, v in ml.LABELS.items() if "cache missed" in v.lower()]
    assert not wrong, wrong[:5]


# Two throwaway self-signed certificates, public halves only: a leaf that is
# not vCenter's, and a CA that did not issue vCenter's certificate.
PEM_A = """-----BEGIN CERTIFICATE-----
MIIBlTCCATugAwIBAgIUW2YSru6pA80i/lFe73J+yUy/QIAwCgYIKoZIzj0EAwIw
IDEeMBwGA1UEAwwVdmMtdGVzdC1hLmV4YW1wbGUuY29tMB4XDTI2MTAyODIxMjQz
OVoXDTM2MTAyNTIxMjQzOVowIDEeMBwGA1UEAwwVdmMtdGVzdC1hLmV4YW1wbGUu
Y29tMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEdOLWuB89IWDh4DW4rw6pODKo
lmFVs9rG7GBlxq/KPob6p59H8BNEjN7IOqKkXsqzoullha9DLeLzvcipRsM4K6NT
MFEwHQYDVR0OBBYEFDerNn5qcXyaP/kGMQuF+4VCX5vyMB8GA1UdIwQYMBaAFDer
Nn5qcXyaP/kGMQuF+4VCX5vyMA8GA1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwID
SAAwRQIgbId05iYysPcWrY7FjG5ZmyU1plFkcWjThVsDFXSPRBACIQDuu/JELywq
E15KVDROT2fKJgGAnZWQX64NVtGCWbOmiw==
-----END CERTIFICATE-----
"""
PEM_B = """-----BEGIN CERTIFICATE-----
MIIBlTCCATugAwIBAgIUOPE4r8VFCC50hOPe9pdLZ84l8UAwCgYIKoZIzj0EAwIw
IDEeMBwGA1UEAwwVdmMtdGVzdC1iLmV4YW1wbGUuY29tMB4XDTI2MTAyODIxMjQz
OVoXDTM2MTAyNTIxMjQzOVowIDEeMBwGA1UEAwwVdmMtdGVzdC1iLmV4YW1wbGUu
Y29tMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEF6VJ0ik5cGBBfo2FvJB+B5tr
2x4CO/e01bRaedrIsR1IvI0uNL7rbW4xPsZYD++iNWffptMWWcCVHR92nTX4jqNT
MFEwHQYDVR0OBBYEFMWYBxy/yLs6vzWm0N69r0HgFpldMB8GA1UdIwQYMBaAFMWY
Bxy/yLs6vzWm0N69r0HgFpldMA8GA1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwID
SAAwRQIhAOhYoLkCRxAWGRMyXiH+K+cmuNEcCX6VSyr68LRVnSMLAiAPnHvg0lyC
S8KhoShbQZhuPZZEZPux/wVC6x6hZxqWIQ==
-----END CERTIFICATE-----
"""


def _tls_lab():
    """A root CA, an issuing CA and a leaf for 'localhost' (DNS SAN only, as
    lab vCenters have), generated per run so no private key lives in the
    repository, and a TLS server on 127.0.0.1 presenting leaf + issuing CA,
    as the lab vCenters do. Returns (port, pems by name, stop) or None when
    the cryptography package is absent (outside the adapter image)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("    (skipped: no cryptography package -- runs inside the "
              "adapter image, as CI runs it)")
        return None
    import datetime as _dt, os as _os, socket as _socket, ssl as _ssl
    import tempfile, threading

    now = _dt.datetime.now(_dt.timezone.utc)

    def make(cn, issuer_cert, issuer_key, ca, san=None):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        b = (x509.CertificateBuilder().subject_name(name)
             .issuer_name(issuer_cert.subject if issuer_cert else name)
             .public_key(key.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - _dt.timedelta(days=1))
             .not_valid_after(now + _dt.timedelta(days=30))
             .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if san:
            b = b.add_extension(x509.SubjectAlternativeName(
                [x509.DNSName(san)]), critical=False)
        cert = b.sign(issuer_key or key, hashes.SHA256())
        return cert, key

    root, root_key = make("Test Root", None, None, True)
    issuing, issuing_key = make("Test Issuing", root, root_key, True)
    leaf, leaf_key = make("localhost", issuing, issuing_key, False, "localhost")
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM).decode()

    d = tempfile.mkdtemp()
    chain = _os.path.join(d, "chain.pem"); keyf = _os.path.join(d, "key.pem")
    open(chain, "w").write(pem(leaf) + pem(issuing))
    open(keyf, "wb").write(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    sctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(chain, keyf)
    srv = _socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(16)
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            try:
                with sctx.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except Exception:                            # noqa: BLE001
                pass
    threading.Thread(target=serve, daemon=True).start()

    def close():
        stop.set(); srv.close()
    return srv.getsockname()[1], {"leaf": pem(leaf), "issuing": pem(issuing),
                                  "root": pem(root)}, close


class _TLSConnect:
    """Stands in for SmartConnect: a REAL handshake with the context it is
    given against the lab server (so chain, anchor and hostname checks are
    OpenSSL's, not a fake's), then pyVmomi's own thumbprint check, with a
    mismatch wrapped the way pyVmomi 8 wraps it (in HostConnectFault)."""
    def __init__(self, port):
        self.port = port; self.calls = []

    def __call__(self, host, port, user, pwd, sslContext, thumbprint,
                 httpConnectionTimeout=None):
        import socket as _socket
        from pyVmomi.Security import VerifyCertThumbprint
        self.calls.append((sslContext.verify_mode, thumbprint,
                           httpConnectionTimeout))
        with _socket.create_connection((host, self.port), timeout=5) as raw:
            with sslContext.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(True)
        if thumbprint:
            try:
                VerifyCertThumbprint(der, thumbprint)
            except perfsvc.ThumbprintMismatchException as exc:
                raise RuntimeError(f"HostConnectFault: {exc}")
        return "si"


def _connect_lab(lab, host, received, verify=True):
    port, _, _ = lab
    fake = _TLSConnect(port)
    real_sc, real_inv = perfsvc.SmartConnect, perfsvc._inventory
    perfsvc.SmartConnect = fake
    perfsvc._inventory = lambda si, ctx, fp: (si, ["c"], {"fp": fp})
    try:
        _, _, mos = perfsvc.connect(host, "u", "p", verify=verify,
                                    accepted_pems=received, port=port)
        return mos["fp"], fake.calls
    finally:
        perfsvc.SmartConnect, perfsvc._inventory = real_sc, real_inv


def _sha(pem):
    import hashlib, ssl as _ssl
    return hashlib.sha256(_ssl.PEM_cert_to_DER_cert(pem.strip())).hexdigest()


def test_received_certificates_verify_by_chain_or_by_pin():
    """What Operations passes is this account's accepted leaves PLUS every
    CA the cluster trusts. Where Operations trusts vCenter through a CA, no
    accept dialog fires and only CAs arrive (devel 9.0.2), so a leaf-only
    pin failed there. Each case: (host, received, expected thumbprint pinned
    or None for verified by chain)."""
    lab = _tls_lab()
    if lab is None:
        return
    port, p, close = lab
    try:
        leaf = _sha(p["leaf"])
        cases = {
            "leaf accepted, name matches": ("localhost", [p["leaf"]], None),
            "leaf accepted, by IP (pin)": ("127.0.0.1", [p["leaf"]], leaf),
            "CAs only": ("localhost", [p["issuing"], p["root"]], None),
            "issuing CA only (partial chain)": ("localhost", [p["issuing"]], None),
            "root only": ("localhost", [p["root"]], None),
            "mixed": ("localhost", [PEM_A, p["issuing"], p["root"]], None),
            "mixed, by IP (pin)": ("127.0.0.1", [p["root"], p["leaf"]], leaf),
        }
        for label, (host, received, want) in cases.items():
            fp, calls = _connect_lab(lab, host, received)
            assert fp == want, (label, fp, want)
            assert all(c[2] == perfsvc.HTTP_TIMEOUT_S for c in calls), (label, calls)
    finally:
        close()


def test_a_certificate_nobody_accepted_is_rejected_with_both_sides_named():
    lab = _tls_lab()
    if lab is None:
        return
    port, p, close = lab
    try:
        for label, host, received in (
                ("another leaf", "localhost", [PEM_A]),
                ("another CA", "localhost", [PEM_B]),
                ("CAs only, by IP: an IP needs the leaf accepted",
                 "127.0.0.1", [p["issuing"], p["root"]])):
            try:
                _connect_lab(lab, host, received)
                raise AssertionError(f"{label}: let through")
            except perfsvc.PerfSvcError as exc:
                text = str(exc)
                assert "matches none" in text, (label, text)
                assert _sha(p["leaf"]) in text, (label, "presented sha missing")
                for pem in received:
                    assert _sha(pem) in text, (label, "received sha missing")
        try:
            _connect_lab(lab, "localhost", [])
            raise AssertionError("nothing received: let through")
        except perfsvc.PerfSvcError as exc:
            assert "Validate Connection" in str(exc), exc
            assert _sha(p["leaf"]) in str(exc), exc
    finally:
        close()


def test_a_certificate_swapped_between_look_and_login_is_rejected():
    """The leaf is read once to choose the pin; if the login then meets a
    different certificate, pyVmomi's pin check refuses it, and that must be
    reported as a mismatch, not as a failed login."""
    lab = _tls_lab()
    if lab is None:
        return
    port, p, close = lab
    real = perfsvc.presented_sha256
    perfsvc.presented_sha256 = lambda host, port: _sha(PEM_A)
    try:
        _connect_lab(lab, "127.0.0.1", [PEM_A])
        raise AssertionError("a swapped certificate was let through")
    except perfsvc.PerfSvcError as exc:
        assert "matches none" in str(exc), exc
        assert _sha(p["leaf"]) in str(exc), "the certificate actually met is not named"
    finally:
        perfsvc.presented_sha256 = real
        close()


def test_the_pin_relies_on_pyvmomi_8_checking_every_connection():
    """perfsvc.connect pins with an unverified context plus `thumbprint`.
    That is safe only because pyVmomi 8.0.x's GetConnection verifies the
    thumbprint on every new connection. pyVmomi 9.x checks a pin only after
    an SSLCertVerificationError, which an unverified context never raises,
    so the login would go out unverified. Fail loudly on a bump; see the
    comment at the pinned login in perfsvc.connect for what to change."""
    import inspect
    from importlib.metadata import version
    from pyVmomi.SoapAdapter import SoapStubAdapter
    installed = version("pyvmomi")
    assert installed.split(".")[0] == "8", (
        f"pyVmomi {installed}: change the pinned login in perfsvc.connect "
        f"before moving off 8.x")
    src = inspect.getsource(SoapStubAdapter.GetConnection)
    assert "_VerifyThumbprint(" in src, (
        "SoapStubAdapter.GetConnection no longer checks the thumbprint; the "
        "pinned login in perfsvc.connect would not be verified")


def test_one_bad_received_entry_does_not_stop_the_good_one():
    """A malformed entry -- empty, the string "None" (what CertificateInfo
    returns for a missing PEM), stray whitespace, broken base64 -- raised a
    raw ValueError and the valid certificate after it was never tried."""
    lab = _tls_lab()
    if lab is None:
        return
    port, p, close = lab
    try:
        lines = p["leaf"].splitlines()
        broken = "\n".join(lines[:2] + lines[3:])     # a body line missing
        received = ["", "None", broken, "\n  " + p["leaf"] + "\n\n"]
        fp, _ = _connect_lab(lab, "127.0.0.1", received)
        assert fp == _sha(p["leaf"]), fp
        assert [s for _, s in perfsvc.usable_certificates(received)] == \
            [_sha(p["leaf"])]
    finally:
        close()


def test_verify_off_checks_nothing_and_pins_nothing():
    lab = _tls_lab()
    if lab is None:
        return
    port, p, close = lab
    try:
        import ssl as _ssl
        fp, calls = _connect_lab(lab, "127.0.0.1", [PEM_A], verify=False)
        assert fp is None
        assert [c[:2] for c in calls] == [(_ssl.CERT_NONE, None)], calls
    finally:
        close()


def test_a_wrong_password_is_still_reported_as_a_login_failure():
    """The pin-mismatch detection must not swallow ordinary login faults,
    and the UI gets the fault's message, not its multi-line repr."""
    def _bad_login(**kwargs):
        raise perfsvc.vim.fault.InvalidLogin(
            msg="Cannot complete login due to an incorrect user name or password.")
    real = perfsvc.SmartConnect
    perfsvc.SmartConnect = _bad_login
    try:
        perfsvc.connect("vc01.example.com", "u", "p", verify=False)
        raise AssertionError("expected PerfSvcError")
    except perfsvc.PerfSvcError as exc:
        text = str(exc)
        assert "login failed" in text and "incorrect user name" in text, text
        assert "dynamicType" not in text, text
    finally:
        perfsvc.SmartConnect = real


def test_the_version_probe_has_a_timeout_and_it_is_restored():
    """SmartConnect's API-version probe takes no timeout argument."""
    import socket as _socket
    seen = []
    def _record(**kwargs):
        seen.append((_socket.getdefaulttimeout(), kwargs.get("httpConnectionTimeout")))
        return "si"
    real, before = perfsvc.SmartConnect, _socket.getdefaulttimeout()
    perfsvc.SmartConnect = _record
    try:
        perfsvc._login("vc01.example.com", 443, "u", "p", None, None)
    finally:
        perfsvc.SmartConnect = real
    assert seen == [(perfsvc.HTTP_TIMEOUT_S, perfsvc.HTTP_TIMEOUT_S)], seen
    assert _socket.getdefaulttimeout() == before


def test_host_field_is_normalised():
    """A URL pasted into the server field produced https://https://... in the
    certificate prompt and an unresolvable host in SmartConnect."""
    cases = {
        "vc01.example.com": ("vc01.example.com", 443),
        "  vc01.example.com  ": ("vc01.example.com", 443),
        "https://vc01.example.com/": ("vc01.example.com", 443),
        "https://vc01.example.com/ui/app": ("vc01.example.com", 443),
        "vc01.example.com:8443": ("vc01.example.com", 8443),
        "https://192.0.2.10:8443/sdk": ("192.0.2.10", 8443),
        "[2001:db8::10]": ("2001:db8::10", 443),
    }
    for raw, want in cases.items():
        assert perfsvc.split_host(raw) == want, (raw, perfsvc.split_host(raw))
    assert perfsvc.endpoint_url("vc01.example.com") == "https://vc01.example.com"
    assert perfsvc.endpoint_url("vc01.example.com", 8443) == \
        "https://vc01.example.com:8443"
    assert perfsvc.endpoint_url("2001:db8::10") == "https://[2001:db8::10]"
    for bad in ("", "   ", "vc01.example.com:notaport"):
        try:
            perfsvc.split_host(bad)
            raise AssertionError(f"{bad!r} was accepted")
        except perfsvc.PerfSvcError:
            pass


def test_nothing_turns_tls_verification_off_for_the_process():
    """The vendored vsanapiutils.GetLatestVmodlVersion replaced
    ssl._create_default_https_context with the unverified one, on every
    connect, whatever the verify setting said."""
    import pathlib, re, ssl as _ssl
    before = _ssl._create_default_https_context
    import vsanapiutils
    vsanapiutils.GetLatestVmodlVersion("127.0.0.1:1")    # refused, offline
    assert _ssl._create_default_https_context is before
    for f in pathlib.Path("app").rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"_create_default_https_context\s*=", src), f


def test_clusters_in_foldered_datacenters_are_found():
    """Only datacenters directly under the root were walked, so a datacenter
    inside a folder was skipped and its clusters never collected."""
    made = []

    class _View:
        def __init__(self, clusters): self.view = clusters; self.destroyed = False
        def DestroyView(self): self.destroyed = True

    class _VM:
        def CreateContainerView(self, container, types, recursive):
            made.append((container, types, recursive))
            v = _View(["c-in-root-dc", "c-in-foldered-dc"]); made.append(v)
            return v

    class _Content:
        rootFolder = "root"; viewManager = _VM()

    class _SI:
        _stub = None
        def RetrieveContent(self): return _Content()

    real = perfsvc.vsanapiutils.GetVsanVcMos
    perfsvc.vsanapiutils.GetVsanVcMos = lambda *a, **k: {}
    try:
        _, clusters, _ = perfsvc._inventory(_SI(), None, None)
    finally:
        perfsvc.vsanapiutils.GetVsanVcMos = real
    assert clusters == ["c-in-root-dc", "c-in-foldered-dc"], clusters
    assert made[0] == ("root", [perfsvc.vim.ClusterComputeResource], True), made[0]
    assert made[1].destroyed, "the container view was left on the server"


def test_a_session_is_logged_out_if_reading_inventory_fails():
    """connect() logs in, then reads inventory; if that read fails the caller
    never gets the session to disconnect, so connect must."""
    gone = []

    class _SI:
        _stub = None
        def RetrieveContent(self): raise RuntimeError("NoPermission")

    real = perfsvc.Disconnect
    perfsvc.Disconnect = gone.append
    try:
        si = _SI()
        try:
            perfsvc._inventory(si, None, None)
            raise AssertionError("expected the inventory failure")
        except RuntimeError:
            pass
        assert gone == [si], gone
    finally:
        perfsvc.Disconnect = real


def test_absent_features_are_not_reported_as_problems():
    """'N entity types not available' was appended to problems, so the
    caller's collection-problem warning fired on nearly every cluster every
    cycle. Absent features are a property of the cluster, not a fault."""
    _patch_specs()

    class _Perf:
        def VsanPerfQueryPerf(self, specs, cluster):
            ent = specs[0].entityRefId.split(":")[0]
            if ent == "host-domclient":
                return [_Result(f"host-domclient:{HOST}",
                                [_Value("readCount", "1,2,3")])]
            raise perfsvc.vmodl.fault.NotSupported()

    objs, problems = perfsvc.collect(_Perf(), cluster=None)
    assert objs, "the supported entity type was lost"
    assert problems == [], problems


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


def test_units_do_not_contradict_what_the_metric_is():
    """Logic check: if the name says latency the unit must be a time, if it
    says throughput a rate, and so on.  Guards against a plausible-looking but
    wrong unit, which is worse than none because Operations scales and renders
    it confidently.

    Precedence matters. A percent qualifier outranks an embedded noun --
    netSchedBWDiscoveryStopsDueToHighLatencyPct is a percentage that happens to
    mention latency, not a duration.
    """
    import json
    import re
    import metric_labels as ml

    schema = {}
    try:
        for metrics in json.load(open("docs/assets/perfsvc_schema.json")).values():
            for mid, d in metrics.items():
                schema.setdefault(mid, d)
    except FileNotFoundError:
        pass

    EXPECT = [                                    # first match wins
        # "(%)" is the converted per-mille suffix; "X per Y" is a ratio
        # (Cache Miss Per IOPS) even when Y is a throughput or IOPS noun.
        (r"percent|percentage|pct\b|%|\bper (iops|throughput)\b", "RATIO"),
        (r"latency|\blat\b|\bqlat\b", "TIME"),
        (r"throughput|bandwidth", "DATA_RATE"),
        (r"\biops\b", "MISC"),
        (r"\bbytes\b|\bsize\b|\bsb ?space\b", "DATA_SIZE"),
    ]
    contradictions = []
    for mid, unit in ml.UNITS.items():
        text = " ".join([(schema.get(mid) or {}).get("name") or "",
                         ml.LABELS.get(mid, ""), mid]).lower()
        official = (schema.get(mid) or {}).get("unit")
        for rx, want in EXPECT:
            if re.search(rx, text):
                got = unit.split(".")[0]
                # "Requested bytes for read" is officially rate_bytes and
                # HCIBench charts it as a rate: a rate named in bytes, not a
                # size. Both authorities agree, so the noun loses.
                if want == "DATA_SIZE" and got == "DATA_RATE" and official == "rate_bytes":
                    break
                if got != want:
                    contradictions.append((mid, ml.LABELS.get(mid), unit, want))
                break
    assert not contradictions, contradictions[:5]


def test_parent_map_is_empty_without_a_vcenter_id():
    """Relationships key on VMEntityObjectID + VMEntityVCID. Without the
    vCenter instance UUID we cannot key an object the way the VMWARE adapter
    does, and a near-miss would create a duplicate ghost object rather than
    attaching to the real one -- so emit nothing instead."""
    class _About:
        instanceUuid = ""
    class _Content:
        about = _About()
        rootFolder = None
        viewManager = None
    class _SI:
        def RetrieveContent(self): return _Content()
    out = perfsvc.build_parent_map(_SI(), [], None)
    assert out["vcid"] == ""
    assert out["hosts"] == {} and out["vms"] == {} and out["clusters"] == {}


def test_one_vcenter_object_yields_one_parent():
    """Regression: two buckets can resolve to the same vCenter object -- a VM
    reached by vm_uuid and the same VM reached by a virtual disk's datastore
    path, or a host reached by host_uuid and by a disk_uuid. Keying the parent
    cache by bucket built two Python objects sharing one Operations key, and
    CollectResult rejects that with ObjectKeyAlreadyExistsException, which
    aborts the ENTIRE collection -- the adapter reported only its own instance
    object, in ERROR, with "Dockerized adapter API client error".
    """
    sys.argv = ["x", "collect", "in", "out"]
    import adapter

    parents = {
        "vcid": "VC-1",
        "vms": {"vm-uuid-a": "vm-8032"},
        "vdisks": {"path/to/a.vmdk": "vm-8032"},
        "hosts": {"host-uuid-a": "host-27"},
        "disks": {"disk-uuid-a": "host-27"},
        "clusters": {},
    }
    cache = {}
    a = adapter._vc_parent(cache, parents, "vms", "vm-uuid-a")
    b = adapter._vc_parent(cache, parents, "vdisks", "path/to/a.vmdk")
    c = adapter._vc_parent(cache, parents, "hosts", "host-uuid-a")
    d = adapter._vc_parent(cache, parents, "disks", "disk-uuid-a")
    assert a is b, "same VM via two buckets must be one object"
    assert c is d, "same host via two buckets must be one object"
    assert len(cache) == 2, cache.keys()


def test_actual_duplicates_are_not_collected():
    """*Actual is the same measurement under a second name -- measured across a
    full collection, 201 pairs, 201 identical values, zero differences. *Raw is
    NOT a duplicate: it is the cumulative since-boot counter and differs in
    practice (pauseCountRaw 224 against pauseCount 0)."""
    for entity, spec in perfsvc.MODEL.ENTITIES.items():
        kept = set(perfsvc.metrics_for(entity))
        present = set(spec["metrics"])
        for m in present:
            if m.endswith("Actual") and m[:-6] in present:
                assert m not in kept, f"{entity}: {m} duplicates {m[:-6]}"
            if m.endswith("Raw"):
                assert m in kept, f"{entity}: {m} must be kept"
    # pnic is the worst offender and a good canary
    pnic = set(perfsvc.metrics_for("vsan-pnic-net"))
    assert "rxMissErr" in pnic and "rxMissErrActual" not in pnic
    assert "rxMissErrRaw" in pnic


def test_permille_is_converted_to_percent():
    """The service reports these in parts per thousand. Broadcom publish their
    thresholds in percent, so a raw 1 sits on the out-of-order warning line
    while looking like a count of one."""
    assert perfsvc.to_percent("portRxDrops", 1.0) == 0.1
    assert perfsvc.to_percent("rxCrcErr", 25.0) == 2.5
    # anything not per-mille passes through untouched
    assert perfsvc.to_percent("rxThroughput", 1000000.0) == 1000000.0
    assert perfsvc.to_percent("rxPackets", 42.0) == 42.0
    import metric_labels as ml
    # Every converted metric must DECLARE the unit, and must not also spell it
    # in the name -- Operations renders the unit, so both gives "... (%)  0.1 %".
    for m in perfsvc.PERMILLE:
        if m in ml.LABELS:
            assert ml.UNITS.get(m) == "RATIO.PERCENT", f"{m} converted, unit not percent"
            assert "%" not in ml.LABELS[m], f"{m} spells the unit in its name too"


def test_nothing_claims_percent_without_being_converted():
    """The inverse, and the bug it guards against was live until 2026-10-13.

    The service schema calls 98 metrics permille; perfsvc divides 24. The label
    generator used to declare RATIO.PERCENT from the SCHEMA, so 74 metrics were
    presented as a percentage whose value had never been divided by ten -- a
    10x overstatement for anything genuinely per-mille. Declaring a unit we do
    not honour is worse than declaring none.
    """
    import metric_labels as ml
    claimed = {k for k, v in ml.UNITS.items() if v == "RATIO.PERCENT"}
    converted = set(perfsvc.PERMILLE)
    # Already a percentage at source, so no conversion is owed. Two routes:
    # the id says so anywhere in the name (iopsDelayPctSched, coreUtilPct), or
    # build_metric_labels.py overrides it because the SCHEMA says "percentage"
    # rather than "permille" -- a different unit from the one perfsvc converts.
    SCHEMA_SAYS_PERCENTAGE = {"iopsCacheMissRate", "tputCacheMissRate"}

    def self_describing(k):
        low = k.lower()
        return any(t in low for t in ("pct", "percent", "util", "ratio"))

    unjustified = sorted(k for k in claimed - converted
                         if not self_describing(k)
                         and k not in SCHEMA_SAYS_PERCENTAGE)
    assert not unjustified, (
        f"{len(unjustified)} metrics declare RATIO.PERCENT without being "
        f"converted: {unjustified[:6]}")


def test_adapter_definition_actually_builds():
    """mp-build reports a broken definition only as "adapterDefinition endpoint
    returned no response", with no traceback -- a NameError in the definition
    loop cost a full build cycle to find. Build it here, where the error is
    visible."""
    try:
        from aria.ops.definition.units import Units  # noqa: F401
    except ImportError:
        return                                        # SDK absent: offline run
    saved = sys.argv
    sys.argv = ["adapter.py", "adapter_definition", "in", "out"]
    try:
        import adapter
        definition = adapter.get_adapter_definition()
        assert definition is not None
        assert definition.to_json()
    finally:
        sys.argv = saved


def test_model_is_non_trivial():
    assert len(perfsvc.MODEL.ENTITIES) >= 20
    t = perfsvc.MODEL.ENTITIES["vsan-tcpip-stats"]
    assert t["identity"] == ["host_uuid", "stack"]
    assert "tcpRcvoopackRate" in t["metrics"]


def _scope_probe(scope):
    """Run collect() against a perf stub and report which entities it asked for."""
    asked = []

    class _Perf:
        def VsanPerfQueryPerf(self, specs, cluster):
            asked.extend(sp.entityRefId.split(":")[0] for sp in specs)
            return []

    # collect() raises when every entity type comes back empty, which is
    # correct behaviour and exactly what a stub returning [] triggers. The
    # entities were already recorded by then, which is all this probe wants.
    try:
        perfsvc.collect(_Perf(), object(), scope=scope)
    except perfsvc.PerfSvcError:
        pass
    return asked


def test_scope_none_queries_every_entity_type():
    asked = _scope_probe(None)
    assert len(asked) == len(perfsvc.MODEL.ENTITIES), (
        f"queried {len(asked)}, model has {len(perfsvc.MODEL.ENTITIES)}")


def test_scope_restricts_which_entities_are_queried():
    asked = _scope_probe({"cluster-domclient": {"iopsRead"}})
    assert asked == ["cluster-domclient"], asked


def test_dashboard_scope_skips_most_of_the_model():
    import metric_scope
    ent_for_kind = {sp["kind"]: e
                    for e, sp in perfsvc.MODEL.ENTITIES.items()}
    scope = {ent_for_kind[k]: set(v)
             for k, v in metric_scope.COVERED.items() if k in ent_for_kind}
    asked = _scope_probe(scope)
    # The saving is the point of the feature; assert it is real, not nominal.
    assert len(asked) < len(perfsvc.MODEL.ENTITIES) / 2, (
        f"dashboard scope queried {len(asked)} of "
        f"{len(perfsvc.MODEL.ENTITIES)} -- barely a saving")
    assert set(asked) <= set(perfsvc.MODEL.ENTITIES)


def test_metric_scope_is_not_stale():
    """app/metric_scope.py is generated; a drifted copy silently under-collects.

    Regenerating is the only honest check -- comparing counts would pass while
    the contents were wrong.
    """
    import importlib.util, io, contextlib, pathlib
    import metric_scope
    before = pathlib.Path("app/metric_scope.py").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "gen_metric_scope", "tools/gen_metric_scope.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    with contextlib.redirect_stdout(io.StringIO()):
        gen.main()
    after = pathlib.Path("app/metric_scope.py").read_text(encoding="utf-8")
    if before != after:
        pathlib.Path("app/metric_scope.py").write_text(before, encoding="utf-8")
        raise AssertionError(
            "app/metric_scope.py is stale -- run tools/gen_metric_scope.py")
    assert metric_scope.COVERED, "COVERED is empty; the generator examined nothing"


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
