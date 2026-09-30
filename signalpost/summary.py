"""Deterministic, citation-carrying company summary built only from published claims."""

from __future__ import annotations

from collections import Counter

from .registry import format_address

SECTION_NAMES = {
    "legal_identity_and_brand": "legal identity and brand",
    "annual_accounts": "annual accounts",
    "leadership_and_workplaces": "leadership and workplaces",
    "website_and_profiles": "official website and company-owned profiles",
    "hiring_and_activity": "hiring and dated public activity",
}
MAX_QUOTE = 220


def fmt_number(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return str(value)


def _quote(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_QUOTE else text[:MAX_QUOTE].rsplit(" ", 1)[0] + " …"


class _Builder:
    def __init__(self, claims: list[dict]):
        self.claims = [c for c in claims if c["availability"] == "available"
                       and not c.get("carried_forward")]
        self.sentences: list[dict] = []

    def all(self, field: str) -> list[dict]:
        return [c for c in self.claims if c["field"] == field]

    def one(self, field: str) -> dict | None:
        found = self.all(field)
        return found[0] if found else None

    def say(self, text: str, cited: list[dict | None]) -> None:
        cited = [c for c in cited if c]
        if not cited:
            return
        self.sentences.append({
            "text": text,
            "claim_ids": [c["id"] for c in cited],
            "evidence_ids": sorted({e for c in cited for e in c["evidence_ids"]}),
        })


def _identity(b: _Builder, legal: dict) -> None:
    name, form = b.one("legal_name"), b.one("organisation_form")
    reg, addr = b.one("registration_date"), b.one("business_address")
    if not name:
        return
    parts = [f"{name['value']} (organisation number {legal.get('organisation_number')})"]
    if form:
        parts.append(f"is registered as {form['value'].get('description') or 'form'} "
                     f"({form['value'].get('code')})")
    else:
        parts.append("is a registered entity")
    if reg:
        parts.append(f"registered in Enhetsregisteret on {reg['value']}")
    text = " ".join(parts[:2]) + (", " + parts[2] if len(parts) > 2 else "")
    if addr and format_address(addr["value"]):
        text += f", with its business address at {format_address(addr['value'])}"
    b.say(text + ".", [name, form, reg, addr])
    founded = b.one("founding_date")
    if founded:
        b.say(f"It was founded on {founded['value']}.", [founded])
    parent = b.one("parent_unit")
    if parent:
        b.say(f"It is registered under the parent unit {parent['value']['organisation_number']}, "
              "which is a separate entity.", [parent])


def _status(b: _Builder) -> None:
    labels = {"bankrupt": "bankrupt", "under_liquidation": "under liquidation",
              "under_forced_liquidation": "under forced liquidation or dissolution"}
    for field, label in labels.items():
        claim = b.one(field)
        if claim and claim["value"] is True:
            since = f" (registered {claim['effective_date']})" if claim.get("effective_date") else ""
            b.say(f"Important: the registry records the company as {label}{since}.", [claim])
    deleted = b.one("deleted")
    if deleted:
        on = (deleted["value"] or {}).get("deleted_on")
        b.say("Important: the entity has been deleted from Enhetsregisteret"
              + (f" on {on}." if on else "."), [deleted])


def _activity(b: _Builder) -> None:
    codes = sorted(b.all("industry_code"), key=lambda c: c.get("rank") or 9)
    if codes:
        described = [f"{c['value']['description']} (NACE {c['value']['code']})" for c in codes]
        b.say("Registered industry: " + "; ".join(described) + ".", codes)
    activity = b.one("registered_activity") or b.one("stated_purpose")
    if activity:
        kind = "registered activity" if activity["field"] == "registered_activity" \
            else "stated purpose"
        b.say(f"Its {kind} reads: “{_quote(activity['value'])}”", [activity])
    description = b.one("site_description")
    if description:
        b.say("In the company's own words on its website (company-provided, not an independent "
              f"assessment): “{_quote(description['value'])}”", [description])


def _size(b: _Builder) -> None:
    employees = b.one("registered_employees")
    if employees:
        when = employees.get("effective_date")
        b.say(f"The registry lists {fmt_number(employees['value'])} employees"
              + (f" (as of {when})." if when else "."), [employees])
    periods = b.all("accounts_period")
    for period in periods:
        ident = period["claim_key"].rsplit(":", 1)[-1]
        currency = period["value"].get("currency") or ""
        picks = [("operating revenue", "operating_revenue"), ("operating result", "operating_result"),
                 ("net result", "net_result"), ("total assets", "total_assets"),
                 ("equity", "total_equity")]
        facts, cited = [], [period]
        for label, field in picks:
            claim = next((c for c in b.all(field) if c["claim_key"].endswith(":" + ident)), None)
            if claim:
                facts.append(f"{label} {fmt_number(claim['value'])} {currency}".strip())
                cited.append(claim)
        if not facts:
            continue
        scope = "group (konsern) " if ident == "konsern" else ""
        b.say(f"Its latest filed {scope}annual accounts ({period['value']['from']} to "
              f"{period['value']['to']}) report " + ", ".join(facts) + ".", cited)
    audited = b.one("audited")
    if audited and audited["value"].get("audit_opted_out"):
        b.say("The company has opted out of auditing its accounts.", [audited])
    years = b.one("filing_years")
    if years and years["value"]:
        b.say(f"Annual-account copies are on file for {len(years['value'])} years "
              f"({years['value'][0]}–{years['value'][-1]}).", [years])


def _leadership(b: _Builder) -> None:
    active = [c for c in b.all("role")
              if not c["value"].get("resigned") and not c["value"].get("deregistered")]
    by_code: dict[str, list[dict]] = {}
    for c in active:
        by_code.setdefault(c["value"].get("role_code"), []).append(c)
    bits, cited = [], []
    for code, label in (("DAGL", "CEO (daglig leder)"), ("INNH", "owner (innehaver)"),
                        ("LEDE", "chair of the board"), ("KONT", "contact person")):
        holders = by_code.get(code, [])
        if holders:
            bits.append(f"{label}: " + ", ".join(h["value"]["name"] for h in holders))
            cited += holders
    members = by_code.get("MEDL", [])
    if members:
        bits.append(f"{len(members)} other board member{'s' if len(members) != 1 else ''}")
        cited += members
    for code, label in (("REVI", "auditor"), ("REGN", "accountant")):
        holders = by_code.get(code, [])
        if holders:
            bits.append(f"{label}: " + ", ".join(h["value"]["name"] for h in holders))
            cited += holders
    if bits:
        b.say("Leadership per the registry — " + "; ".join(bits) + ".", cited)


def _locations(b: _Builder) -> None:
    municipality = b.one("municipality")
    count = b.one("workplace_count")
    places = b.all("workplace")
    if municipality:
        b.say(f"It is based in {municipality['value'].title()} municipality.", [municipality])
    if count and count["value"]:
        towns = Counter((p["value"].get("municipality") or "").title() for p in places
                        if p["value"].get("municipality"))
        top = ", ".join(t for t, _ in towns.most_common(5))
        text = (f"It has {fmt_number(count['value'])} registered workplace"
                f"{'s' if count['value'] != 1 else ''} (sub-units)")
        if top:
            text += f" in {len(towns)} municipalit{'ies' if len(towns) != 1 else 'y'}"
            text += f", including {top}" if len(towns) > 1 else f" ({top})"
        b.say(text + ".", [count] + places[:20])


def _web(b: _Builder) -> None:
    site = b.one("official_website")
    if site:
        how = {"organisation_number_on_site": "the organisation number appears on the site",
               "name_and_address_on_site": "the legal name and registered address appear on the site",
               "name_and_contact_on_site": "the legal name and registered phone/e-mail appear on the site",
               "registry_declared": "the site is declared in Enhetsregisteret"}
        method = how.get(site.get("verification") or "", "verified")
        b.say(f"Official website: {site['value']} ({method}).", [site])
    elif (registered := b.one("registered_website")):
        b.say(f"The registry lists the website {registered['value']}.", [registered])
    profiles = b.all("social_profile")
    if profiles:
        names = sorted({p["value"]["platform"] for p in profiles})
        b.say("Company-owned profiles linked from its website: " + ", ".join(names) + ".", profiles)
    jobs = b.all("job_posting")
    careers = b.one("careers_page")
    if jobs:
        titles = "; ".join(j["value"]["title"] for j in jobs[:3])
        b.say(f"Its own website lists {len(jobs)} job posting{'s' if len(jobs) != 1 else ''}"
              f" (e.g. {titles}).", jobs[:10])
    elif careers:
        b.say(f"It has a careers page ({careers['value']}) with no job postings found.", [careers])
    news = sorted(b.all("news_item"), key=lambda c: c["value"].get("date") or "", reverse=True)
    if news:
        latest = news[0]["value"]
        b.say(f"Latest dated activity on its website: “{_quote(latest['title'])}” "
              f"({latest.get('date') or 'undated'}).", news[:1])


def _changes_text(changes: list[dict], history: dict | None) -> str:
    if history is None:
        return "First observation of this company: no earlier run to compare with."
    since = history.get("last_observed_at", "")[:10]
    if not changes:
        return f"No material changes since the previous observation on {since}."
    counts = Counter(c["type"] for c in changes)
    listed = ", ".join(f"{n} × {t.replace('_', ' ')}" for t, n in counts.most_common())
    high = [c for c in changes if c["materiality"] == "high"]
    text = f"Since the previous observation on {since}: {listed}."
    if high:
        text += " Most material: " + "; ".join(
            f"{c['label']} ({c['type'].replace('_', ' ')})" for c in high[:3]) + "."
    return text


def build_summary(claims: list[dict], sections: dict, changes: list[dict], history: dict | None,
                  legal: dict | None, status: str, status_reason: str) -> dict:
    b = _Builder(claims)
    if status == "available":
        _status(b)
        _identity(b, legal or {})
        _activity(b)
        _size(b)
        _leadership(b)
        _locations(b)
        _web(b)
    else:
        _status(b)
    unknowns = []
    for key, name in SECTION_NAMES.items():
        section = sections.get(key) or {}
        if section.get("availability") != "available":
            unknowns.append({"section": key, "availability": section.get("availability"),
                             "text": f"{name[0].upper() + name[1:]}: "
                                     f"{section.get('availability', 'unknown').replace('_', ' ')}"
                                     f" — {section.get('reason', '')}"})
    changes_text = _changes_text(changes, history)
    if status != "available":
        lead = {"not_available": "No profile: ", "blocked": "No profile: the registry refused "
                "the request — ", "failed": "No profile: the research failed — "}.get(status, "")
        head = lead + status_reason + "."
    else:
        head = ""
    body = " ".join(s["text"] for s in b.sentences)
    unknown_text = ""
    if unknowns:
        unknown_text = "Unknown or not verified: " + "; ".join(
            f"{u['text'].split(':')[0].lower()} ({u['availability'].replace('_', ' ')})"
            for u in unknowns) + "."
    text = " ".join(p for p in (head, body, changes_text, unknown_text) if p)
    return {"text": text, "sentences": b.sentences, "unknowns": unknowns,
            "changes_text": changes_text, "generated_by": "deterministic"}
