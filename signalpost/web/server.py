"""Small web UI: profile lookup, compare view, batch browser, and a JSON API.

Standard library HTTP server only. Pages are one static shell rendered by `static/app.js`, which
inserts source text with textContent only (never as HTML). Live lookups run the same research
pipeline as the batch command against a persistent state directory, so refreshes show changes.
"""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..fetch import Fetcher
from ..inputs import InputRow
from ..orgnr import normalise, validation_error
from ..research import Researcher, ResearchOptions
from ..runner import BRREG_INTERVALS
from ..store import StateStore
from ..urlsafety import UrlPolicy
from ..website import WebsiteResearch

STATIC = Path(__file__).parent / "static"
CACHE_SECONDS = 900
PAGE_ROUTES = re.compile(r"^/(|company/[^/]+|compare|batch)$")
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                               "script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class App:
    def __init__(self, state_dir: str, batch_path: str | None, web: bool = True):
        self.store = StateStore(state_dir)
        fetcher = Fetcher(policy=UrlPolicy(), rate_intervals=BRREG_INTERVALS,
                          default_interval=0.5)
        self.researcher = Researcher(fetcher, self.store, ResearchOptions(web=web),
                                     website_factory=WebsiteResearch)
        self.cache: dict[str, tuple[float, dict]] = {}
        self.locks: dict[str, threading.Lock] = {}
        self.lock = threading.Lock()
        self.batch_path = batch_path
        self.batch: dict[str, dict] = {}
        self.batch_order: list[str] = []
        if batch_path:
            self.load_batch(batch_path)

    def load_batch(self, path: str) -> None:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    env = json.loads(line)
                    number = env.get("organisation_number")
                    if number not in self.batch:
                        self.batch_order.append(number)
                    self.batch[number] = env

    def batch_index(self) -> dict:
        rows = []
        for number in self.batch_order:
            env = self.batch[number]
            legal = env.get("legal_identity") or {}
            rows.append({
                "organisation_number": number,
                "name": legal.get("name"),
                "status": env.get("status"),
                "municipality": legal.get("municipality"),
                "sections": {k: v.get("availability") for k, v in env["sections"].items()},
                "claims": sum(1 for c in env.get("claims", []) if c["availability"] == "available"),
                "changes": len(env.get("changes", [])),
            })
        return {"source": Path(self.batch_path).name if self.batch_path else None,
                "count": len(rows), "companies": rows}

    def company(self, number: str, refresh: bool = False) -> dict:
        with self.lock:
            lock = self.locks.setdefault(number, threading.Lock())
        with lock:
            hit = self.cache.get(number)
            if hit and not refresh and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
            deadline = time.monotonic() + 45
            row = InputRow(index=0, raw=number, organisation_number=number)
            env = self.researcher.research(row, f"ui-{time.strftime('%Y%m%dT%H%M%S')}",
                                           deadline, deadline)
            self.cache[number] = (time.monotonic(), env)
            return env


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Signalpost"

        def log_message(self, fmt, *args):
            sys.stderr.write("[ui] " + fmt % args + "\n")

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            parts = urlsplit(self.path)
            path, query = unquote(parts.path), parse_qs(parts.query)
            try:
                if PAGE_ROUTES.match(path):
                    return self._static("index.html")
                if path.startswith("/static/"):
                    return self._static(path.removeprefix("/static/"))
                if path.startswith("/api/company/"):
                    return self._company(path.removeprefix("/api/company/"), query)
                if path == "/api/batch":
                    return self._json(200, app.batch_index())
                if path.startswith("/api/batch/"):
                    number = path.removeprefix("/api/batch/")
                    env = app.batch.get(number)
                    if env is None:
                        return self._json(404, {"error": "not_in_batch",
                                                "message": f"{number} is not in the loaded batch"})
                    return self._json(200, env)
                if path.startswith("/snapshot/"):
                    return self._snapshot(path.removeprefix("/snapshot/"))
                if path == "/healthz":
                    return self._json(200, {"ok": True})
                return self._json(404, {"error": "not_found", "message": "No such page"})
            except Exception as exc:  # the UI must answer with a readable error, not hang
                return self._json(500, {"error": "internal_error",
                                        "message": f"{type(exc).__name__}: {exc}"})

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def _static(self, name: str) -> None:
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._json(404, {"error": "not_found", "message": "No such file"})
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def _company(self, raw: str, query) -> None:
            number = normalise(raw)
            error = validation_error(number)
            if error:
                return self._json(400, {"error": "invalid_organisation_number",
                                        "message": error[0].upper() + error[1:] + "."})
            if query.get("source") == ["batch"] and number in app.batch:
                return self._json(200, app.batch[number])
            env = app.company(number, refresh=query.get("refresh") == ["1"])
            self._json(200, env)

        def _snapshot(self, sha: str) -> None:
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                return self._json(400, {"error": "bad_hash", "message": "Invalid snapshot hash"})
            body = app.store.read_snapshot(sha)
            if body is None:
                return self._json(404, {"error": "not_found", "message": "Snapshot not stored"})
            # Always plain text: stored pages are shown as source, never rendered as HTML.
            self._send(200, body, "text/plain; charset=utf-8")

    return Handler


def serve(host: str, port: int, state_dir: str, batch: str | None, web: bool = True) -> int:
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    app = App(state_dir, batch, web=web)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    print(f"Signalpost UI on http://{host}:{port}/ (state: {state_dir}"
          + (f", batch: {batch} with {len(app.batch)} companies" if batch else "") + ")",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

