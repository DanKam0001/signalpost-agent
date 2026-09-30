"""Brønnøysundregistrene research: entity, roles, subunits, annual accounts and filing years.

Every fact becomes a claim whose evidence cites the exact API URL, a JSON pointer into the
stored snapshot, the retrieval time and the registry's own date for the fact where it has one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .fetch import Fetcher, Operations, Snapshot
from .model import (AVAILABLE, BLOCKED, FAILED, NOT_AVAILABLE, OFFICIAL_ACCOUNTS,
                    OFFICIAL_REGISTRY, Claim, Collector, Evidence)

BASE = "https://data.brreg.no"
EXTRACTOR = "brreg-json-v1"
SUBUNIT_PAGE_SIZE = 100
SUBUNIT_MAX_PAGES = 10
RATE_LIMIT_REASON = ("Brønnøysund limits this endpoint to about 30 requests per minute; "
                     "not fetched for this company in this run")  # up to 1,000 workplaces listed; the total is always reported

S_IDENTITY = "legal_identity_and_brand"
S_ACCOUNTS = "annual_accounts"
S_LEADERSHIP = "leadership_and_workplaces"
S_WEBSITE = "website_and_profiles"


def entity_url(orgnr: str) -> str:
    return f"{BASE}/enhetsregisteret/api/enheter/{orgnr}"


def subunit_url(orgnr: str) -> str:
    return f"{BASE}/enhetsregisteret/api/underenheter/{orgnr}"


def roles_url(orgnr: str) -> str:
    return f"{BASE}/enhetsregisteret/api/enheter/{orgnr}/roller"


def subunits_url(orgnr: str, page: int) -> str:
    return (f"{BASE}/enhetsregisteret/api/underenheter?overordnetEnhet={orgnr}"
            f"&size={SUBUNIT_PAGE_SIZE}&page={page}")


def accounts_url(orgnr: str) -> str:
    return f"{BASE}/regnskapsregisteret/regnskap/{orgnr}"


def filing_years_url(orgnr: str) -> str:
    return f"{BASE}/regnskapsregisteret/regnskap/aarsregnskap/kopi/{orgnr}/aar"


def human_url(orgnr: str, subunit: bool = False) -> str:
    kind = "underenheter" if subunit else "enheter"
    return f"https://virksomhet.brreg.no/nb/oppslag/{kind}/{orgnr}"


def _date(value) -> str | None:
    return str(value)[:10] if value else None


def _pointer(*parts) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _address(addr: dict | None) -> dict | None:
    if not addr:
        return None
    return {
        "lines": [line for line in addr.get("adresse") or [] if line],
        "postcode": addr.get("postnummer"),
        "city": addr.get("poststed"),
        "municipality": addr.get("kommune"),
        "municipality_number": addr.get("kommunenummer"),
        "country": addr.get("land"),
        "country_code": addr.get("landkode"),
    }


def format_address(addr: dict | None) -> str:
    if not addr:
        return ""
    head = ", ".join(addr.get("lines") or [])
    tail = " ".join(p for p in (addr.get("postcode"), addr.get("city")) if p)
    return ", ".join(p for p in (head, tail) if p)


def _person_name(person: dict) -> str:
    navn = person.get("navn") or {}
    return " ".join(p for p in (navn.get("fornavn"), navn.get("mellomnavn"), navn.get("etternavn")) if p)


def failure_state(snap: Snapshot) -> tuple[str, str]:
    """Map a non-success snapshot to (availability, reason)."""
    if snap.error and snap.error.startswith("time_budget"):
        return FAILED, "time_budget_exhausted"
    if snap.refused:
        return BLOCKED, f"source refused the request ({snap.outcome()})"
    if snap.status == 404:
        return NOT_AVAILABLE, "no record returned by the source (HTTP 404)"
    if snap.status == 410:
        return NOT_AVAILABLE, "record deleted at the source (HTTP 410)"
    return FAILED, f"source error ({snap.outcome()})"


@dataclass
class RegistryResult:
    status: str                  # envelope-level status
    reason: str
    entity: dict | None = None
    is_subunit: bool = False
    legal_identity: dict | None = None


class RegistryResearch:
    def __init__(self, fetcher: Fetcher, collector: Collector, ops: Operations,
                 deadline_fn, history_max_wait: float = 5.0):
        self.fetcher = fetcher
        self.c = collector
        self.ops = ops
        self.deadline_fn = deadline_fn
        self.history_max_wait = history_max_wait
        self.orgnr = collector.orgnr
        self.extractor = EXTRACTOR

    # -- helpers ---------------------------------------------------------------------------
    def _get(self, url: str, source: str, **kw) -> Snapshot:
        return self.fetcher.get(url, source=source, ops=self.ops, deadline=self.deadline_fn(),
                                check_policy=False, **kw)

    def _ev(self, snap: Snapshot, pointer: str, *, record_date=None, record_date_field=None,
            source_class=OFFICIAL_REGISTRY, subunit_orgnr: str | None = None) -> Evidence:
        if subunit_orgnr:
            human = human_url(subunit_orgnr, subunit=True)
        else:
            human = human_url(self.orgnr, subunit=self._subunit)
        return Evidence(source_url=snap.url, source_class=source_class,
                        retrieved_at=snap.retrieved_at, content_sha256=snap.sha256,
                        extraction_method=self.extractor, human_url=human,
                        record_date=_date(record_date), record_date_field=record_date_field,
                        json_pointer=pointer)

    def _claim(self, section, field, label, value, snap, pointer, *, identity="",
               record_date=None, record_date_field=None, source_class=OFFICIAL_REGISTRY,
               **kw) -> Claim:
        ev = self._ev(snap, pointer, record_date=record_date, record_date_field=record_date_field,
                      source_class=source_class, subunit_orgnr=kw.pop("subunit_orgnr", None))
        return self.c.add(Claim(field=field, label=label, section=section, value=value,
                                availability=AVAILABLE, identity=identity, evidence=[ev], **kw))

    def _absent(self, section, field, label, reason, snap: Snapshot | None = None,
                pointer: str = "", availability=NOT_AVAILABLE, identity="") -> Claim:
        evidence = [self._ev(snap, pointer)] if snap is not None and snap.ok else []
        return self.c.add(Claim(field=field, label=label, section=section, value=None,
                                availability=availability, identity=identity, reason=reason,
                                confidence=1.0 if evidence else 0.0, evidence=evidence))

    _subunit = False

    # -- identity --------------------------------------------------------------------------
    def identity(self) -> RegistryResult:
        snap = self._get(entity_url(self.orgnr), "brreg.entity")
        self.c.note_source(S_IDENTITY, snap)
        if snap.ok:
            self.c.keep_snapshot(snap, OFFICIAL_REGISTRY)
            try:
                data = snap.json()
            except ValueError:
                self.c.error(S_IDENTITY, "invalid_json", "entity response was not JSON", snap.url)
                return RegistryResult(FAILED, "registry returned an unreadable response")
            self.c.checked.add("entity")
            return self._entity_claims(snap, data)
        if snap.status == 410:
            return self._deleted(snap)
        if snap.status == 404:
            sub = self._get(subunit_url(self.orgnr), "brreg.subunit_entity")
            self.c.note_source(S_IDENTITY, sub)
            if sub.ok:
                self.c.keep_snapshot(sub, OFFICIAL_REGISTRY)
                self._subunit = True
                self.c.checked.add("entity")
                try:
                    return self._entity_claims(sub, sub.json(), is_subunit=True)
                except ValueError:
                    return RegistryResult(FAILED, "registry returned an unreadable response")
            if sub.status == 410:
                self._subunit = True
                return self._deleted(sub)
            return RegistryResult(NOT_AVAILABLE, "no entity with this organisation number in "
                                  "Enhetsregisteret (HTTP 404)")
        state, reason = failure_state(snap)
        self.c.error(S_IDENTITY, "entity_fetch_failed", reason, snap.url)
        if state == NOT_AVAILABLE:
            state = FAILED
        return RegistryResult(state, reason)

    def identity_from_snapshot(self, record: dict, snapshot, live: RegistryResult) -> RegistryResult:
        """Anchor identity on the frozen registry snapshot when the live API failed."""
        body = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str).encode()
        info = snapshot.identity
        snap = Snapshot(url=entity_url(self.orgnr), source="brreg.registry_snapshot",
                        retrieved_at=datetime.fromtimestamp(info["modified"], timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"), status=200, body=body,
                        final_url=entity_url(self.orgnr),
                        headers={"content-type": "application/json"})
        self.c.keep_snapshot(snap, OFFICIAL_REGISTRY)
        self.c.note_source(S_IDENTITY, snap, "frozen_registry_snapshot")
        self.extractor = f"brreg-bulk-snapshot-v1 file={info['file']} sha256={info['sha256']}"
        result = self._entity_claims(snap, record)
        self.extractor = EXTRACTOR
        result.reason = (f"identity anchored on the frozen registry snapshot {info['file']} "
                         f"(live API: {live.reason})")
        return result

    def _deleted(self, snap: Snapshot) -> RegistryResult:
        self.c.keep_snapshot(snap, OFFICIAL_REGISTRY)
        deleted_on = None
        try:
            data = snap.json() if snap.body else {}
            deleted_on = data.get("slettedato") if isinstance(data, dict) else None
        except ValueError:
            data = {}
        ev = self._ev(snap, "/slettedato" if deleted_on else "", record_date=deleted_on,
                      record_date_field="slettedato" if deleted_on else None)
        self.c.add(Claim(field="deleted", label="Deleted from Enhetsregisteret", section=S_IDENTITY,
                         value={"deleted": True, "deleted_on": _date(deleted_on)},
                         availability=AVAILABLE, evidence=[ev], effective_date=_date(deleted_on)))
        reason = "entity deleted from Enhetsregisteret (HTTP 410)"
        if deleted_on:
            reason += f" on {_date(deleted_on)}"
        identity = {"organisation_number": self.orgnr, "deleted": True,
                    "deleted_on": _date(deleted_on), "source_url": snap.url,
                    "human_url": human_url(self.orgnr, self._subunit)}
        return RegistryResult(NOT_AVAILABLE, reason, entity=data or None,
                              legal_identity=identity)

    def _entity_claims(self, snap: Snapshot, d: dict, is_subunit: bool = False) -> RegistryResult:
        S = S_IDENTITY
        reg_date = d.get("registreringsdatoEnhetsregisteret")
        history = d.get("historiskeNavn") or []
        if d.get("navn"):
            name_since = history[-1].get("tilDato") if history else None
            self._claim(S, "legal_name", "Legal name", d["navn"], snap, "/navn",
                        record_date=name_since or reg_date,
                        record_date_field="historiskeNavn/-1/tilDato" if name_since
                        else "registreringsdatoEnhetsregisteret",
                        effective_date=_date(name_since or reg_date))
        form = d.get("organisasjonsform") or {}
        if form.get("kode"):
            self._claim(S, "organisation_form", "Organisation form",
                        {"code": form.get("kode"), "description": form.get("beskrivelse")},
                        snap, "/organisasjonsform")
        if reg_date:
            self._claim(S, "registration_date", "Registered in Enhetsregisteret", _date(reg_date),
                        snap, "/registreringsdatoEnhetsregisteret", record_date=reg_date,
                        record_date_field="registreringsdatoEnhetsregisteret")
        if d.get("registrertIForetaksregisteret") and d.get("registreringsdatoForetaksregisteret"):
            v = d["registreringsdatoForetaksregisteret"]
            self._claim(S, "business_register_date", "Registered in Foretaksregisteret", _date(v),
                        snap, "/registreringsdatoForetaksregisteret", record_date=v,
                        record_date_field="registreringsdatoForetaksregisteret")
        founded = d.get("stiftelsesdato") or d.get("oppstartsdato")
        if founded:
            ptr = "/stiftelsesdato" if d.get("stiftelsesdato") else "/oppstartsdato"
            self._claim(S, "founding_date", "Founded" if not is_subunit else "Start date",
                        _date(founded), snap, ptr, record_date=founded,
                        record_date_field=ptr.lstrip("/"))
        else:
            self._absent(S, "founding_date", "Founded", "no founding date in the registry record",
                         snap)
        addr_key = "beliggenhetsadresse" if is_subunit else "forretningsadresse"
        business = _address(d.get(addr_key))
        if business:
            self._claim(S, "business_address", "Business address", business, snap, f"/{addr_key}")
            if business.get("municipality"):
                self._claim(S, "municipality", "Municipality", business["municipality"],
                            snap, f"/{addr_key}/kommune",
                            extra={"municipality_number": business.get("municipality_number")})
        else:
            self._absent(S, "business_address", "Business address",
                         "no business address in the registry record", snap)
        postal = _address(d.get("postadresse"))
        if postal:
            self._claim(S, "postal_address", "Postal address", postal, snap, "/postadresse")
        for i in (1, 2, 3):
            code = d.get(f"naeringskode{i}") or {}
            if code.get("kode"):
                self._claim(S, "industry_code", f"Industry code (NACE) {i}",
                            {"code": code["kode"], "description": code.get("beskrivelse")},
                            snap, f"/naeringskode{i}", identity=str(i), extra={"rank": i})
        sector = d.get("institusjonellSektorkode") or {}
        if sector.get("kode"):
            self._claim(S, "sector_code", "Institutional sector",
                        {"code": sector["kode"], "description": sector.get("beskrivelse")},
                        snap, "/institusjonellSektorkode")
        if d.get("harRegistrertAntallAnsatte") and d.get("antallAnsatte") is not None:
            v = d.get("registreringsdatoAntallAnsatteEnhetsregisteret")
            self._claim(S, "registered_employees", "Registered employees", d["antallAnsatte"],
                        snap, "/antallAnsatte", record_date=v, effective_date=_date(v),
                        record_date_field="registreringsdatoAntallAnsatteEnhetsregisteret"
                        if v else None)
        else:
            self._absent(S, "registered_employees", "Registered employees",
                         "the registry has no registered employee count for this entity", snap,
                         "/harRegistrertAntallAnsatte")
        if "registrertIMvaregisteret" in d:
            v = d.get("registreringsdatoMerverdiavgiftsregisteret") if d[
                "registrertIMvaregisteret"] else None
            self._claim(S, "vat_registered", "Registered for VAT", bool(d["registrertIMvaregisteret"]),
                        snap, "/registrertIMvaregisteret", record_date=v,
                        record_date_field="registreringsdatoMerverdiavgiftsregisteret" if v else None)
        capital = d.get("kapital") or {}
        if capital.get("belop") is not None:
            self._claim(S, "share_capital", "Share capital",
                        {"amount": capital["belop"], "currency": capital.get("valuta"),
                         "shares": capital.get("antallAksjer"), "type": capital.get("type")},
                        snap, "/kapital", record_date=capital.get("innfortDato"),
                        record_date_field="kapital/innfortDato" if capital.get("innfortDato") else None)
        purpose = " ".join(d.get("vedtektsfestetFormaal") or []).strip()
        if purpose:
            self._claim(S, "stated_purpose", "Purpose (articles of association)", purpose, snap,
                        "/vedtektsfestetFormaal", record_date=d.get("vedtektsdato"),
                        record_date_field="vedtektsdato" if d.get("vedtektsdato") else None)
        activity = " ".join(d.get("aktivitet") or []).strip()
        if activity:
            self._claim(S, "registered_activity", "Registered activity", activity, snap,
                        "/aktivitet")
        for i, h in enumerate(history):
            if h.get("navn"):
                self._claim(S, "historical_name", "Former name",
                            {"name": h["navn"], "from": _date(h.get("fraDato")),
                             "to": _date(h.get("tilDato"))}, snap, _pointer("historiskeNavn", i),
                            identity=f"{_date(h.get('fraDato'))}:{h['navn']}",
                            record_date=h.get("tilDato"), record_date_field="tilDato",
                            effective_date=_date(h.get("fraDato")))
        if "erIKonsern" in d:
            self._claim(S, "in_group", "Part of a group (konsern)", bool(d["erIKonsern"]), snap,
                        "/erIKonsern")
        if d.get("overordnetEnhet"):
            self._claim(S, "parent_unit", "Parent unit (overordnet enhet)",
                        {"organisation_number": d["overordnetEnhet"],
                         "relationship": "parent unit registered in Enhetsregisteret; "
                                         "a separate legal entity, not this company"},
                        snap, "/overordnetEnhet")
        flags = (("konkurs", "bankrupt", "Bankrupt", "konkursdato"),
                 ("underAvvikling", "under_liquidation", "Under liquidation", "underAvviklingDato"),
                 ("underTvangsavviklingEllerTvangsopplosning", "under_forced_liquidation",
                  "Under forced liquidation or dissolution",
                  "tvangsavvikletPgaManglendeSlettingDato"))
        for key, field, label, date_key in flags:
            if key in d:
                when = d.get(date_key) if d[key] else None
                self._claim(S, field, label, bool(d[key]), snap, f"/{key}", record_date=when,
                            record_date_field=date_key if when else None,
                            effective_date=_date(when))
        if d.get("slettedato"):
            self._claim(S, "deleted", "Deleted from Enhetsregisteret",
                        {"deleted": True, "deleted_on": _date(d["slettedato"])}, snap,
                        "/slettedato", record_date=d["slettedato"], record_date_field="slettedato")
        if d.get("nedleggelsesdato"):
            self._claim(S, "closed", "Closed (nedlagt)", _date(d["nedleggelsesdato"]), snap,
                        "/nedleggelsesdato", record_date=d["nedleggelsesdato"],
                        record_date_field="nedleggelsesdato")
        if d.get("sisteInnsendteAarsregnskap"):
            self._claim(S_ACCOUNTS, "latest_submitted_accounts_year",
                        "Latest submitted annual accounts (year)", str(d["sisteInnsendteAarsregnskap"]),
                        snap, "/sisteInnsendteAarsregnskap")
        # Registry-declared contact points belong to the website/profile section.
        if d.get("hjemmeside"):
            self._claim(S_WEBSITE, "registered_website", "Website registered in Enhetsregisteret",
                        str(d["hjemmeside"]).strip(), snap, "/hjemmeside")
        email = str(d.get("epostadresse") or "").strip()
        if "@" in email:
            self._claim(S_WEBSITE, "registered_email_domain", "Registered e-mail domain",
                        email.rsplit("@", 1)[1].lower(), snap, "/epostadresse")
        if d.get("telefon") and form.get("kode") != "ENK":
            self._claim(S_IDENTITY, "registered_phone", "Registered phone", d["telefon"], snap,
                        "/telefon")

        identity = {
            "organisation_number": self.orgnr,
            "unit_type": "underenhet" if is_subunit else "enhet",
            "name": d.get("navn"),
            "organisation_form": form.get("kode"),
            "organisation_form_description": form.get("beskrivelse"),
            "business_address": business,
            "municipality": (business or {}).get("municipality"),
            "registration_date": _date(reg_date),
            "founding_date": _date(founded),
            "industry": (d.get("naeringskode1") or {}).get("beskrivelse"),
            "bankrupt": bool(d.get("konkurs")),
            "under_liquidation": bool(d.get("underAvvikling")),
            "under_forced_liquidation": bool(d.get("underTvangsavviklingEllerTvangsopplosning")),
            "deleted": bool(d.get("slettedato")),
            "parent_organisation_number": d.get("overordnetEnhet"),
            "source_url": snap.url,
            "human_url": human_url(self.orgnr, is_subunit),
            "retrieved_at": snap.retrieved_at,
        }
        reason = "entity retrieved from Enhetsregisteret"
        if is_subunit:
            reason = "organisation number is a registered sub-unit (underenhet) of " \
                     f"{d.get('overordnetEnhet')}"
        return RegistryResult(AVAILABLE, reason, entity=d, is_subunit=is_subunit,
                              legal_identity=identity)

    # -- leadership ------------------------------------------------------------------------
    def roles(self) -> None:
        S = S_LEADERSHIP
        snap = self._get(roles_url(self.orgnr), "brreg.roles")
        self.c.note_source(S, snap)
        if not snap.ok:
            state, reason = failure_state(snap)
            self.c.set_section("roles", state, reason)
            if state != NOT_AVAILABLE:
                self.c.error(S, "roles_fetch_failed", reason, snap.url)
            return
        self.c.keep_snapshot(snap, OFFICIAL_REGISTRY)
        try:
            data = snap.json()
        except ValueError:
            self.c.set_section("roles", FAILED, "roles response was not JSON")
            return
        self.c.checked.add("roles")
        count = 0
        for gi, group in enumerate(data.get("rollegrupper") or []):
            changed = group.get("sistEndret")
            gtype = group.get("type") or {}
            for ri, role in enumerate(group.get("roller") or []):
                rtype = role.get("type") or {}
                value = {"role_code": rtype.get("kode"), "role": rtype.get("beskrivelse"),
                         "group_code": gtype.get("kode"), "group": gtype.get("beskrivelse"),
                         "resigned": bool(role.get("fratraadt")),
                         "deregistered": bool(role.get("avregistrert")),
                         "order": role.get("rekkefolge")}
                if role.get("person"):
                    name = _person_name(role["person"])
                    value.update(holder_type="person", name=name,
                                 deceased=bool(role["person"].get("erDoed")))
                    holder = "p:" + name.casefold()
                elif role.get("enhet"):
                    unit = role["enhet"]
                    name = " ".join(unit.get("navn") or []) if isinstance(unit.get("navn"), list) \
                        else str(unit.get("navn") or "")
                    value.update(holder_type="organisation", name=name,
                                 organisation_number=unit.get("organisasjonsnummer"))
                    holder = f"o:{unit.get('organisasjonsnummer')}"
                else:
                    continue
                if role.get("valgtAv"):
                    value["elected_by"] = (role["valgtAv"] or {}).get("beskrivelse")
                self._claim(S, "role", rtype.get("beskrivelse") or "Role", value, snap,
                            _pointer("rollegrupper", gi, "roller", ri),
                            identity=f"{rtype.get('kode')}:{holder}", record_date=changed,
                            record_date_field="rollegrupper/sistEndret" if changed else None,
                            effective_date=_date(changed))
                count += 1
        if count:
            self.c.set_section("roles", AVAILABLE, f"{count} registered roles")
        else:
            self.c.set_section("roles", NOT_AVAILABLE, "no roles registered for this entity")

    def subunits(self) -> None:
        S = S_LEADERSHIP
        total = None
        listed = 0
        for page in range(SUBUNIT_MAX_PAGES):
            snap = self._get(subunits_url(self.orgnr, page), "brreg.subunits")
            self.c.note_source(S, snap)
            if not snap.ok:
                state, reason = failure_state(snap)
                if page == 0:
                    self.c.set_section("workplaces", state, reason)
                    self.c.error(S, "subunits_fetch_failed", reason, snap.url)
                else:
                    self.c.error(S, "subunits_page_failed", f"page {page}: {reason}", snap.url)
                break
            self.c.keep_snapshot(snap, OFFICIAL_REGISTRY)
            try:
                data = snap.json()
            except ValueError:
                self.c.set_section("workplaces", FAILED, "subunit response was not JSON")
                break
            page_info = data.get("page") or {}
            if total is None:
                total = int(page_info.get("totalElements") or 0)
                self._claim(S, "workplace_count", "Registered workplaces (sub-units)", total, snap,
                            "/page/totalElements")
            units = (data.get("_embedded") or {}).get("underenheter") or []
            for i, u in enumerate(units):
                self._subunit_claim(snap, i, u)
                listed += 1
            if page + 1 >= int(page_info.get("totalPages") or 0):
                break
        if total is not None:
            capped = total > listed
            if not capped:
                self.c.checked.add("subunits")
            reason = f"{total} registered workplaces" + (f" ({listed} listed)" if capped else "")
            self.c.set_section("workplaces", AVAILABLE if total else NOT_AVAILABLE,
                               reason if total else "checked: no registered workplaces (sub-units)")

    def _subunit_claim(self, snap: Snapshot, i: int, u: dict) -> None:
        sub = u.get("organisasjonsnummer")
        code = u.get("naeringskode1") or {}
        value = {
            "organisation_number": sub,
            "name": u.get("navn"),
            "address": _address(u.get("beliggenhetsadresse")),
            "municipality": (u.get("beliggenhetsadresse") or {}).get("kommune"),
            "industry": {"code": code.get("kode"), "description": code.get("beskrivelse")}
            if code else None,
            "start_date": _date(u.get("oppstartsdato")),
        }
        if u.get("harRegistrertAntallAnsatte") and u.get("antallAnsatte") is not None:
            value["employees"] = u["antallAnsatte"]
        if u.get("nedleggelsesdato"):
            value["closed_on"] = _date(u["nedleggelsesdato"])
        reg = u.get("registreringsdatoEnhetsregisteret")
        self._claim(S_LEADERSHIP, "workplace", "Registered workplace", value, snap,
                    _pointer("_embedded", "underenheter", i), identity=str(sub),
                    record_date=reg, record_date_field="registreringsdatoEnhetsregisteret"
                    if reg else None, effective_date=_date(u.get("oppstartsdato")),
                    subunit_orgnr=sub)

    # -- accounts --------------------------------------------------------------------------
    ACCOUNT_FIELDS = (
        ("operating_revenue", "Total operating revenue",
         ("resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter")),
        ("operating_expenses", "Total operating expenses",
         ("resultatregnskapResultat", "driftsresultat", "driftskostnad", "sumDriftskostnad")),
        ("operating_result", "Operating result",
         ("resultatregnskapResultat", "driftsresultat", "driftsresultat")),
        ("net_financial_items", "Net financial items",
         ("resultatregnskapResultat", "finansresultat", "nettoFinans")),
        ("profit_before_tax", "Profit before tax",
         ("resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad")),
        ("net_result", "Net result for the year", ("resultatregnskapResultat", "aarsresultat")),
        ("total_assets", "Total assets", ("eiendeler", "sumEiendeler")),
        ("fixed_assets", "Fixed assets", ("eiendeler", "anleggsmidler", "sumAnleggsmidler")),
        ("current_assets", "Current assets", ("eiendeler", "omloepsmidler", "sumOmloepsmidler")),
        ("total_equity", "Total equity", ("egenkapitalGjeld", "egenkapital", "sumEgenkapital")),
        ("total_debt", "Total debt", ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld")),
        ("total_equity_and_debt", "Total equity and debt",
         ("egenkapitalGjeld", "sumEgenkapitalGjeld")),
    )
    CORE_ACCOUNT_FIELDS = ("operating_revenue", "net_result", "total_assets", "total_equity")

    def accounts(self) -> None:
        S = S_ACCOUNTS
        snap = self._get(accounts_url(self.orgnr), "brreg.accounts")
        self.c.note_source(S, snap)
        if not snap.ok:
            state, reason = failure_state(snap)
            if snap.status == 404:
                self.c.checked.add("accounts")
                reason = "no filed annual accounts returned by Regnskapsregisteret (HTTP 404)"
            else:
                self.c.error(S, "accounts_fetch_failed", reason, snap.url)
            self.c.set_section("accounts", state, reason)
            return
        self.c.keep_snapshot(snap, OFFICIAL_ACCOUNTS)
        try:
            filings = snap.json()
        except ValueError:
            self.c.set_section("accounts", FAILED, "accounts response was not JSON")
            return
        self.c.checked.add("accounts")
        if isinstance(filings, dict):
            filings = [filings]
        published = 0
        for fi, f in enumerate(filings or []):
            period = f.get("regnskapsperiode") or {}
            rp = {"from": _date(period.get("fraDato")), "to": _date(period.get("tilDato"))}
            kind = f.get("regnskapstype") or "SELSKAP"
            ident = kind.lower()
            end = period.get("tilDato")
            common = dict(identity=ident, record_date=end,
                          record_date_field="regnskapsperiode/tilDato", reporting_period=rp,
                          source_class=OFFICIAL_ACCOUNTS)
            base = _pointer(fi)
            self._claim(S, "accounts_period", f"Annual accounts period ({kind.lower()})",
                        {**rp, "account_type": kind, "currency": f.get("valuta"),
                         "journal_number": f.get("journalnr"),
                         "liquidation_accounts": bool(f.get("avviklingsregnskap"))},
                        snap, base + "/regnskapsperiode", **common)
            for field, label, path in self.ACCOUNT_FIELDS:
                cur = f
                for step in path:
                    cur = cur.get(step) if isinstance(cur, dict) else None
                if cur is None:
                    if field in self.CORE_ACCOUNT_FIELDS:
                        self._absent(S, field, label, "not present in the filed accounts", snap,
                                     base, identity=ident)
                    continue
                self._claim(S, field, label, cur, snap, base + _pointer(*path),
                            extra={"currency": f.get("valuta"), "as_filed": str(cur)}, **common)
                published += 1
            audit = f.get("revisjon") or {}
            if audit:
                audited = not audit.get("ikkeRevidertAarsregnskap") and not audit.get("fravalgRevisjon")
                self._claim(S, "audited", "Accounts audited",
                            {"audited": audited,
                             "audit_opted_out": bool(audit.get("fravalgRevisjon")),
                             "not_audited": bool(audit.get("ikkeRevidertAarsregnskap"))},
                            snap, base + "/revisjon", **common)
        if published:
            self.c.set_section("accounts", AVAILABLE, "latest filed annual accounts retrieved")
        else:
            self.c.set_section("accounts", NOT_AVAILABLE, "no financial values in the filing")

    def fetch_filing_years(self) -> Snapshot:
        """Only the fetch (thread-safe): Brreg limits this endpoint to ~30 requests/minute, so
        callers run it alongside the other research; a slot further away than
        `history_max_wait` is skipped rather than waited for."""
        return self._get(filing_years_url(self.orgnr), "brreg.filing_years",
                         max_wait=self.history_max_wait, retries=1)

    def filing_years(self, snap: Snapshot | None = None) -> None:
        S = S_ACCOUNTS
        snap = snap or self.fetch_filing_years()
        skipped = bool(snap.error and snap.error.startswith("time_budget: rate_limit_wait"))
        self.c.note_source(S, snap, "rate_limit_skipped" if skipped else None)
        if not snap.ok:
            if skipped or snap.status == 429:
                self._absent(S, "filing_years", "Years with filed annual-account copies",
                             RATE_LIMIT_REASON, availability=BLOCKED)
                return
            state, reason = failure_state(snap)
            self._absent(S, "filing_years", "Years with filed annual-account copies", reason,
                         availability=state)
            return
        self.c.keep_snapshot(snap, OFFICIAL_ACCOUNTS)
        self.c.checked.add("filing_years")
        try:
            years = sorted(str(y) for y in snap.json())
        except (ValueError, TypeError):
            self._absent(S, "filing_years", "Years with filed annual-account copies",
                         "unreadable response", availability=FAILED)
            return
        if years:
            self._claim(S, "filing_years", "Years with filed annual-account copies", years, snap,
                        "", source_class=OFFICIAL_ACCOUNTS)
        else:
            self._absent(S, "filing_years", "Years with filed annual-account copies",
                         "checked: no annual-account copies listed", snap)

