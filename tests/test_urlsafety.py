import http.server
import threading
import time

import pytest

from signalpost.fetch import Fetcher, Operations
from signalpost.urlsafety import UrlPolicy, UrlRefused


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "http://100.64.0.1/",
    "file:///etc/passwd", "ftp://example.com/", "https://user:pw@example.com/",
    "http://printer.local/", "http://93.184.215.14:8080/",
])
def test_refused_urls(url):
    with pytest.raises(UrlRefused):
        UrlPolicy(frozenset()).check(url)


def test_public_literal_address_allowed():
    UrlPolicy(frozenset()).check("https://93.184.215.14/")


def test_allow_list_is_per_host_and_port():
    policy = UrlPolicy(frozenset({"127.0.0.1:8801"}))
    policy.check("http://127.0.0.1:8801/")
    with pytest.raises(UrlRefused):
        policy.check("http://127.0.0.1:8802/")
    with pytest.raises(UrlRefused):
        policy.check("http://169.254.169.254/")


def test_allow_list_env(monkeypatch):
    monkeypatch.setenv("SIGNALPOST_ALLOW_PRIVATE_HOSTS", "127.0.0.1")
    UrlPolicy().check("http://127.0.0.1:9999/")
    monkeypatch.delenv("SIGNALPOST_ALLOW_PRIVATE_HOSTS")
    with pytest.raises(UrlRefused):
        UrlPolicy().check("http://127.0.0.1:9999/")


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        _Handler.hits.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html>ok</html>")

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Handler.hits = []
    yield server.server_address[1]
    server.shutdown()


def _fetch(port: int, path: str, allow: frozenset[str]):
    fetcher = Fetcher(policy=UrlPolicy(allow), default_interval=0.0)
    return fetcher.get(f"http://127.0.0.1:{port}{path}", source="test", ops=Operations(),
                       deadline=time.monotonic() + 10, accept="text/html")


def test_private_host_never_requested_without_allow_list(local_server):
    snap = _fetch(local_server, "/", frozenset())
    assert snap.error and snap.error.startswith("url_refused")
    assert _Handler.hits == []


def test_redirect_to_metadata_is_refused_even_from_allowed_host(local_server):
    snap = _fetch(local_server, "/redirect", frozenset({"127.0.0.1"}))
    assert _Handler.hits == ["/redirect"]
    assert snap.error and snap.error.startswith("url_refused")
    ok = _fetch(local_server, "/", frozenset({"127.0.0.1"}))
    assert ok.ok and b"ok" in ok.body
