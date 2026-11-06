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


@pytest.fixture
def connect_proxy():
    """A minimal HTTP CONNECT proxy recording the tunnel targets (and the Proxy-Authorization header)."""
    seen: list[tuple[str, str | None]] = []
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(5)
    stop = threading.Event()

    def pipe(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        finally:
            for x in (a, b):
                try:
                    x.close()
                except OSError:
                    pass

    def serve():
        lsock.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = lsock.accept()
            except OSError:
                continue
            head = b""
            while b"\r\n\r\n" not in head:
                head += c.recv(4096)
            lines = head.decode().split("\r\n")
            target = lines[0].split(" ")[1]
            auth = next((x.split(": ", 1)[1] for x in lines if x.lower().startswith("proxy-authorization")), None)
            seen.append((target, auth))
            if target.startswith("10."):
                c.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                c.close()
                continue
            h, p = target.rsplit(":", 1)
            up = socket.create_connection((h.strip("[]"), int(p)))
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            threading.Thread(target=pipe, args=(c, up), daemon=True).start()
            threading.Thread(target=pipe, args=(up, c), daemon=True).start()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    yield lsock.getsockname()[1], seen
    stop.set()
    lsock.close()


def test_delivery_through_https_proxy_tunnels_to_the_checked_address(server, connect_proxy, monkeypatch):
    port, ca, hits = server
    pport, seen = connect_proxy
    monkeypatch.setattr("socket.getaddrinfo", lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                                                       ("127.0.0.1", p))])
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    ctx = ssl.create_default_context(cafile=ca)
    px = outbox.proxy_config(f"http://u:p%40ss@127.0.0.1:{pport}")
    code, err = outbox.pinned_post(f"https://hooks.example.test:{port}/in", b"{}", {}, allow_private=True,
                                   context=ctx, proxy=px)
    assert (code, err) == (204, "") and seen[0][0] == f"127.0.0.1:{port}"       # CONNECT to the pinned IP
    import base64

    assert base64.b64decode(seen[0][1].split(" ", 1)[1]).decode() == "u:p@ss"
    # host mode: the proxy gets the name; TLS still verifies it
    px_host = outbox.proxy_config(f"http://127.0.0.1:{pport}", connect_by="host")
    # the SSRF check still runs on the target before any proxy connection
    with pytest.raises(ApiError):
        outbox.pinned_post(f"https://hooks.example.test:{port}/in", b"{}", {}, allow_private=False, context=ctx,
                           proxy=px_host)
    assert len(seen) == 1
    # a refusing proxy is a failed attempt
    monkeypatch.setattr("socket.getaddrinfo", lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                                                       ("127.0.0.1" if h == "127.0.0.1" else
                                                                        "10.9.9.9", p))])
    code, err = outbox.pinned_post(f"https://hooks.example.test:{port}/in", b"{}", {}, allow_private=True,
                                   context=ctx, proxy=px)
    assert code == 0 and "403" in err
    assert outbox.proxy_config("direct") is None and outbox.proxy_config(None) is None


@pytest.mark.parametrize("addr", ["100.64.1.1", "192.0.2.1", "198.18.0.1", "169.254.169.254", "::ffff:10.0.0.1",
                                  "64:ff9b::a00:1", "2002:a00:1::1", "64:ff9b:1::1", "fd00::1", "::1"])
def test_non_global_addresses_are_refused(addr, monkeypatch):
    import ipaddress as ia

    assert outbox._bad_ip(ia.ip_address(addr))
    assert not outbox._bad_ip(ia.ip_address("93.184.216.34"))
    assert not outbox._bad_ip(ia.ip_address("64:ff9b::5db8:d822"))      # NAT64 of a public address
