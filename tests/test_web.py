import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from conftest import brreg, make_fetcher

from signalpost.research import Researcher, ResearchOptions
from signalpost.web.server import App, make_handler


@pytest.fixture
def ui(tmp_path):
    batch = tmp_path / "batch.jsonl"
    batch.write_text(json.dumps({"organisation_number": "923609016", "status": "available",
                                 "legal_identity": {"name": "EQUINOR ASA"},
                                 "sections": {}, "claims": [], "changes": []}) + "\n")
    app = App(str(tmp_path / "state"), str(batch))
    fetcher, _ = make_fetcher(brreg("923609016"))
    app.researcher = Researcher(fetcher, app.store, ResearchOptions(web=False))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def test_pages_and_security_headers(ui):
    for path in ("/", "/company/923609016", "/compare?orgnr=923609016&orgnr=810034882", "/batch"):
        status, headers, body = get(ui + path)
        assert status == 200 and b"/static/app.js" in body
        assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_company_api_and_validation(ui):
    status, _, body = get(ui + "/api/company/923%20609%20016")
    env = json.loads(body)
    assert status == 200 and env["status"] == "available"
    status, _, body = get(ui + "/api/company/923609017")
    assert status == 400 and "check digit" in json.loads(body)["message"]


def test_batch_api(ui):
    status, _, body = get(ui + "/api/batch")
    data = json.loads(body)
    assert status == 200 and data["count"] == 1
    assert data["companies"][0]["name"] == "EQUINOR ASA"


def test_static_assets_do_not_inject_html():
    from pathlib import Path
    js = (Path(__file__).parents[1] / "signalpost/web/static/app.js").read_text()
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert 'rel: "noopener noreferrer"' in js
    assert "Not refreshed this run" in js and "Sources checked (" in js
    assert "No sources recorded" in js
