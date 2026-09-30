"""HTML/XML parsing helpers: structured data, meta tags, links, CSS paths and text spans."""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

_WS = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def clean(text: str | None) -> str:
    return _WS.sub(" ", text or "").strip()


def registered_domain(host: str) -> str:
    """Good-enough registrable domain for .no/.com style hosts (strip www and subdomains)."""
    host = (host or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    second_level = {"co.uk", "com.au", "co.nz", "priv.no", "kommune.no", "org.uk"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in second_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/", "", ""))


def normalise_url(url: str) -> str:
    p = urlsplit(url)
    path = p.path or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def css_path(el: Tag) -> str:
    parts = []
    node = el
    while isinstance(node, Tag) and node.name not in ("[document]", "html"):
        ident = node.get("id")
        if ident and re.fullmatch(r"[A-Za-z][\w\-]*", ident):
            parts.append(f"{node.name}#{ident}")
            break
        parent = node.parent
        if isinstance(parent, Tag):
            same = [s for s in parent.find_all(node.name, recursive=False)]
            if len(same) > 1:
                parts.append(f"{node.name}:nth-of-type({same.index(node) + 1})")
            else:
                parts.append(node.name)
        else:
            parts.append(node.name)
        node = parent
    return " > ".join(reversed(parts))


@dataclass
class Page:
    url: str                 # final URL after redirects
    requested_url: str
    html: str
    sha256: str
    retrieved_at: str
    last_modified: str | None = None
    kind: str = "page"       # home/about/contact/careers/news/leadership/investor/other
    soup: BeautifulSoup = field(init=False, repr=False)

    def __post_init__(self):
        self.soup = BeautifulSoup(self.html, "html.parser")
        for bad in self.soup(["script", "style", "noscript", "template"]):
            if bad.name == "script" and "ld+json" in (bad.get("type") or ""):
                continue
            bad.decompose()

    @property
    def text(self) -> str:
        return clean(self.soup.get_text(" "))

    def meta(self, *names: str) -> tuple[str, Tag] | None:
        for name in names:
            tag = self.soup.find("meta", attrs={"property": name}) or \
                self.soup.find("meta", attrs={"name": name})
            if tag and clean(tag.get("content")):
                return clean(tag.get("content")), tag
        return None

    def jsonld(self) -> list[tuple[dict, Tag]]:
        found = []
        for script in self.soup.find_all("script", attrs={"type": re.compile("ld\\+json")}):
            try:
                data = json.loads(script.string or script.get_text() or "")
            except (ValueError, TypeError):
                continue
            stack = data if isinstance(data, list) else [data]
            while stack:
                item = stack.pop(0)
                if isinstance(item, dict):
                    if "@graph" in item and isinstance(item["@graph"], list):
                        stack.extend(item["@graph"])
                    found.append((item, script))
                elif isinstance(item, list):
                    stack.extend(item)
        return found

    def links(self) -> list[tuple[str, str, Tag]]:
        out = []
        for a in self.soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:")):
                continue
            out.append((urljoin(self.url, href), clean(a.get_text(" ")), a))
        return out

    def page_date(self) -> str | None:
        hit = self.meta("article:modified_time", "article:published_time", "og:updated_time")
        if hit:
            return hit[0][:10]
        for item, _ in self.jsonld():
            for key in ("dateModified", "datePublished"):
                if isinstance(item.get(key), str):
                    return item[key][:10]
        return self.last_modified

    def element_with_text(self, needle: str) -> Tag | None:
        """Smallest element whose text contains `needle` (whitespace-insensitive)."""
        target = clean(needle)
        for node in self.soup.find_all(string=True):
            if target in clean(node):
                return node.parent
        best, best_len = None, float("inf")
        for tag in self.soup.find_all(True):
            text = clean(tag.get_text(" "))
            if target in text and len(text) < best_len:
                best, best_len = tag, len(text)
        return best


def jsonld_types(item: dict) -> set[str]:
    t = item.get("@type")
    if isinstance(t, list):
        return {str(x) for x in t}
    return {str(t)} if t else set()


def iso_date(value: str | None) -> str | None:
    """Normalise ISO-8601 or RFC-822 dates to YYYY-MM-DD; None when unparseable."""
    if not value:
        return None
    value = value.strip()
    m = _ISO_DATE.match(value)
    if m:
        return m.group(0)
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _xml_root(xml_text: str):
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str)
                                      else xml_text)
    except ElementTree.ParseError:
        return None
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _child_text(node, *names: str) -> str:
    for name in names:
        child = node.find(name)
        if child is not None and clean(child.text):
            return clean(child.text)
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 / Atom items as {title, url, date}."""
    root = _xml_root(xml_text)
    if root is None:
        return []
    items = []
    for node in list(root.iter("item")) + list(root.iter("entry")):
        title = _child_text(node, "title")
        link = _child_text(node, "link")
        if not link:
            link_el = node.find("link")
            link = link_el.get("href", "") if link_el is not None else ""
        date = iso_date(_child_text(node, "pubDate", "published", "updated", "date"))
        if title:
            items.append({"title": title, "url": link, "date": date})
    return items


def parse_sitemap(xml_text: str) -> tuple[list[dict], list[str]]:
    """Returns (url entries with lastmod, child sitemap URLs)."""
    root = _xml_root(xml_text)
    if root is None:
        return [], []
    children = [_child_text(s, "loc") for s in root.iter("sitemap") if _child_text(s, "loc")]
    entries = [{"url": _child_text(u, "loc"), "lastmod": iso_date(_child_text(u, "lastmod"))}
               for u in root.iter("url") if _child_text(u, "loc")]
    return entries, children
