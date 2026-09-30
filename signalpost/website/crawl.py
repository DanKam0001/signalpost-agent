"""Bounded, polite, deterministic crawl of one candidate site.

robots.txt is fetched first and obeyed (RFC 9309: a 4xx robots file means no restrictions, a 5xx
or unreachable robots file means stay out). Static HTML only — no JavaScript is executed. Every
page goes through the fetcher, so the URL safety policy is applied to each hop.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from ..fetch import Fetcher, Operations, Snapshot
from .pages import Page, iso_date

ROBOTS_AGENT = "SignalpostEvidenceAgent"
MAX_PAGES = 10              # HTML pages per site (robots.txt, sitemap and feeds not included)
MAX_AUX = 4                 # robots.txt, sitemap(s), feed
MAX_PAGE_BYTES = 1_500_000
MAX_CRAWL_DELAY = 5.0
SITE_TIMEOUT = 10.0         # seconds per request; a hanging site fails fast, not the batch
HTML_TYPES = ("text/html", "application/xhtml+xml", "")


class CrawlStop(Exception):
    pass


def _host_root(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "", "", ""))


def classify(snap: Snapshot) -> str:
    """Crawl outcome for a snapshot: ok, blocked, timeout, unreachable, not_found, error, ..."""
    if snap.error:
        err = snap.error
        if err.startswith("robots"):
            return "robots_disallowed"
        if err.startswith("url_refused"):
            return "unreachable" if "dns_" in err else "url_refused"
        if err.startswith("time_budget"):
            return "time_budget"
        if err == "timeout":
            return "timeout"
        return "unreachable"
    if snap.egress_blocked:
        return "egress_blocked"
    if snap.status in (401, 403, 429, 451):
        return "blocked"
    if snap.status in (404, 410):
        return "not_found"
    if snap.status and snap.status >= 500:
        return "error"
    if snap.status and 200 <= snap.status < 300:
        return "ok"
    return "error"


class SiteCrawler:
    def __init__(self, fetcher: Fetcher, ops: Operations, deadline_fn, keep_snapshot):
        self.fetcher = fetcher
        self.ops = ops
        self.deadline_fn = deadline_fn
        self.keep_snapshot = keep_snapshot
        self.robots: dict[str, RobotFileParser | None] = {}
        self.robots_state: dict[str, str] = {}
        self.pages_fetched = 0
        self.aux_fetched = 0
        self.snapshots: list[Snapshot] = []

    def _get(self, url: str, source: str, accept: str, check_robots: bool = True) -> Snapshot:
        return self.fetcher.get(url, source=source, ops=self.ops, deadline=self.deadline_fn(),
                                retries=0, max_bytes=MAX_PAGE_BYTES, accept=accept,
                                timeout=SITE_TIMEOUT,
                                allow_hop=self._hop_allowed if check_robots else None)

    def _hop_allowed(self, url: str) -> bool:
        try:
            return self.allowed(url)
        except CrawlStop:
            return False

    def _robots_for(self, url: str) -> RobotFileParser | None:
        root = _host_root(url)
        if root in self.robots:
            return self.robots[root]
        snap = self._get(root + "/robots.txt", "site.robots", "text/plain,*/*;q=0.5",
                         check_robots=False)
        self.aux_fetched += 1
        self.snapshots.append(snap)
        outcome = classify(snap)
        parser: RobotFileParser | None = RobotFileParser()
        if outcome == "ok":
            self.keep_snapshot(snap)
            parser.parse(snap.text().splitlines())
            self.robots_state[root] = "parsed"
            delay = parser.crawl_delay(ROBOTS_AGENT)
            if delay:
                host = urlsplit(url).hostname or ""
                self.fetcher.limiter.intervals[host] = min(float(delay), MAX_CRAWL_DELAY)
        elif snap.status and 400 <= snap.status < 500 and snap.status != 429:
            parser.parse([])                  # RFC 9309: unavailable robots.txt → allow
            self.robots_state[root] = f"http_{snap.status}_allow_all"
        elif outcome == "time_budget":
            raise CrawlStop("time_budget")
        else:
            parser = None                     # unreachable/5xx → treat as complete disallow
            self.robots_state[root] = f"unavailable_{outcome}"
        self.robots[root] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return parser is not None and parser.can_fetch(ROBOTS_AGENT, url)

    def robots_sitemaps(self, url: str) -> list[str]:
        parser = self.robots.get(_host_root(url))
        return list(parser.site_maps() or []) if parser else []

    def fetch_page(self, url: str, kind: str) -> tuple[Page | None, Snapshot | None, str]:
        """Fetch one HTML page. Returns (page, snapshot, outcome)."""
        if self.pages_fetched >= MAX_PAGES:
            return None, None, "page_cap"
        if time.monotonic() >= self.deadline_fn() - 1:
            return None, None, "time_budget"
        try:
            if not self.allowed(url):
                root = _host_root(url)
                state = self.robots_state.get(root, "")
                return None, None, ("robots_disallowed" if state == "parsed"
                                    else f"robots_{state or 'unavailable'}")
        except CrawlStop:
            return None, None, "time_budget"
        snap = self._get(url, f"site.{kind}", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5")
        self.pages_fetched += 1
        self.snapshots.append(snap)
        outcome = classify(snap)
        if outcome != "ok":
            return None, snap, outcome
        if snap.content_type not in HTML_TYPES:
            return None, snap, "not_html"
        self.keep_snapshot(snap)
        page = Page(url=snap.final_url or url, requested_url=url, html=snap.text(),
                    sha256=snap.sha256, retrieved_at=snap.retrieved_at,
                    last_modified=iso_date(snap.headers.get("last-modified")), kind=kind)
        return page, snap, "ok"

    def fetch_aux(self, url: str, kind: str) -> Snapshot | None:
        """Fetch a sitemap or feed (XML); counted separately from HTML pages."""
        if self.aux_fetched >= MAX_AUX or time.monotonic() >= self.deadline_fn() - 1:
            return None
        try:
            if not self.allowed(url):
                return None
        except CrawlStop:
            return None
        snap = self._get(url, f"site.{kind}",
                         "application/xml,text/xml,application/rss+xml,application/atom+xml")
        self.aux_fetched += 1
        self.snapshots.append(snap)
        if classify(snap) != "ok":
            return None
        self.keep_snapshot(snap)
        return snap
