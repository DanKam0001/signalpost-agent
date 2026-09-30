import json
from decimal import Decimal

from conftest import (FIXTURES, brreg, claims_by_field, evidence_of, research, resolve_pointer)

from signalpost.model import SECTIONS, STATES
from signalpost.registry import entity_url

TOP_KEYS = {"organisation_number", "status", "run", "legal_identity", "sections", "claims",
            "evidence", "source_snapshots", "changes", "summary", "errors", "operations"}


def _bodies() -> dict:
    out = {}
    for url, (status, body, _) in brreg("923609016").items():
        out[url] = json.loads(body, parse_float=Decimal)
    return out


def test_envelope_shape_and_sections(equinor):
    assert TOP_KEYS <= set(equinor)
    assert equinor["status"] == "available"
    assert equinor["run"]["terminal_status"] == "completed"
    assert set(equinor["sections"]) == set(SECTIONS)
    for section in equinor["sections"].values():
        assert section["availability"] in STATES
        assert isinstance(section["claim_ids"], list)
    assert equinor["operations"]["third_party_cost_usd"] == 0
    json.dumps(equinor, ensure_ascii=False)  # serialisable


def test_every_available_claim_has_complete_evidence(equinor):
    evidence = {e["id"]: e for e in equinor["evidence"]}
    for claim in equinor["claims"]:
        if claim["availability"] != "available":
            continue
        assert claim["evidence_ids"], claim["field"]
        for ev_id in claim["evidence_ids"]:
            ev = evidence[ev_id]
            assert ev["source_url"].startswith("https://data.brreg.no/")
            assert ev["human_url"].startswith("https://virksomhet.brreg.no/")
            assert ev["retrieved_at"].endswith("Z")
            assert len(ev["content_sha256"]) == 64
            assert ev["extraction_method"] and "json_pointer" in ev


def test_json_pointers_resolve_into_the_exact_source(equinor):
    bodies = _bodies()
    scalar_fields = {"legal_name", "registration_date", "founding_date", "registered_employees",
                     "vat_registered", "in_group", "operating_revenue", "net_result",
                     "total_assets", "total_equity", "total_equity_and_debt", "municipality",
                     "workplace_count", "registered_website"}
    for claim in equinor["claims"]:
        for ev in evidence_of(equinor, claim):
            target = resolve_pointer(bodies[ev["source_url"]], ev["json_pointer"])
            if claim["field"] in scalar_fields:
                expected = claim["value"]
                if isinstance(target, Decimal):
                    target = int(target) if target == target.to_integral_value() else target
                if isinstance(target, str) and len(target) >= 10 and claim["field"].endswith(
                        "_date"):
                    target = target[:10]
                assert target == expected, claim["field"]


def test_financials_exact_as_filed(equinor):
    assets = claims_by_field(equinor, "total_assets")[0]
    equity_debt = claims_by_field(equinor, "total_equity_and_debt")[0]
    assert assets["value"] == 103432000000
    assert equity_debt["value"] == 103431000000   # filed as-is, never "fixed"
    assert assets["currency"] == "USD"
    assert assets["reporting_period"] == {"from": "2025-01-01", "to": "2025-12-31"}
    assert evidence_of(equinor, assets)[0]["json_pointer"] == "/0/eiendeler/sumEiendeler"
    assert evidence_of(equinor, assets)[0]["record_date"] == "2025-12-31"


def test_roles_subunits_and_privacy(equinor):
    roles = claims_by_field(equinor, "role")
    assert any(r["value"]["role_code"] == "DAGL" for r in roles)
    assert all("sistEndret" in (evidence_of(equinor, r)[0]["record_date_field"] or "")
               for r in roles)
    assert claims_by_field(equinor, "workplace_count")[0]["value"] == 35
    assert len(claims_by_field(equinor, "workplace")) == 35
    text = json.dumps(equinor, ensure_ascii=False)
    assert "fodselsdato" not in text and "1970-01-01" not in text


def test_employees_only_when_registered(tmp_path):
    responses = brreg("810034882")
    url = entity_url("810034882")
    entity = json.loads(responses[url][1])
    entity["harRegistrertAntallAnsatte"] = False
    responses[url] = (200, json.dumps(entity).encode(), {})
    env = research(tmp_path, responses, "810034882")
    claim = claims_by_field(env, "registered_employees")[0]
    assert claim["availability"] == "not_available" and claim["value"] is None


def test_norwegian_characters_preserved(equinor):
    names = [c["value"] for c in claims_by_field(equinor, "workplace")]
    assert any("ØYGARDEN" in (n.get("municipality") or "") for n in names)


def test_deleted_entity_is_not_available_with_deletion_date(tmp_path):
    env = research(tmp_path, brreg("921326904"), "921326904")
    assert env["status"] == "not_available"
    deleted = claims_by_field(env, "deleted")[0]
    assert deleted["value"]["deleted_on"] == "2019-06-18"
    assert deleted["availability"] == "available" and deleted["evidence_ids"]


def test_unknown_entity_is_not_available(tmp_path):
    env = research(tmp_path, {}, "908660242")
    assert env["status"] == "not_available"
    assert all(env["sections"][s]["availability"] == "not_available" for s in SECTIONS[:5])


def test_refusal_is_blocked_and_errors_are_failed(tmp_path):
    refused = {entity_url("923609016"): (403, b"", {})}
    env = research(tmp_path / "a", refused, "923609016")
    assert env["status"] == "blocked"
    broken = {entity_url("923609016"): (500, b"", {})}
    env = research(tmp_path / "b", broken, "923609016")
    assert env["status"] == "failed"
    assert env["errors"]


def test_section_failure_keeps_rest_of_envelope(tmp_path):
    responses = brreg("923609016")
    responses[f"{entity_url('923609016')}/roller"] = (503, b"", {})
    env = research(tmp_path, responses, "923609016")
    assert env["status"] == "available"
    assert env["sections"]["leadership_and_workplaces"]["availability"] == "available"  # subunits
    assert "roles: source error" in env["sections"]["leadership_and_workplaces"]["reason"]
    assert claims_by_field(env, "total_assets")


def test_fixture_bodies_exist():
    assert (FIXTURES / "brreg" / "923609016.entity.json").exists()
