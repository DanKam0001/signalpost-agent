"""Exact-entity proof for a candidate website.

A site is the company's own only with proof tied to the organisation number: the number itself on
the site (any common formatting), or a documented strong combination of the full legal name with the
registered address or registered phone/e-mail. A site that presents a *different* organisation
number as its owner is never attributed to this company.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..orgnr import is_valid
from .pages import Page, clean

# 9 digits, optionally grouped 3-3-3 with spaces/dots/nbsp, optionally wrapped as NO … MVA.
_ORGNR = re.compile(r"(?<![\d])(\d{3})[ .  ]?(\d{3})[ .  ]?(\d{3})(?![\d])")
_LABEL = re.compile(r"(org(anisasjons)?[\s.\-]*n(umme)?r|org\.?\s*no|foretaksregisteret|"
                    r"organi[sz]ation\s*(number|no)|company\s*(reg|no|number)|\bmva\b|vat|"
                    r"\bno\s*$|business\s*reg)", re.I)
_FORM_SUFFIXES = {"as", "asa", "ans", "da", "sa", "ba", "enk", "nuf", "ks", "sf", "iks",
                  "stiftelse"}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\wæøå]+", " ", text).strip()


@dataclass
class OrgnrHit:
    number: str
    span: str
    labelled: bool
    page: Page


def find_orgnrs(page: Page) -> list[OrgnrHit]:
    hits = []
    text = page.text
    for m in _ORGNR.finditer(text):
        number = "".join(m.groups())
        if not is_valid(number):
            continue
        before = text[max(0, m.start() - 40):m.start()]
        after = text[m.end():m.end() + 6]
        grouped = m.group(0) != number  # written as 3-3-3 groups: how org numbers are printed
        labelled = bool(_LABEL.search(before)) or after.strip().upper().startswith("MVA") \
            or grouped
        span = clean(text[max(0, m.start() - 40):m.end() + 8])
        hits.append(OrgnrHit(number, span, labelled, page))
    for item, _ in page.jsonld():
        for key in ("vatID", "taxID", "leiCode", "identifier", "organizationNumber"):
            raw = item.get(key)
            if isinstance(raw, (str, int)):
                digits = re.sub(r"\D", "", str(raw))
                if len(digits) == 9 and is_valid(digits):
                    hits.append(OrgnrHit(digits, f'JSON-LD {key}: "{raw}"', True, page))
    return hits


def name_on_page(legal_name: str, page: Page) -> str | None:
    """The full legal name (with its form suffix, e.g. 'AS') appears on the page."""
    target = _fold(legal_name)
    if not target or len(target) < 4:
        return None
    if target.split()[-1] not in _FORM_SUFFIXES:
        # Names without a form suffix are too generic to be proof on their own.
        if len(target.split()) < 2:
            return None
    folded = _fold(page.text)
    idx = f" {folded} ".find(f" {target} ")
    if idx < 0:
        return None
    return legal_name


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def address_on_page(address: dict | None, page: Page) -> str | None:
    if not address:
        return None
    postcode = address.get("postcode") or ""
    lines = [line for line in address.get("lines") or [] if line]
    if not postcode or not lines:
        return None
    folded = _fold(page.text)
    street = _fold(lines[0])
    if len(street) >= 4 and street in folded and re.search(rf"(?<!\d){postcode}(?!\d)", folded):
        return f"{lines[0]}, {postcode}"
    return None


def phone_on_page(phone: str | None, page: Page) -> str | None:
    digits = _digits(phone or "")
    if digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    if len(digits) != 8:
        return None
    if digits in _digits(page.text) or any(digits in _digits(href) for href, _, _ in page.links()
                                           if href.startswith("tel:")):
        return phone
    return None


@dataclass
class Verdict:
    status: str          # verified | conflict | unproven
    method: str | None   # organisation_number_on_site | name_and_address_on_site | ...
    proof_page: Page | None = None
    proof_span: str | None = None
    other_orgnrs: tuple[str, ...] = ()


def verify(orgnr: str, entity: dict, pages: list[Page], trusted_candidate: bool) -> Verdict:
    """Decide whether `pages` (one site) belong to the entity with `orgnr`.

    `trusted_candidate` is True when the site came from the registry or the company's own
    registered e-mail domain; guessed or externally supplied candidates need cleaner proof.
    """
    hits = [h for p in pages for h in find_orgnrs(p)]
    own = [h for h in hits if h.number == orgnr]
    others = sorted({h.number for h in hits if h.number != orgnr and h.labelled})
    if own:
        best = next((h for h in own if h.labelled), own[0])
        if others and not trusted_candidate:
            return Verdict("conflict", None, best.page, best.span, tuple(others))
        return Verdict("verified", "organisation_number_on_site", best.page, best.span,
                       tuple(others))
    if others:
        first = next(h for h in hits if h.number in others)
        return Verdict("conflict", None, first.page, first.span, tuple(others))
    name = entity.get("navn") or ""
    address = entity.get("_address")
    for page in pages:
        if not name_on_page(name, page):
            continue
        addr = address_on_page(address, page)
        if addr:
            return Verdict("verified", "name_and_address_on_site", page, f"{name} … {addr}")
        phone = phone_on_page(entity.get("telefon"), page)
        if phone:
            return Verdict("verified", "name_and_contact_on_site", page, f"{name} … {phone}")
        email = str(entity.get("epostadresse") or "").lower()
        if email and email in page.text.lower():
            return Verdict("verified", "name_and_contact_on_site", page, f"{name} … {email}")
    return Verdict("unproven", None)
