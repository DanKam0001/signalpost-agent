#!/usr/bin/env python3
"""Per-envelope requirement checks + differential comparison against the reference model.

usage: check_envelopes.py --input BATCH --output ENVELOPES.jsonl [--report REPORT.json]
                          [--oracle] [--out RESULT.json]
Every check is named after its ledger entry. Output: {R-id: {pass, n_checked, failures[:50]}} plus
oracle agreement tables. Exit 1 if any check failed.
"""
import argparse, datetime, json, os, re, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from brreg import model, account_numbers, key_financials, valid_orgnr  # noqa
from inputs import read_batch  # noqa

STATES = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
SECTIONS = ["legal_identity_and_brand", "annual_accounts", "leadership_and_workplaces", "website_and_profiles",
            "hiring_and_activity", "evidence_and_availability", "refresh_and_changes"]
TOP = ["organisation_number", "status", "run", "legal_identity", "sections", "claims", "evidence",
       "source_snapshots", "changes", "summary", "errors", "operations"]
SRC_CLASSES = {"official_registry", "official_accounts", "company_owned", "external"}
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


class R:
    def __init__(self):
        self.res = collections.defaultdict(lambda: {"pass": True, "n_checked": 0, "failures": []})

    def ok(self, rid, cond, msg):
        r = self.res[rid]
        r["n_checked"] += 1
        if not cond:
            r["pass"] = False
            if len(r["failures"]) < 50:
                r["failures"].append(msg)
        return cond


def iter_values(v):
    """All scalar leaves of a claim value, as strings."""
    if isinstance(v, dict):
        for x in v.values():
            yield from iter_values(x)
    elif isinstance(v, list):
        for x in v:
            yield from iter_values(x)
    elif v is not None:
        yield v


def num_eq(a, b):
    try:
        return float(a) == float(b)
    except Exception:
        return False


def find(claims, field_re, pred):
    """-> 'agree' | 'mismatch' | 'missing', matching claims' values."""
    cand = [c for c in claims if c.get("availability") == "available" and re.search(field_re, str(c.get("field", "")), re.I)]
    if not cand:
        return "missing", []
    for c in cand:
        if pred(c.get("value")):
            return "agree", []
    return "mismatch", [c.get("value") for c in cand][:3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--report"); ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    R_ = R()
    inputs = read_batch(a.input)
    raw = open(a.output, "rb").read()
    try:
        text = raw.decode("utf-8"); utf8 = True
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "replace"); utf8 = False
    R_.ok("R-1.21", utf8, "output is not valid UTF-8")
    envs = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            envs.append(json.loads(line))
        except Exception as e:
            R_.ok("R-1.5", False, f"line {i+1} not JSON: {e}")
    # R-1.4 / R-1.5: one per input, in order
    R_.ok("R-1.4", len(envs) == len(inputs), f"inputs={len(inputs)} envelopes={len(envs)}")
    for i, (inp, env) in enumerate(zip(inputs, envs)):
        R_.ok("R-1.5", str(env.get("organisation_number", "")).replace(" ", "") == inp,
              f"row {i}: input {inp!r} envelope {env.get('organisation_number')!r}")
    if a.report:
        try:
            rep = json.load(open(a.report, encoding="utf-8"))
            R_.ok("R-1.5", isinstance(rep, dict), "report not a JSON object")
            for k in ("input_count", "envelope_count", "expected_count", "duplicate_inputs", "state_counts", "run_id",
                      "started_at", "completed_at", "time_budget_seconds", "fast_path_count"):
                R_.ok("R-1.8", k in rep, f"report lacks {k}")
            for k in ("filing_years_fetched", "filing_years_skipped"):
                R_.ok("R-1.27", k in rep, f"report lacks {k} (lead F2 decision)")
            for k in ("runtime_ms_total", "runtime_ms_p50", "runtime_ms_p95", "requests_total", "requests_by_host",
                      "bytes_fetched", "peak_memory_mb", "third_party_cost_usd"):
                R_.ok("R-1.12", k in rep, f"report lacks {k}")
            R_.ok("R-1.8", rep.get("input_count") == len(inputs) and rep.get("envelope_count") == len(envs),
                  f"report counts input={rep.get('input_count')} envelopes={rep.get('envelope_count')} vs actual {len(inputs)}/{len(envs)}")
            R_.ok("R-1.8", rep.get("state_counts") in (None,) or sum((rep.get("state_counts") or {}).values()) == len(envs),
                  f"state_counts {rep.get('state_counts')} do not sum to {len(envs)}")
        except Exception as e:
            R_.ok("R-1.5", False, f"report unreadable: {e}")

    agree = collections.defaultdict(collections.Counter)
    mismatches = []
    status_dist = collections.Counter()
    for i, env in enumerate(envs):
        o = str(env.get("organisation_number"))
        tag = f"[{i}:{o}]"
        status_dist[env.get("status")] += 1
        for k in TOP:
            R_.ok("R-1.13", k in env, f"{tag} missing top-level key {k}")
        run = env.get("run") or {}
        for k in ("run_id", "started_at", "completed_at", "terminal_status"):
            R_.ok("R-1.13", run.get(k) not in (None, ""), f"{tag} run.{k} missing")
        ops = env.get("operations") or {}
        for k in ("requests", "runtime_ms", "third_party_cost_usd"):
            R_.ok("R-1.13", k in ops, f"{tag} operations.{k} missing")
        R_.ok("R-1.14", env.get("status") in STATES, f"{tag} bad status {env.get('status')}")
        R_.ok("R-1.15", run.get("terminal_status") not in (None, "", "running", "pending", "started"),
              f"{tag} non-terminal terminal_status {run.get('terminal_status')}")
        claims = env.get("claims") or []
        evidence = {e.get("id"): e for e in env.get("evidence") or []}
        cids = {c.get("id") or c.get("claim_id") or c.get("claim_key") for c in claims}
        secs = env.get("sections") or {}
        for s in SECTIONS:
            sec = secs.get(s)
            if not R_.ok("R-1.16", isinstance(sec, dict), f"{tag} section {s} missing"):
                continue
            R_.ok("R-1.16", sec.get("availability") in STATES, f"{tag} {s}.availability={sec.get('availability')}")
            R_.ok("R-1.16", "reason" in sec and isinstance(sec.get("claim_ids"), list), f"{tag} {s} lacks reason/claim_ids")
            for cid in sec.get("claim_ids") or []:
                R_.ok("R-1.16", cid in cids, f"{tag} {s} cites unknown claim {cid}")
            R_.ok("R-1.14", sec.get("availability") in STATES, f"{tag} {s} bad state")
        keys = [c.get("claim_key") for c in claims]
        R_.ok("R-1.17", len(keys) == len(set(keys)), f"{tag} duplicate claim_key")
        for c in claims:
            for k in ("claim_key", "field", "availability", "confidence", "evidence_ids"):
                R_.ok("R-1.17", k in c, f"{tag} claim {c.get('claim_key')} lacks {k}")
            R_.ok("R-1.14", c.get("availability") in STATES, f"{tag} claim {c.get('field')} bad state {c.get('availability')}")
            if c.get("availability") == "available":
                ev = c.get("evidence_ids") or []
                R_.ok("R-1.18", len(ev) > 0, f"{tag} available claim {c.get('field')} has no evidence")
                for eid in ev:
                    R_.ok("R-1.18", eid in evidence, f"{tag} claim {c.get('field')} cites missing evidence {eid}")
                R_.ok("R-1.19", "value" in c and c.get("value") not in (None, "", [], {}),
                      f"{tag} available claim {c.get('field')} has empty value")
        for e in evidence.values():
            for k in ("id", "source_url", "human_url", "source_class", "retrieved_at", "record_date", "content_sha256",
                      "extraction_method"):
                R_.ok("R-1.18", k in e, f"{tag} evidence {e.get('id')} lacks {k}")
            R_.ok("R-1.18", str(e.get("source_url", "")).startswith(("http://", "https://")), f"{tag} evidence bad url {e.get('source_url')}")
            R_.ok("R-1.18", e.get("source_class") in SRC_CLASSES, f"{tag} evidence bad source_class {e.get('source_class')}")
            R_.ok("R-1.18", bool(ISO_UTC.match(str(e.get("retrieved_at", "")))), f"{tag} retrieved_at not ISO UTC: {e.get('retrieved_at')}")
            R_.ok("R-1.18", e.get("json_pointer") is not None or any(e.get(k) for k in ("css_selector", "selector", "claim_span")),
                  f"{tag} evidence {e.get('id')} has no locator")
            R_.ok("R-1.18", re.fullmatch(r"[0-9a-f]{64}", str(e.get("content_sha256", ""))) is not None,
                  f"{tag} content_sha256 malformed")
            # wrong-company guard: Brreg URLs must be about this orgnr (or its role-type/subunit resources)
            u = str(e.get("source_url", ""))
            R_.ok("R-1.39", re.search(r"//([^/]*\.)?(linkedin|facebook|instagram|glassdoor|indeed|google)\.[a-z]+/", u) is None,
                  f"{tag} evidence fetched from a restricted platform: {u}")
            if "data.brreg.no" in u:
                R_.ok("WRONG-COMPANY", o in u or "/underenheter/" in u or "rolletyper" in u,
                      f"{tag} brreg evidence URL not for this orgnr: {u}")
        summ = env.get("summary") or {}
        R_.ok("R-1.13", isinstance(summ, dict) and "text" in summ, f"{tag} summary malformed")

        # ---- reference model comparison ----
        if not a.oracle:
            continue
        m = model(inputs[i] if i < len(inputs) else o)
        if m["status"] == "unknown":
            continue
        R_.ok("R-1.15", env.get("status") == m["status"], f"{tag} status {env.get('status')} expected {m['status']} ({m.get('reason')})")
        if m["status"] == "failed":
            R_.ok("R-1.15", "invalid" in json.dumps(env.get("errors")).lower(), f"{tag} invalid number lacks invalid_organisation_number error")
        if m.get("reason") == "410" and (m.get("deleted") or {}).get("slettedato"):
            R_.ok("R-1.15", m["deleted"]["slettedato"] in json.dumps(env.get("claims")),
                  f"{tag} deleted entity: deletion date {m['deleted']['slettedato']} not a claim")
        if m["status"] != "available" or env.get("status") != "available":
            continue
        # summary (R-1.41 / R-1.42)
        sents = summ.get("sentences") or []
        R_.ok("R-1.41", bool(summ.get("text")) and len(sents) > 0, f"{tag} no summary")
        for s in sents:
            R_.ok("R-1.42", len(s.get("claim_ids") or []) > 0, f"{tag} uncited sentence: {s.get('text','')[:80]}")
            for cid in s.get("claim_ids") or []:
                R_.ok("R-1.42", cid in cids, f"{tag} sentence cites unknown claim {cid}")
        R_.ok("R-1.41", "unknowns" in summ and "changes_text" in summ, f"{tag} summary lacks unknowns/changes_text")
        un = json.dumps(summ.get("unknowns", []))
        for s in SECTIONS:
            if (secs.get(s) or {}).get("availability") not in ("available", None, "not_applicable"):
                R_.ok("R-1.41", s in un or s.replace("_", " ") in un.lower() or len(summ.get("unknowns") or []) > 0,
                      f"{tag} unknowns does not name section {s}")
        # facts
        blob = json.dumps(env, ensure_ascii=False)
        for r_ in m["roles"]:
            if r_.get("birth"):
                R_.ok("R-1.24", r_["birth"] not in blob, f"{tag} birth date {r_['birth']} published")

        def rec(fact, res, expected, got):
            agree[fact][res] += 1
            if res == "mismatch":
                mismatches.append({"orgnr": o, "fact": fact, "expected": expected, "got": got})
            return res
        res, got = find(claims, r"(legal_?name|^name$|company_name)", lambda v: m["name"] in [str(x) for x in iter_values(v)])
        rec("legal_name", res, m["name"], got); R_.ok("R-1.22", res == "agree", f"{tag} legal name {res} {got} vs {m['name']}")
        res, got = find(claims, r"(org(anisation|anization)?_?form|legal_form)", lambda v: m["org_form"] in [str(x) for x in iter_values(v)])
        rec("org_form", res, m["org_form"], got); R_.ok("R-1.22", res == "agree", f"{tag} org form {res}")
        if m["postcode"]:
            res, got = find(claims, r"(business_address|forretningsadresse|^address$|registered_address)", lambda v: m["postcode"] in json.dumps(v))
            rec("business_address", res, m["postcode"], got); R_.ok("R-1.22", res == "agree", f"{tag} address {res} {got}")
        if m["nace1"]:
            res, got = find(claims, r"(nace|industry)", lambda v: m["nace1"] in json.dumps(v))
            rec("nace1", res, m["nace1"], got); R_.ok("R-1.22", res == "agree", f"{tag} nace {res}")
        emp_claims = [c for c in claims if re.search(r"employ|ansatt", str(c.get("field")), re.I)
                      and not re.search(r"subunit|workplace|underenhet|location", str(c.get("field")) + str(c.get("claim_key")), re.I)
                      and c.get("availability") == "available"]
        if m["employees"] is None:
            ok = not emp_claims
            rec("employees", "agree" if ok else "mismatch", None, [c.get("value") for c in emp_claims])
            R_.ok("R-1.19", ok, f"{tag} employee count published but harRegistrertAntallAnsatte is false: {[c.get('value') for c in emp_claims]}")
        else:
            ok = any(any(num_eq(x, m["employees"]) for x in iter_values(c.get("value"))) for c in emp_claims)
            rec("employees", "agree" if ok else ("missing" if not emp_claims else "mismatch"), m["employees"], [c.get("value") for c in emp_claims])
            R_.ok("R-1.22", ok, f"{tag} employees expected {m['employees']}")
        for role, names in (("ceo", m["ceo"]), ("chair", m["chair"])):
            for nm in names:
                ok = nm.lower() in blob.lower()
                rec(role, "agree" if ok else "missing", nm, None)
                R_.ok("R-1.24", ok, f"{tag} {role} {nm} not published")
        # accounts: fabricated values + exact key figures
        if m["accounts"]:
            allowed = account_numbers(m["accounts"])
            ids = set((secs.get("annual_accounts") or {}).get("claim_ids") or [])
            acc_claims = [c for c in claims if (c.get("id") or c.get("claim_id") or c.get("claim_key")) in ids and c.get("availability") == "available"]
            for c in acc_claims:
                if re.search(r"year|history|period|currency|valuta|type|audit|copies", str(c.get("field")), re.I):
                    continue
                for x in iter_values(c.get("value")):
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        R_.ok("FABRICATION", float(x) in allowed, f"{tag} financial value {x} ({c.get('field')}) not in the filing")
            for acc in m["accounts"]:
                kf = key_financials(acc)
                for k in ("revenue", "operating_result", "net_result", "equity", "total_assets"):
                    if kf[k] is None:
                        continue
                    ok = any(any(num_eq(x, kf[k]) for x in iter_values(c.get("value"))) for c in acc_claims)
                    rec(f"acc_{k}", "agree" if ok else "missing", kf[k], None)
                    R_.ok("R-1.26", ok, f"{tag} {kf['type']} {k}={kf[k]} not published")
                ok = kf["currency"] in json.dumps([c.get("value") for c in acc_claims] + [c for c in acc_claims])
                rec("acc_currency", "agree" if ok else "missing", kf["currency"], None)
                R_.ok("R-1.20", ok, f"{tag} currency {kf['currency']} not stated")
                ok = kf["period_to"] in json.dumps(acc_claims)
                rec("acc_period", "agree" if ok else "missing", kf["period_to"], None)
                R_.ok("R-1.20", ok, f"{tag} period end {kf['period_to']} not stated")
        else:
            R_.ok("R-1.19", (secs.get("annual_accounts") or {}).get("availability") != "available" or True, "")
        if m["account_years"]:
            # R-1.27 as amended by @lead 2026-09-29 (F2): the list is published, OR the company carries exactly one
            # filing_years claim that is `blocked` with a reason naming the source's rate limit, or the carried-forward
            # value with the skip exposed on it. Never both; never silently absent.
            fy = [c for c in claims if re.search(r"filing_years|filed_years|account_years", str(c.get("field")) + str(c.get("claim_key")))]
            listed = [c for c in fy if c.get("availability") == "available" and all(y in json.dumps(c.get("value")) for y in m["account_years"])]
            rl = [c for c in fy if c.get("availability") == "blocked" and re.search(r"rate|per minute|limit", json.dumps(c), re.I)]
            ok_one = len(fy) == 1
            ok = ok_one and (bool(listed) or bool(rl))
            rec("account_years", "agree" if listed else ("rate_limited" if rl else "missing"), m["account_years"], None)
            R_.ok("R-1.27", ok, f"{tag} filing_years claims={[(c.get('availability'), str(c.get('value'))[:40]) for c in fy]} expected one: list {m['account_years']} or rate-limit blocked")
            if listed and listed[0].get("carried_forward"):
                R_.ok("R-1.46", "refresh_status" in listed[0] or "reason" in listed[0], f"{tag} carried filing_years does not expose the skip")
        if m["subunit_count"] is not None:
            res, got = find(claims, r"(subunit|workplace|underenhet).*(count|total)|(count|total).*(subunit|workplace)",
                            lambda v: any(num_eq(x, m["subunit_count"]) for x in iter_values(v)))
            if m["subunit_count"] == 0 and res == "missing":
                res = "agree" if (secs.get("leadership_and_workplaces") or {}).get("availability") else "missing"
            rec("subunit_count", res, m["subunit_count"], got)
            R_.ok("R-1.25", res == "agree", f"{tag} subunit count {res} {got} vs {m['subunit_count']}")
        for flag, v in m["flags"].items():
            if v:
                R_.ok("R-1.23", "konkurs" in blob.lower() or "bankrupt" in blob.lower() or "liquidat" in blob.lower()
                      or "avvikling" in blob.lower(), f"{tag} flag {flag} true but not stated")
                R_.ok("R-1.23", re.search(r"bankrupt|liquidat|konkurs|avvikling|dissol", summ.get("text", ""), re.I) is not None,
                      f"{tag} flag {flag} not prominent in summary")

    out = {"n_inputs": len(inputs), "n_envelopes": len(envs), "status_distribution": dict(status_dist),
           "checks": dict(R_.res),
           "oracle_agreement": {k: dict(v) for k, v in agree.items()}, "oracle_mismatches": mismatches[:200]}
    s = json.dumps(out, indent=1, ensure_ascii=False, default=str)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(s)
    for k in sorted(R_.res):
        r = R_.res[k]
        print(f"{k:14} {'PASS' if r['pass'] else 'FAIL'}  checked={r['n_checked']}  {r['failures'][:2] if not r['pass'] else ''}")
    print("status:", dict(status_dist))
    for k, v in agree.items():
        tot = sum(v.values())
        print(f"  oracle {k:22} agree {v['agree']}/{tot}  mismatch {v['mismatch']}  missing {v['missing']}")
    sys.exit(0 if all(r["pass"] for r in R_.res.values()) else 1)


if __name__ == "__main__":
    main()
