"""Company-owned sources: candidate website → exact-entity proof → bounded crawl → facts.

Facts from a site are published only after the site is tied to the organisation number (see
`identity.py`). Search results are never used; candidates come from the registry record, the
registered e-mail domain, the input row, and two conservative guesses from the legal name that
must show the organisation number on the site to count.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ..fetch import Fetcher, Operations, utc_now
from ..model import (AMBIGUOUS, AVAILABLE, BLOCKED, COMPANY_OWNED, FAILED, NOT_AVAILABLE, Claim,
                     Collector, Evidence)
from ..registry import S_WEBSITE
from .crawl import SiteCrawler
from .extract import Extractor
from .identity import Verdict, verify
from .pages import Page, origin, registered_domain

S_HIRING = "hiring_and_activity"

GENERIC_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "hotmail.co.uk", "outlook.com",
    "outlook.no", "live.com", "live.no", "msn.com", "yahoo.com", "yahoo.no", "ymail.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "gmx.com", "gmx.net", "mail.com", "email.com",
    "protonmail.com", "proton.me", "online.no", "broadpark.no", "frisurf.no", "getmail.no",
    "start.no", "c2i.net", "chello.no", "lyse.net", "altibox.no", "bluezone.no", "tele2.no",
    "netcom.no", "telenor.no", "epost.no", "nextgentel.no", "ebnett.no", "haugnett.no",
    "enivest.net", "eidsiva.net", "bredband.net", "tdcadsl.no", "sensewave.com", "vikenfiber.no",
    "loqal.no", "post.com", "hotmail.se", "outlook.dk", "live.se", "kpnmail.nl",
}
_FORM_WORDS = {"as", "asa", "ans", "da", "sa", "ba", "enk", "nuf", "ks", "sf", "iks", "avd",
               "norge", "norway"}
_TRANSLIT = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "ä": "a", "ö": "o", "ü": "u",
                           "é": "e", "&": ""})

# Pages we try to reach from the homepage, by link keywords (Norwegian and English).
PAGE_KINDS = (
    ("contact", ("kontakt", "contact")),
    ("about", ("om-oss", "om oss", "about", "hvem-er-vi", "om-selskapet", "company", "selskapet")),
    ("careers", ("karriere", "career", "jobb", "jobs", "stilling", "ledige", "rekrutter",
                 "work-with-us", "join-us", "vacanc")),
    ("news", ("nyheter", "news", "aktuelt", "presse", "press", "media", "blogg", "blog")),
    ("leadership", ("ledelse", "leadership", "management", "styret", "board", "ansatte", "team")),
    ("investor", ("investor", "/ir/", "aksjon")),
)
GUESSED_PATHS = {"contact": ["/kontakt"], "about": ["/om-oss"], "careers": ["/karriere"],
                 "news": [], "leadership": [], "investor": []}


@dataclass
class Candidate:
    url: str
    origin: str   # registry_website | registry_email_domain | input_row | name_guess

    @property
    def trusted(self) -> bool:
        return self.origin in ("registry_website", "registry_email_domain")


def _normalise_site(value: str) -> str | None:
    value = (value or "").strip()
    if not value or " " in value or "." not in value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    p = urlsplit(value)
    if not p.hostname or p.username or p.password:
        return None
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", ""))


def name_guesses(legal_name: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", legal_name or "").casefold().translate(_TRANSLIT)
    words = [w for w in re.split(r"[^a-z0-9]+", folded) if w and w not in _FORM_WORDS]
    if not words or len(words) > 3:
        return []
    joined = "".join(words)
    if len(joined) < 4 or len(joined) > 40:
        return []
    guesses = [f"https://www.{joined}.no/"]
    if len(words) > 1:
        guesses.append(f"https://www.{'-'.join(words)}.no/")
    return guesses


def gather_candidates(entity: dict, website_hint: str) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(url: str | None, how: str) -> None:
        if not url:
            return
        domain = registered_domain(urlsplit(url).hostname or "")
        if domain and domain not in seen:
            seen.add(domain)
            out.append(Candidate(url, how))

    add(_normalise_site(str(entity.get("hjemmeside") or "")), "registry_website")
    email = str(entity.get("epostadresse") or "").strip().lower()
    if "@" in email:
        domain = email.rsplit("@", 1)[1]
        if domain not in GENERIC_MAIL_DOMAINS:
            add(_normalise_site(domain), "registry_email_domain")
    add(_normalise_site(website_hint), "input_row")
    if not out:
        for guess in name_guesses(entity.get("navn") or ""):
            add(guess, "name_guess")
    return out


_OUTCOME_STATE = {
    "blocked": (BLOCKED, "the site refused the request"),
    "robots_disallowed": (BLOCKED, "robots.txt disallows crawling"),
    "timeout": (FAILED, "the site timed out"),
    "error": (FAILED, "the site returned a server error"),
    "time_budget": (FAILED, "time_budget_exhausted before the site could be crawled"),
    "unreachable": (NOT_AVAILABLE, "the site could not be reached (DNS or connection failure)"),
    "not_found": (NOT_AVAILABLE, "the site's homepage was not found"),
    "url_refused": (BLOCKED, "the URL was refused by the outbound safety policy"),
    "not_html": (NOT_AVAILABLE, "the homepage is not an HTML page"),
    "egress_blocked": (FAILED, "this run's own network policy blocked outbound access to the site"),
}


class WebsiteResearch:
    def __init__(self, fetcher: Fetcher, collector: Collector, ops: Operations, deadline_fn,
                 entity: dict | None, row) -> None:
        self.fetcher = fetcher
        self.c = collector
        self.ops = ops
        self.deadline_fn = deadline_fn
        self.entity = dict(entity or {})
        self.row = row
        addr = self.entity.get("forretningsadresse") or self.entity.get("beliggenhetsadresse")
        if addr:
            self.entity["_address"] = {"lines": addr.get("adresse") or [],
                                       "postcode": addr.get("postnummer")}

    # -- orchestration ---------------------------------------------------------------------
    def run(self) -> None:
        candidates = gather_candidates(self.entity, self.row.website_hint if self.row else "")
        if not candidates:
            self._set(NOT_AVAILABLE, "no website candidate: none registered in Enhetsregisteret, "
                      "no company e-mail domain and none supplied",
                      NOT_AVAILABLE, "no verified website to check for jobs or dated activity")
            return
        attempts: list[str] = []
        conflict: tuple[Candidate, Verdict] | None = None
        failure: tuple[str, str] | None = None
        declared: Candidate | None = None
        for cand in candidates:
            crawler = SiteCrawler(self.fetcher, self.ops, self.deadline_fn,
                                  lambda snap: self.c.keep_snapshot(snap, COMPANY_OWNED))
            home, outcome = self._homepage(crawler, cand)
            if home is None:
                self._candidate(cand, outcome, _OUTCOME_STATE.get(outcome, (FAILED, outcome))[0])
                attempts.append(f"{cand.url} ({cand.origin}): {outcome}")
                if cand.origin != "name_guess" and failure is None:
                    failure = _OUTCOME_STATE.get(outcome, (FAILED, outcome))
                    failure = (failure[0], f"{failure[1]} ({cand.url})")
                if cand.origin == "registry_website":
                    declared = cand
                continue
            pages = [home] + self._identity_pages(crawler, home)
            verdict = verify(self.c.orgnr, self.entity, pages, cand.trusted)
            attempts.append(f"{cand.url} ({cand.origin}): {verdict.status}")
            if verdict.status == "verified":
                self._candidate(cand, "verified", AVAILABLE, verdict.method)
                self._publish(cand, crawler, pages, verdict)
                return
            if verdict.status == "conflict":
                self._candidate(cand, "other_orgnr", AMBIGUOUS,
                                "presents " + ", ".join(verdict.other_orgnrs))
                if cand.origin != "name_guess" and conflict is None:
                    conflict = (cand, verdict)
            elif cand.origin == "registry_website":
                # The registry itself declares the site and nothing on it contradicts identity.
                self._candidate(cand, "registry_declared", AVAILABLE,
                                "no identity proof on the site, no contradiction")
                self._publish(cand, crawler, pages, Verdict("verified", "registry_declared"))
                return
            else:
                self._candidate(cand, "no_proof", AMBIGUOUS if cand.trusted or
                                cand.origin == "input_row" else NOT_AVAILABLE)
        if conflict is not None:
            cand, verdict = conflict
            self._conflict(cand, verdict)
            return
        if failure is not None:
            state, reason = failure
            if declared is not None and self._registry_declared(declared):
                reason += "; the registry-declared website is published from registry evidence"
            self._set(state, reason, state, f"no verified website could be crawled: {reason}")
            return
        tried = "; ".join(attempts)
        trusted = [c for c in candidates if c.origin != "name_guess"]
        if trusted:
            self._set(AMBIGUOUS, "candidate site(s) found but none shows proof that it belongs "
                      f"to this organisation number ({tried})",
                      NOT_AVAILABLE, "no verified website to check for jobs or dated activity")
        else:
            self._set(NOT_AVAILABLE, "no website registered and no site with this organisation "
                      f"number found at likely addresses ({tried})",
                      NOT_AVAILABLE, "no verified website to check for jobs or dated activity")

    def _candidate(self, cand: Candidate, outcome: str, state: str, detail: str | None = None):
        """One record per candidate tried, with its final outcome (R-1.37)."""
        self.c.sources[S_WEBSITE].append({
            "source": "site.candidate", "url": cand.url, "candidate_origin": cand.origin,
            "outcome": outcome, "availability": state, "detail": detail,
            "retrieved_at": utc_now()})

    def _set(self, web_state, web_reason, hiring_state, hiring_reason) -> None:
        self.c.set_section("website", web_state, web_reason)
        self.c.set_section("hiring", hiring_state, hiring_reason)

    def _homepage(self, crawler: SiteCrawler, cand: Candidate) -> tuple[Page | None, str]:
        page, snap, outcome = crawler.fetch_page(cand.url, "home")
        if snap is not None:
            self.c.note_source(S_WEBSITE, snap, outcome)
        else:  # stopped before the homepage request (robots.txt, budget): record the decision
            robots = next((s for s in reversed(crawler.snapshots)
                           if s.source == "site.robots"), None)
            self.c.sources[S_WEBSITE].append({
                "source": "site.home", "url": cand.url, "candidate_origin": cand.origin,
                "http_status": None, "outcome": outcome,
                "robots_url": robots.url if robots else None,
                "robots_http_status": robots.status if robots else None,
                "retrieved_at": robots.retrieved_at if robots else utc_now()})
        if page is None and outcome.startswith("robots_unavailable"):
            robots_state = outcome.removeprefix("robots_unavailable_")
            return None, {"unreachable": "unreachable", "timeout": "timeout",
                          "time_budget": "time_budget", "egress_blocked": "egress_blocked"}.get(
                              robots_state, "robots_disallowed")
        if page is None and outcome.startswith("robots"):
            return None, "robots_disallowed"
        return page, outcome

    def _identity_pages(self, crawler: SiteCrawler, home: Page) -> list[Page]:
        """Contact and about pages: where organisation numbers usually are."""
        pages = []
        links = discover_links(home)
        for kind in ("contact", "about"):
            urls = links.get(kind) or [origin(home.url).rstrip("/") + p for p in GUESSED_PATHS[kind]]
            for url in urls[:1]:
                page, snap, outcome = crawler.fetch_page(url, kind)
                if snap is not None:
                    self.c.note_source(S_WEBSITE, snap, outcome)
                if page is not None:
                    pages.append(page)
        return pages

    # -- publication -----------------------------------------------------------------------
    def _registry_evidence(self) -> list[Evidence]:
        for claim in self.c.claims:
            if claim.field == "registered_website":
                return list(claim.evidence)
        return []

    def _registry_declared(self, cand: Candidate) -> bool:
        """Publish the registry-declared URL (site not crawlable) with registry evidence only."""
        evidence = self._registry_evidence()
        if not evidence:
            return False
        self.c.add(Claim(field="official_website", label="Official website", section=S_WEBSITE,
                         value=cand.url, availability=AVAILABLE, confidence=0.7,
                         evidence=evidence,
                         extra={"verification": "registry_declared", "site_crawled": False,
                                "candidate_origin": cand.origin}))
        return True

    def _conflict(self, cand: Candidate, verdict: Verdict) -> None:
        others = ", ".join(verdict.other_orgnrs)
        reason = (f"{cand.url} presents organisation number {others}, a different legal entity "
                  "(possibly a parent, group or brand company); its facts are not attributed to "
                  "this company")
        self.c.add(Claim(field="website_candidate_relationship", label="Related entity's website",
                         section=S_WEBSITE, value=None, availability=AMBIGUOUS,
                         confidence=0.0, reason=reason,
                         extra={"candidate_url": cand.url, "candidate_origin": cand.origin,
                                "presented_organisation_numbers": list(verdict.other_orgnrs)}))
        self._set(AMBIGUOUS, reason, NOT_AVAILABLE,
                  "no verified website to check for jobs or dated activity")

    def _publish(self, cand: Candidate, crawler: SiteCrawler, pages: list[Page],
                 verdict: Verdict) -> None:
        home = pages[0]
        site_url = origin(home.url)
        evidence = []
        if verdict.proof_page is not None and verdict.proof_span:
            el = verdict.proof_page.element_with_text(verdict.proof_span.split(" … ")[0][-20:])
            evidence.append(Extractor.evidence(verdict.proof_page, el, verdict.proof_span,
                                               "site-identity-v1"))
        if cand.origin == "registry_website":
            evidence.extend(self._registry_evidence())
        if not evidence:
            evidence.append(Extractor.evidence(home, None, None, "site-identity-v1"))
        confidence = {"organisation_number_on_site": 0.99, "name_and_address_on_site": 0.9,
                      "name_and_contact_on_site": 0.9, "registry_declared": 0.8}[verdict.method]
        self.c.add(Claim(field="official_website", label="Official website", section=S_WEBSITE,
                         value=site_url, availability=AVAILABLE, confidence=confidence,
                         evidence=evidence,
                         extra={"verification": verdict.method, "candidate_origin": cand.origin,
                                "candidate_url": cand.url}))
        self.c.checked.add("website")

        links = discover_links(home)
        for kind in ("careers", "news", "leadership", "investor"):
            urls = links.get(kind) or [origin(home.url).rstrip("/") + p
                                       for p in GUESSED_PATHS[kind]]
            for url in urls[:1]:
                if any(p.url == url or p.requested_url == url for p in pages):
                    continue
                page, snap, outcome = crawler.fetch_page(url, kind)
                if snap is not None:
                    self.c.note_source(S_HIRING if kind in ("careers", "news") else S_WEBSITE,
                                       snap, outcome)
                if page is not None:
                    pages.append(page)
        extractor = Extractor(self.c, crawler, self.entity, site_url, confidence)
        result = extractor.run(pages)
        method = verdict.method.replace("_", " ")
        self.c.set_section("website", AVAILABLE, f"official website verified ({method}); "
                           f"{crawler.pages_fetched} pages crawled")
        self.c.set_section("hiring", *result.hiring_state())


def discover_links(home: Page) -> dict[str, list[str]]:
    """Same-site links from the homepage grouped by page kind, in document order."""
    site = registered_domain(urlsplit(home.url).hostname or "")
    found: dict[str, list[str]] = {}
    for url, text, _ in home.links():
        p = urlsplit(url)
        if p.scheme not in ("http", "https"):
            continue
        if registered_domain(p.hostname or "") != site:
            continue
        clean_url = urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
        haystack = (p.path + " " + text).lower()
        for kind, words in PAGE_KINDS:
            if any(w in haystack for w in words):
                bucket = found.setdefault(kind, [])
                if clean_url not in bucket:
                    bucket.append(clean_url)
                break
    return found

