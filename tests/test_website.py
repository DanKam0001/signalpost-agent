import json

from conftest import brreg, claims_by_field, evidence_of, page, research

from signalpost.registry import entity_url

SITE = "https://sandneselektriske.no"
TEXT = {"content-type": "text/plain"}


def _site(robots: bytes = b"User-agent: *\nAllow: /\n") -> dict:
    return {
        f"{SITE}/robots.txt": (200, robots, TEXT),
        f"{SITE}/": page("verified_home.html"),
        f"{SITE}/kontakt": page("plain_page.html"),
        f"{SITE}/om-oss": page("plain_page.html"),
        f"{SITE}/karriere": page("verified_careers.html"),
        f"{SITE}/nyheter": page("verified_news.html"),
        f"{SITE}/nyheter/rss.xml": page("verified_rss.xml",
                                        headers={"content-type": "application/rss+xml"}),
    }


def _without_email(responses: dict) -> dict:
    url = entity_url("810034882")
    entity = json.loads(responses[url][1])
    entity.pop("epostadresse", None)
    responses[url] = (200, json.dumps(entity).encode(), {})
    return responses


def _run(tmp_path, extra: dict, row=None, allow=("sandneselektriske.no",), strip_email=False):
    responses = brreg("810034882")
    if strip_email:
        responses = _without_email(responses)
    responses.update(extra)
    return research(tmp_path, responses, "810034882", web=True, row=row, allow_hosts=allow)


def test_verified_site_by_org_number_publishes_company_owned_facts(tmp_path):
    env = _run(tmp_path, _site())
    web = env["sections"]["website_and_profiles"]
    assert web["availability"] == "available", web
    site = claims_by_field(env, "official_website")[0]
    assert site["value"] == f"{SITE}/"
    assert site["verification"] == "organisation_number_on_site"
    proof = evidence_of(env, site)[0]
    assert proof["source_class"] == "company_owned"
    assert "810 034 882" in proof["claim_span"] and proof["css_selector"].startswith("footer#footer")
    assert claims_by_field(env, "site_description")[0]["value"].startswith("Vi er en elektro")
    assert claims_by_field(env, "brand_name")[0]["value"] == "Sandnes Elektro"
    platforms = sorted(c["value"]["platform"] for c in claims_by_field(env, "social_profile"))
    assert platforms == ["Facebook", "LinkedIn", "YouTube"]
    assert [c["value"] for c in claims_by_field(env, "site_email")] == ["post@sandneselektriske.no"]


def test_jobs_and_dated_news(tmp_path):
    env = _run(tmp_path, _site())
    jobs = claims_by_field(env, "job_posting")
    titles = sorted(j["value"]["title"] for j in jobs)
    assert titles == ["Elektriker (fast stilling)", "Lærling elektrofag 2027"]
    jsonld = next(j for j in jobs if j["value"]["source"] == "JobPosting structured data")
    assert jsonld["value"]["date_posted"] == "2026-09-15"
    assert evidence_of(env, jsonld)[0]["record_date"] == "2026-09-15"
    news = claims_by_field(env, "news_item")
    assert {n["value"]["date"] for n in news} == {"2026-08-30", "2026-05-02", "2026-08-17"}
    assert all(n["value"]["date"] for n in news)
    assert env["sections"]["hiring_and_activity"]["availability"] == "available"
    assert claims_by_field(env, "careers_page")


def test_javascript_is_never_executed(tmp_path):
    env = _run(tmp_path, _site())
    assert "evil.example" not in json.dumps(env)


def test_name_and_address_is_strong_proof(tmp_path):
    site = "https://www.elektro-fixture.no"
    extra = {f"{site}/robots.txt": (404, b"", TEXT), f"{site}/": page("name_address_home.html")}
    env = _run(tmp_path, extra, row={"website": site + "/"}, allow=("www.elektro-fixture.no",),
               strip_email=True)
    claim = claims_by_field(env, "official_website")[0]
    assert claim["verification"] == "name_and_address_on_site"


def test_no_proof_publishes_nothing(tmp_path):
    site = "https://www.sandnes-elektro.no"
    extra = {f"{site}/robots.txt": (404, b"", TEXT), f"{site}/": page("no_proof_home.html")}
    env = _run(tmp_path, extra, row={"website": site + "/"}, allow=("www.sandnes-elektro.no",),
               strip_email=True)
    assert env["sections"]["website_and_profiles"]["availability"] == "ambiguous"
    assert not claims_by_field(env, "official_website")
    assert not [c for c in env["claims"] if c["scope"] == "website"
                and c["availability"] == "available"]
    assert env["sections"]["hiring_and_activity"]["availability"] == "not_available"


def test_other_company_org_number_is_ambiguous(tmp_path):
    site = "https://www.dnb-fixture.no"
    extra = {f"{site}/robots.txt": (404, b"", TEXT), f"{site}/": page("conflict_home.html")}
    env = _run(tmp_path, extra, row={"website": site + "/"}, allow=("www.dnb-fixture.no",),
               strip_email=True)
    web = env["sections"]["website_and_profiles"]
    assert web["availability"] == "ambiguous" and "984851006" in web["reason"]
    assert not claims_by_field(env, "official_website")
    assert not claims_by_field(env, "social_profile")


def test_robots_disallow_is_blocked_and_nothing_else_fetched(tmp_path):
    env = _run(tmp_path, _site(robots=b"User-agent: *\nDisallow: /\n"))
    assert env["sections"]["website_and_profiles"]["availability"] == "blocked"
    site_requests = [s for s in env["source_snapshots"] if s["url"].startswith(SITE)]
    assert [s["url"] for s in site_requests] == [f"{SITE}/robots.txt"]
    assert env["operations"]["requests_by_source"].get("site.home") is None


def test_refusals_are_blocked(tmp_path):
    for status in (403, 429):
        extra = {f"{SITE}/robots.txt": (404, b"", TEXT), f"{SITE}/": (status, b"no", TEXT)}
        env = _run(tmp_path / str(status), extra)
        assert env["sections"]["website_and_profiles"]["availability"] == "blocked"
        assert env["sections"]["hiring_and_activity"]["availability"] == "blocked"


def test_unreachable_site_is_not_available(tmp_path):
    extra = {f"{SITE}/robots.txt": (None, b"", {}), f"{SITE}/": (None, b"", {})}
    env = _run(tmp_path, extra)
    assert env["sections"]["website_and_profiles"]["availability"] == "not_available"
    assert "could not be reached" in env["sections"]["website_and_profiles"]["reason"]


def test_no_candidates_is_not_available(tmp_path):
    env = _run(tmp_path, {}, strip_email=True, allow=("www.sandneselektriske.no",))
    # Only the conservative name guess is tried; here it answers 404.
    assert env["sections"]["website_and_profiles"]["availability"] == "not_available"
    assert env["sections"]["hiring_and_activity"]["availability"] == "not_available"


def test_robots_blocked_candidate_is_recorded_when_another_candidate_fails(tmp_path):
    site = "https://www.robots-fixture.no"
    extra = {f"{site}/robots.txt": (200, b"User-agent: *\nDisallow: /\n", TEXT),
             f"{SITE}/robots.txt": (None, b"", {}), f"{SITE}/": (None, b"", {})}
    env = _run(tmp_path, extra, row={"website": site + "/"},
               allow=("sandneselektriske.no", "www.robots-fixture.no"))
    sources = env["sections"]["website_and_profiles"]["sources"]
    entry = next(s for s in sources if s["url"] == site + "/" and s["source"] == "site.home")
    assert entry["outcome"].startswith("robots") and entry["robots_http_status"] == 200
    outcomes = {s["url"]: s["outcome"] for s in sources if s["source"] == "site.candidate"}
    assert outcomes == {site + "/": "robots_disallowed", f"{SITE}/": "unreachable"}
    assert f"{site}/" not in [s["url"] for s in env["source_snapshots"]]


def _candidates(env):
    return [(s["candidate_origin"], s["outcome"]) for s in
            env["sections"]["website_and_profiles"]["sources"] if s["source"] == "site.candidate"]


def test_every_candidate_is_recorded_with_its_outcome(tmp_path):
    assert _candidates(_run(tmp_path / "v", _site())) == [("registry_email_domain", "verified")]
    for name, fixture, outcome in (("np", "no_proof_home.html", "no_proof"),
                                   ("co", "conflict_home.html", "other_orgnr")):
        site = f"https://www.{name}-fixture.no"
        extra = {f"{site}/robots.txt": (404, b"", TEXT), f"{site}/": page(fixture)}
        env = _run(tmp_path / name, extra, row={"website": site + "/"},
                   allow=(f"www.{name}-fixture.no",), strip_email=True)
        assert _candidates(env) == [("input_row", outcome)]
    extra = {f"{SITE}/robots.txt": (404, b"", TEXT), f"{SITE}/": (403, b"no", TEXT)}
    assert _candidates(_run(tmp_path / "b", extra)) == [("registry_email_domain", "blocked")]
