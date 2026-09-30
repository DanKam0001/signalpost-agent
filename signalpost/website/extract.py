"""Facts extracted from a verified company site: description, brand, contact points, social
profiles, careers page, job postings and dated news. Structured data first (JSON-LD, OpenGraph),
then DOM links, then feeds and sitemaps. Every fact carries page URL, hash, date and selector."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import Tag

from ..model import AVAILABLE, COMPANY_OWNED, NOT_AVAILABLE, Claim, Collector, Evidence, short_hash
from ..registry import S_IDENTITY, S_WEBSITE
from .pages import (Page, clean, css_path, iso_date, jsonld_types, parse_feed, parse_sitemap,
                    registered_domain)

S_HIRING = "hiring_and_activity"
MAX_JOBS = 50
MAX_NEWS = 10
MIN_DESCRIPTION = 30

SOCIAL_PATTERNS = (
    ("LinkedIn", re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/(company|school|showcase)/"
                            r"[^/?#]+", re.I)),
    ("Facebook", re.compile(r"^https?://(www\.|m\.|nb-no\.)?facebook\.com/(?!sharer|share|dialog|"
                            r"plugins|tr\b|login|groups/?$)[^/?#]+", re.I)),
    ("Instagram", re.compile(r"^https?://(www\.)?instagram\.com/(?!p/|explore|accounts)[^/?#]+",
                             re.I)),
    ("YouTube", re.compile(r"^https?://(www\.)?youtube\.com/(channel/|c/|user/|@)[^/?#]+", re.I)),
    ("X", re.compile(r"^https?://(www\.)?(twitter|x)\.com/(?!intent|share|home|search|hashtag)"
                     r"[^/?#]+", re.I)),
    ("TikTok", re.compile(r"^https?://(www\.)?tiktok\.com/@[^/?#]+", re.I)),
    ("Vimeo", re.compile(r"^https?://(www\.)?vimeo\.com/(?!\d+$)[a-z][^/?#]*", re.I)),
)
GENERIC_MAILBOXES = {"post", "info", "kontakt", "contact", "firmapost", "mail", "salg", "sales",
                     "support", "office", "kontor", "kundeservice", "hello", "hei", "service",
                     "admin", "resepsjon", "reception", "booking", "ordre", "order", "jobb",
                     "hr", "karriere", "careers", "presse", "press", "media", "invoice",
                     "faktura", "regnskap", "okonomi", "post.no"}
ATS_DOMAINS = ("webcruiter", "jobylon", "teamtailor", "recman", "easycruit", "hrmanager",
               "reachmee", "jobbnorge", "varbi", "workday", "smartrecruiters", "lever.co",
               "greenhouse.io", "talentech", "cvpartner", "finn.no/job")
JOB_PATH = re.compile(r"/(stilling|stillinger|ledige-stillinger|jobb|jobs?|vacanc|career|karriere)"
                      r"[^?#]*/[\w\-%]{6,}", re.I)
GENERIC_LINK_TEXT = re.compile(r"^(se |vis |les |alle |ledige stillinger|jobb|karriere|careers?|"
                               r"jobs?|apply|søk|send|mer|more|read|open positions|stillinger)",
                               re.I)
NEWS_PATH = re.compile(r"/(nyheter|news|aktuelt|presse|press|blogg?|artikler|media)/[\w\-%]{6,}",
                       re.I)


class HiringResult:
    def __init__(self) -> None:
        self.careers_checked = False
        self.careers_url: str | None = None
        self.jobs = 0
        self.news = 0

    def hiring_state(self) -> tuple[str, str]:
        parts = []
        if self.jobs:
            parts.append(f"{self.jobs} job posting(s) on the company's own website")
        elif self.careers_checked:
            parts.append(f"careers page checked ({self.careers_url}): no job postings found")
        else:
            parts.append("no careers page found on the verified website")
        if self.news:
            parts.append(f"{self.news} dated news/activity item(s) on the company's own website")
        else:
            parts.append("no dated news items found on the verified website")
        state = AVAILABLE if (self.jobs or self.news) else NOT_AVAILABLE
        return state, "; ".join(parts)


def _job_key(url: str, title: str) -> str:
    """The same posting found as JSON-LD and as a listing link counts once."""
    return short_hash(f"{_normal_link(url)}|{clean(title).casefold()}")


def _normal_link(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("https", p.netloc.lower().removeprefix("www.").removeprefix("m."),
                       path, "", ""))


class Extractor:
    def __init__(self, collector: Collector, crawler, entity: dict, site_url: str,
                 site_confidence: float):
        self.c = collector
        self.crawler = crawler
        self.entity = entity
        self.site_url = site_url
        self.site_domain = registered_domain(urlsplit(site_url).hostname or "")
        self.conf = site_confidence
        self.result = HiringResult()

    @staticmethod
    def evidence(page: Page, el: Tag | None, span: str | None, method: str,
                 record_date: str | None = None) -> Evidence:
        return Evidence(source_url=page.url, source_class=COMPANY_OWNED,
                        retrieved_at=page.retrieved_at, content_sha256=page.sha256,
                        extraction_method=method,
                        record_date=record_date or page.page_date(),
                        record_date_field="page date" if (record_date or page.page_date()) else None,
                        css_selector=_css(el), claim_span=clean(span)[:300] if span else None)

    def _add(self, section, field, label, value, page, el, span, method, identity="",
             record_date=None, **extra) -> None:
        ev = self.evidence(page, el, span, method, record_date)
        self.c.add(Claim(field=field, label=label, section=section, value=value,
                         availability=AVAILABLE, identity=identity, confidence=self.conf,
                         evidence=[ev], effective_date=record_date, extra=extra))

    def run(self, pages: list[Page]) -> HiringResult:
        home = pages[0]
        self._description(home)
        self._brand(home)
        seen_social: set[str] = set()
        seen_jobs: set[str] = set()
        seen_news: set[str] = set()
        for page in pages:
            self._contacts(page)
            self._social(page, seen_social)
            self._jobposting_jsonld(page, seen_jobs)
            self._news_jsonld(page, seen_news)
            if page.kind == "careers":
                self._careers(page, seen_jobs)
            if page.kind == "news":
                self._news_listing(page, seen_news)
        self._feeds(home, seen_news)
        self._sitemap(home, seen_news)
        self.result.jobs = len(seen_jobs)
        self.result.news = len(seen_news)
        return self.result

    # -- identity-adjacent facts -----------------------------------------------------------
    def _description(self, home: Page) -> None:
        for item, script in home.jsonld():
            if jsonld_types(item) & {"Organization", "Corporation", "LocalBusiness"} and \
                    isinstance(item.get("description"), str) and \
                    len(clean(item["description"])) >= MIN_DESCRIPTION:
                text = clean(item["description"])
                self._add(S_WEBSITE, "site_description", "Company's own description", text, home,
                          script, text, "site-jsonld-v1")
                return
        hit = home.meta("og:description", "description")
        if hit and len(hit[0]) >= MIN_DESCRIPTION:
            self._add(S_WEBSITE, "site_description", "Company's own description", hit[0], home,
                      hit[1], hit[0], "site-meta-v1")

    def _brand(self, home: Page) -> None:
        legal = clean(self.entity.get("navn") or "").casefold()
        for item, script in home.jsonld():
            if jsonld_types(item) & {"Organization", "Corporation", "LocalBusiness"} and \
                    isinstance(item.get("name"), str) and clean(item["name"]):
                name = clean(item["name"])
                if name.casefold() != legal:
                    self._add(S_IDENTITY, "brand_name", "Public brand name (own website)", name,
                              home, script, name, "site-jsonld-v1")
                return
        hit = home.meta("og:site_name")
        if hit and hit[0].casefold() != legal and len(hit[0]) <= 80:
            self._add(S_IDENTITY, "brand_name", "Public brand name (own website)", hit[0], home,
                      hit[1], hit[0], "site-meta-v1")

    def _contacts(self, page: Page) -> None:
        for url, text, a in page.links():
            if url.startswith("tel:"):
                number = re.sub(r"[^\d+]", "", url[4:])
                if 8 <= len(re.sub(r"\D", "", number)) <= 12:
                    self._add(S_WEBSITE, "site_phone", "Phone on own website", number, page, a,
                              text or number, "site-links-v1", identity=number)
            elif url.startswith("mailto:"):
                address = url[7:].split("?")[0].strip().lower()
                local, _, domain = address.partition("@")
                if domain and local in GENERIC_MAILBOXES and \
                        registered_domain(domain) == self.site_domain:
                    self._add(S_WEBSITE, "site_email", "Company e-mail on own website", address,
                              page, a, text or address, "site-links-v1", identity=address)

    def _social(self, page: Page, seen: set[str]) -> None:
        links = [(url, text, a) for url, text, a in page.links()]
        for item, script in page.jsonld():
            same = item.get("sameAs")
            for url in (same if isinstance(same, list) else [same] if same else []):
                if isinstance(url, str):
                    links.append((url, "", script))
        for url, text, el in links:
            for platform, pattern in SOCIAL_PATTERNS:
                m = pattern.match(url)
                if not m:
                    continue
                profile = _normal_link(m.group(0))
                if profile in seen:
                    break
                seen.add(profile)
                self._add(S_WEBSITE, "social_profile", f"{platform} profile (linked from own site)",
                          {"platform": platform, "url": profile}, page, el, text or url,
                          "site-links-v1", identity=profile)
                break

    # -- hiring ----------------------------------------------------------------------------
    def _jobposting_jsonld(self, page: Page, seen: set[str]) -> None:
        for item, script in page.jsonld():
            if "JobPosting" not in jsonld_types(item) or len(seen) >= MAX_JOBS:
                continue
            title = clean(str(item.get("title") or item.get("name") or ""))
            if not title:
                continue
            url = item.get("url") if isinstance(item.get("url"), str) else page.url
            key = _job_key(urljoin(page.url, url), title)
            if key in seen:
                continue
            seen.add(key)
            place = item.get("jobLocation")
            place = place[0] if isinstance(place, list) and place else place
            locality = None
            if isinstance(place, dict) and isinstance(place.get("address"), dict):
                locality = place["address"].get("addressLocality")
            posted = iso_date(str(item.get("datePosted") or "")) or None
            value = {"title": title, "url": urljoin(page.url, url), "date_posted": posted,
                     "valid_through": iso_date(str(item.get("validThrough") or "")),
                     "employment_type": item.get("employmentType"), "location": locality,
                     "source": "JobPosting structured data"}
            self._add(S_HIRING, "job_posting", "Job posting (own website)", value, page, script,
                      title, "site-jsonld-v1", identity=key, record_date=posted)

    def _careers(self, page: Page, seen: set[str]) -> None:
        self.result.careers_checked = True
        self.result.careers_url = page.url
        self._add(S_HIRING, "careers_page", "Careers page (own website)", page.url, page, None,
                  page.soup.title.get_text() if page.soup.title else None, "site-links-v1")
        for url, text, a in page.links():
            if len(seen) >= MAX_JOBS:
                break
            if not (8 <= len(text) <= 120) or GENERIC_LINK_TEXT.match(text):
                continue
            same_site = registered_domain(urlsplit(url).hostname or "") == self.site_domain
            is_ats = any(d in url.lower() for d in ATS_DOMAINS)
            if not (is_ats or (same_site and JOB_PATH.search(urlsplit(url).path))):
                continue
            key = _job_key(url, text)
            if key in seen:
                continue
            seen.add(key)
            date = _nearby_date(a)
            value = {"title": text, "url": url, "date_posted": date, "valid_through": None,
                     "employment_type": None, "location": None,
                     "source": "listing on the company's careers page"}
            self._add(S_HIRING, "job_posting", "Job posting (own website)", value, page, a, text,
                      "site-careers-links-v1", identity=key, record_date=date)

    # -- dated activity --------------------------------------------------------------------
    def _news(self, page: Page, el, title: str, url: str, date: str | None, method: str,
              seen: set[str]) -> None:
        if len(seen) >= MAX_NEWS or not title or not date:
            return
        key = _normal_link(urljoin(page.url, url or page.url))
        if key in seen:
            return
        seen.add(key)
        value = {"title": title, "url": urljoin(page.url, url or page.url), "date": date}
        if method == "site-sitemap-lastmod-v1":
            value["title_source"] = "derived from the URL (the sitemap has no titles)"
        self._add(S_HIRING, "news_item", "Dated news item (own website)", value, page, el, title,
                  method, identity=key, record_date=date)

    def _news_jsonld(self, page: Page, seen: set[str]) -> None:
        for item, script in page.jsonld():
            if jsonld_types(item) & {"NewsArticle", "BlogPosting", "Article", "PressRelease"}:
                title = clean(str(item.get("headline") or item.get("name") or ""))
                date = iso_date(str(item.get("datePublished") or item.get("dateModified") or ""))
                url = item.get("url") if isinstance(item.get("url"), str) else page.url
                self._news(page, script, title, url, date, "site-jsonld-v1", seen)

    def _news_listing(self, page: Page, seen: set[str]) -> None:
        for container in page.soup.find_all(["article", "li", "div"]):
            if len(seen) >= MAX_NEWS:
                return
            time_tag = container.find("time")
            link = container.find("a", href=True)
            if time_tag is None or link is None:
                continue
            if container.find(["article"]) is not None and container.name != "article":
                continue  # use the innermost article
            date = iso_date(time_tag.get("datetime") or time_tag.get_text())
            heading = container.find(["h1", "h2", "h3", "h4"])
            title = clean((heading or link).get_text(" "))
            if 8 <= len(title) <= 200:
                self._news(page, container, title, link["href"], date, "site-news-listing-v1",
                           seen)

    def _feeds(self, home: Page, seen: set[str]) -> None:
        for link in home.soup.find_all("link", attrs={"type": re.compile("rss|atom")}):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(home.url, href)
            if registered_domain(urlsplit(url).hostname or "") != self.site_domain:
                continue
            snap = self.crawler.fetch_aux(url, "feed")
            if snap is None:
                continue
            feed_page = _AuxPage(snap)
            for item in parse_feed(snap.text()):
                self._news(feed_page, None, item["title"], item["url"], item["date"],
                           "site-feed-v1", seen)
            return

    def _sitemap(self, home: Page, seen: set[str]) -> None:
        """Dated news URLs from the sitemap (title taken from the URL slug)."""
        if len(seen) >= MAX_NEWS:
            return
        urls = self.crawler.robots_sitemaps(home.url) or [home.url.rstrip("/") + "/sitemap.xml"]
        snap = self.crawler.fetch_aux(urls[0], "sitemap")
        if snap is None:
            return
        entries, children = parse_sitemap(snap.text())
        if not entries and children:
            news_child = next((c for c in children if re.search(r"news|nyhet|post|artik", c, re.I)),
                              None)
            if news_child:
                snap = self.crawler.fetch_aux(news_child, "sitemap")
                entries = parse_sitemap(snap.text())[0] if snap is not None else []
        page = _AuxPage(snap) if snap is not None else None
        dated = sorted((e for e in entries if e["lastmod"] and NEWS_PATH.search(
            urlsplit(e["url"]).path)), key=lambda e: e["lastmod"], reverse=True)
        for entry in dated[:MAX_NEWS]:
            slug = urlsplit(entry["url"]).path.rstrip("/").rsplit("/", 1)[-1]
            title = re.sub(r"[-_]+", " ", slug).strip().capitalize()
            if page is not None:
                self._news(page, None, title, entry["url"], entry["lastmod"],
                           "site-sitemap-lastmod-v1", seen)


class _AuxPage:
    """Minimal page-like wrapper so feed/sitemap facts get the same evidence shape."""

    def __init__(self, snap):
        self.url = snap.final_url or snap.url
        self.retrieved_at = snap.retrieved_at
        self.sha256 = snap.sha256

    def page_date(self):
        return None


def _nearby_date(el: Tag) -> str | None:
    node = el
    for _ in range(3):
        if node is None:
            return None
        time_tag = node.find("time") if isinstance(node, Tag) else None
        if time_tag is not None:
            return iso_date(time_tag.get("datetime") or time_tag.get_text())
        node = node.parent
    return None


def _css(el) -> str | None:
    return css_path(el) if isinstance(el, Tag) else None
