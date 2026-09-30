from conftest import brreg, research


def test_every_sentence_cites_published_claims(equinor):
    summary = equinor["summary"]
    assert summary["generated_by"] == "deterministic"
    claims = {c["id"]: c for c in equinor["claims"]}
    evidence = {e["id"] for e in equinor["evidence"]}
    assert summary["sentences"]
    for sentence in summary["sentences"]:
        assert sentence["claim_ids"] and sentence["evidence_ids"]
        for cid in sentence["claim_ids"]:
            assert claims[cid]["availability"] == "available"
        assert set(sentence["evidence_ids"]) <= evidence


def test_summary_explains_business_size_leaders_places_changes_unknowns(equinor):
    text = equinor["summary"]["text"]
    assert "EQUINOR ASA" in text and "Utvinning av råolje" in text
    assert "67 956 000 000 USD" in text
    assert "CEO (daglig leder)" in text
    assert "35 registered workplaces" in text
    assert "First observation" in text
    unknown = {u["section"] for u in equinor["summary"]["unknowns"]}
    assert "website_and_profiles" in unknown   # web research disabled in this test


def test_bankruptcy_is_stated_first(tmp_path):
    import json

    from signalpost.registry import entity_url
    responses = brreg("810034882")
    url = entity_url("810034882")
    entity = json.loads(responses[url][1])
    entity["konkurs"] = True
    entity["konkursdato"] = "2026-09-01"
    responses[url] = (200, json.dumps(entity).encode(), {})
    env = research(tmp_path, responses, "810034882")
    assert env["summary"]["sentences"][0]["text"].startswith(
        "Important: the registry records the company as bankrupt (registered 2026-09-01)")
