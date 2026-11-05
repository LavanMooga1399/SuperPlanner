"""SSRF guard (M5-DESIGN 4.6, 15.WP-S): the webhook connects to exactly the address that passed the check (one DNS
lookup, no rebinding window) while TLS keeps SNI and host-name verification; private targets refused."""

from __future__ import annotations

import datetime as dt
import http.server
import socket
import ssl
import threading

import pytest

from superplanner.api.errors import ApiError
from superplanner.integration import outbox


def _cert(tmp_path, name: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cp, kp = tmp_path / "c.pem", tmp_path / "k.pem"
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return str(cp), str(kp)


@pytest.fixture
def server(tmp_path):
    cp, kp = _cert(tmp_path, "hooks.example.test")
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append((self.headers.get("Host"), self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path == "/redirect":
                self.send_response(307)
                self.send_header("Location", "/internal-admin")
            else:
                self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cp, kp)
    srv.socket = sctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1], cp, hits
    srv.shutdown()


def test_pinned_connection_uses_the_checked_address_and_verifies_tls(server, monkeypatch):
    port, ca, hits = server
    calls = []
    answers = [["127.0.0.1"], ["10.66.66.66"]]          # a rebinding resolver: second answer differs

    def resolver(host, p, *a, **kw):
        calls.append(host)
        addrs = answers[min(len(calls) - 1, 1)]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, p)) for x in addrs]

    monkeypatch.setattr("socket.getaddrinfo", resolver)
    ctx = ssl.create_default_context(cafile=ca)
    code, err = outbox.pinned_post(f"https://hooks.example.test:{port}/in", b"{}", {"SP-Event-Id": "1"},
                                   allow_private=True, context=ctx)
    assert (code, err) == (204, "") and len(calls) == 1 and hits[0][0] == f"hooks.example.test:{port}"
    # host-name verification is kept: the same address under another name fails TLS
    calls.clear()
    code, err = outbox.pinned_post(f"https://other.example.test:{port}/in", b"{}", {}, allow_private=True,
                                   context=ctx)
    assert code == 0 and "SSL" in err
    # private targets are refused before any connection
    calls.clear()
    with pytest.raises(ApiError) as e:
        outbox.pinned_post(f"https://hooks.example.test:{port}/in", b"{}", {}, allow_private=False, context=ctx)
    assert e.value.code == "INT_URL_NOT_ALLOWED" and len(hits) == 1


def test_redirects_are_not_followed(server, monkeypatch):
    port, ca, hits = server
    monkeypatch.setattr("socket.getaddrinfo", lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                                                       ("127.0.0.1", p))])
    code, err = outbox.pinned_post(f"https://hooks.example.test:{port}/redirect", b"{}", {}, allow_private=True,
                                   context=ssl.create_default_context(cafile=ca))
    assert code == 307 and err == "HTTP 307" and len(hits) == 1       # the redirect target is never requested
