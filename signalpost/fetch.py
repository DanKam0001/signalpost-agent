"""HTTP fetching with polite per-host rate limits, retries, deadlines and size caps.

Every response (or failure) becomes a `Snapshot`: the raw bytes, their SHA-256 and the retrieval
time, so every published claim can point at exactly what was fetched.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from . import __version__
from .urlsafety import UrlPolicy, UrlRefused

USER_AGENT = (f"SignalpostEvidenceAgent/{__version__} "
              "(registry-first company research; obeys robots.txt)")
# Bodies of 403s produced by a local egress proxy (not by the source): the environment, not the
# company's site, refused the request, so it must not be reported as the source blocking us.
EGRESS_BLOCK_MARKERS = (b"Blocked by network policy", b"Blocked by org policy",
                        b"Blocked by local rule")
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_REDIRECTS = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class BudgetExhausted(Exception):
    """The caller's deadline passed before the request could be made."""


@dataclass
class RawResponse:
    status: int | None
    headers: dict[str, str]
    body: bytes
    error: str | None = None
    truncated: bool = False


@dataclass
class Snapshot:
    url: str
    source: str
    retrieved_at: str
    status: int | None = None
    final_url: str = ""
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    redirects: list[str] = field(default_factory=list)
    error: str | None = None
    attempts: int = 0
    elapsed_ms: int = 0
    truncated: bool = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def egress_blocked(self) -> bool:
        return self.status == 403 and any(m in self.body[:2000] for m in EGRESS_BLOCK_MARKERS)

    @property
    def refused(self) -> bool:
        """The source actively refused us (as opposed to not having the record)."""
        if self.egress_blocked:
            return False
        return self.status in (401, 403, 429) or (self.error or "").startswith("robots")

    def json(self):
        """Parse the body keeping decimals exact (financial values must not be rounded)."""
        return json.loads(self.body.decode("utf-8"), parse_float=Decimal)

    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def outcome(self) -> str:
        if self.error:
            return self.error.split(":", 1)[0]
        return f"http_{self.status}"


class Operations:
    """Per-company (or per-run) request accounting. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.bytes = 0
        self.per_source: Counter[str] = Counter()
        self.per_host: Counter[str] = Counter()

    def record(self, source: str, host: str, nbytes: int) -> None:
        with self._lock:
            self.requests += 1
            self.bytes += nbytes
            self.per_source[source] += 1
            self.per_host[host] += 1


class RateLimiter:
    """Minimum interval between requests per key (host or host+path prefix)."""

    def __init__(self, intervals: dict[str, float], default_interval: float):
        self.intervals = intervals
        self.default_interval = default_interval
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def key_for(self, url: str) -> str:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        for key in self.intervals:
            if "/" in key and f"{host}{parts.path}".startswith(key):
                return key
        return host

    def reserve(self, url: str, max_wait: float) -> float:
        """Reserve the next slot; return the seconds to sleep, or raise if too far away."""
        key = self.key_for(url)
        interval = self.intervals.get(key, self.default_interval)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next.get(key, 0.0))
            wait = slot - now
            if wait > max_wait:
                raise BudgetExhausted(f"rate_limit_wait {wait:.1f}s exceeds {max_wait:.1f}s")
            self._next[key] = slot + interval
        return wait

    def push_back(self, url: str, seconds: float) -> None:
        """The server asked us to slow down (Retry-After / rate-limit header)."""
        key = self.key_for(url)
        with self._lock:
            self._next[key] = max(self._next.get(key, 0.0), time.monotonic() + seconds)


class HttpxTransport:
    def __init__(self, user_agent: str = USER_AGENT, trust_env: bool = True):
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "nb,no;q=0.9,en;q=0.8"},
            follow_redirects=False, trust_env=trust_env,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))

    def __call__(self, url: str, timeout: float, max_bytes: int, accept: str) -> RawResponse:
        try:
            with self.client.stream("GET", url, timeout=timeout, headers={"Accept": accept}) as resp:
                chunks, size, truncated = [], 0, False
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        truncated = True
                        break
                body = b"".join(chunks)[:max_bytes]
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return RawResponse(resp.status_code, headers, body, truncated=truncated)
        except httpx.TimeoutException:
            return RawResponse(None, {}, b"", error="timeout")
        except httpx.HTTPError as exc:
            return RawResponse(None, {}, b"", error=f"connection_error: {type(exc).__name__}")

    def close(self) -> None:
        self.client.close()


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    value = headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


class Fetcher:
    def __init__(self, transport=None, policy: UrlPolicy | None = None,
                 rate_intervals: dict[str, float] | None = None, default_interval: float = 1.0,
                 timeout: float = 15.0, sleep=time.sleep):
        self.transport = transport or HttpxTransport()
        self.policy = policy or UrlPolicy()
        self.limiter = RateLimiter(rate_intervals or {}, default_interval)
        self.timeout = timeout
        self.sleep = sleep
        self.totals = Operations()

    def get(self, url: str, *, source: str, ops: Operations, deadline: float,
            retries: int = 3, max_bytes: int = 5_000_000, max_wait: float | None = None,
            accept: str = "application/json", check_policy: bool = True,
            allow_hop=None, timeout: float | None = None) -> Snapshot:
        """Fetch `url`, following redirects (each hop re-checked), never past `deadline`.

        `allow_hop(url)` may veto a redirect target before it is requested (robots.txt).
        """
        snap = Snapshot(url=url, source=source, retrieved_at=utc_now())
        started = time.monotonic()
        current = url
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                if check_policy:
                    self.policy.check(current)
                raw = self._get_with_retries(current, source, ops, deadline, retries, max_bytes,
                                             max_wait, accept, snap, timeout or self.timeout)
                if raw.status in (301, 302, 303, 307, 308) and raw.headers.get("location"):
                    snap.redirects.append(current)
                    current = urljoin(current, raw.headers["location"])
                    if allow_hop is not None and not allow_hop(current):
                        snap.error = "robots_disallowed: redirect target"
                        break
                    continue
                snap.status, snap.headers, snap.body = raw.status, raw.headers, raw.body
                snap.error, snap.truncated = raw.error, raw.truncated
                break
            else:
                snap.error = "too_many_redirects"
        except UrlRefused as exc:
            snap.error = f"url_refused: {exc}"
        except BudgetExhausted as exc:
            snap.error = f"time_budget: {exc}"
        snap.final_url = current
        snap.retrieved_at = utc_now()
        snap.elapsed_ms = int((time.monotonic() - started) * 1000)
        return snap

    def _get_with_retries(self, url, source, ops, deadline, retries, max_bytes, max_wait,
                          accept, snap, request_timeout) -> RawResponse:
        attempt = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                raise BudgetExhausted("deadline reached")
            wait = self.limiter.reserve(url, min(max_wait if max_wait is not None else remaining,
                                                 remaining - 0.5))
            if wait > 0:
                self.sleep(wait)
            timeout = max(1.0, min(request_timeout, deadline - time.monotonic()))
            raw = self.transport(url, timeout, max_bytes, accept)
            attempt += 1
            snap.attempts += 1
            host = (urlsplit(url).hostname or "").lower()
            ops.record(source, host, len(raw.body))
            self.totals.record(source, host, len(raw.body))
            retry_after = _retry_after_seconds(raw.headers)
            if raw.headers.get("x-rate-limit-remaining") == "0":
                self.limiter.push_back(url, retry_after if retry_after is not None else 60.0)
            retryable = raw.status in RETRY_STATUSES or raw.error in ("timeout",) or (
                raw.error or "").startswith("connection_error")
            if not retryable or attempt > retries:
                return raw
            backoff = retry_after if retry_after is not None else 0.5 * 2 ** (attempt - 1)
            backoff = min(30.0, backoff) + random.uniform(0, 0.25)
            if time.monotonic() + backoff >= deadline - 1.0:
                return raw
            self.limiter.push_back(url, backoff)
