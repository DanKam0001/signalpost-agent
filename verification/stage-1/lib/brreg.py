"""Independent Brreg client + reference model (oracle) for Signalpost verification.

Written by @verifier from the specification only (ledger stage-1, docs/official). Stdlib only.
The oracle states what the registry says about a company; checks compare the product's
published claims against it.
"""
import hashlib, json, os, time, urllib.request, urllib.error

UA = "signalpost-verifier/1.0 (+team.local)"
CACHE = os.environ.get("VERIFY_CACHE", os.path.join(os.path.dirname(__file__), "..", ".cache", "brreg"))
W = [3, 2, 7, 6, 5, 4, 3, 2]
ENH = "https://data.brreg.no/enhetsregisteret/api/enheter/{}"
ROL = "https://data.brreg.no/enhetsregisteret/api/enheter/{}/roller"
UND = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={}&size=100&page={}"
REG = "https://data.brreg.no/regnskapsregisteret/regnskap/{}"
AAR = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{}/aar"


def check_digit(base8):
    r = 11 - sum(int(c) * w for c, w in zip(base8, W)) % 11
    return None if r == 10 else (0 if r == 11 else r)


def valid_orgnr(s):
    return isinstance(s, str) and len(s) == 9 and s.isdigit() and check_digit(s[:8]) == int(s[8])


def normalise(raw):
    return "".join(str(raw).split())


def fetch(url, use_cache=True, retries=4):
    """Return (status, body_bytes). Cached on disk by URL hash."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest())
    if use_cache and os.path.exists(p):
        with open(p, "rb") as f:
            d = f.read()
        st, body = d.split(b"\n", 1)
        return int(st), body
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                st, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            st, body = e.code, e.read()
        except Exception:
            time.sleep(1 + 2 * a); continue
        if st in (429, 500, 502, 503, 504):
            time.sleep(1 + 2 * a); continue
        with open(p, "wb") as f:
            f.write(str(st).encode() + b"\n" + body)
        return st, body
    return 0, b""


def jget(url, **kw):
    st, body = fetch(url, **kw)
    try:
        return st, json.loads(body) if body else None
    except Exception:
        return st, None


def person_name(n):
    if not n:
        return None
    return " ".join(x for x in [n.get("fornavn"), n.get("mellomnavn"), n.get("etternavn")] if x)


def model(orgnr, use_cache=True):
    """Reference model: expected envelope status + registry facts for one input string."""
    o = normalise(orgnr)
    if not valid_orgnr(o):
        return {"orgnr": o, "status": "failed", "reason": "invalid_organisation_number"}
    st, e = jget(ENH.format(o), use_cache=use_cache)
    if st == 404:
        return {"orgnr": o, "status": "not_available", "reason": "404"}
    if st == 410:
        return {"orgnr": o, "status": "not_available", "reason": "410", "deleted": e}
    if st != 200 or not e:
        return {"orgnr": o, "status": "unknown", "reason": f"oracle fetch {st}"}
    f = {"orgnr": o, "status": "available", "raw": e}
    f["name"] = e.get("navn")
    f["org_form"] = (e.get("organisasjonsform") or {}).get("kode")
    a = e.get("forretningsadresse") or {}
    f["postcode"] = a.get("postnummer"); f["municipality"] = a.get("kommune")
    f["street"] = a.get("adresse") or []
    f["nace1"] = (e.get("naeringskode1") or {}).get("kode")
    f["employees"] = e.get("antallAnsatte") if e.get("harRegistrertAntallAnsatte") else None
    f["employees_registered"] = bool(e.get("harRegistrertAntallAnsatte"))
    f["website"] = e.get("hjemmeside")
    f["flags"] = {k: e.get(k) for k in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning")}
    f["latest_accounts_year"] = e.get("sisteInnsendteAarsregnskap")
    # roles
    st, r = jget(ROL.format(o), use_cache=use_cache)
    f["roles_status"] = st
    roles = []
    for g in (r or {}).get("rollegrupper", []) if st == 200 else []:
        for x in g.get("roller", []):
            nm = person_name((x.get("person") or {}).get("navn")) or (x.get("enhet") or {}).get("navn")
            if isinstance(nm, list):
                nm = " ".join(nm)
            roles.append({"type": (x.get("type") or {}).get("kode"), "name": nm,
                          "orgnr": (x.get("enhet") or {}).get("organisasjonsnummer"),
                          "resigned": x.get("avregistrert"), "sistEndret": g.get("sistEndret"),
                          "birth": (x.get("person") or {}).get("fodselsdato")})
    f["roles"] = roles
    f["ceo"] = sorted({x["name"] for x in roles if x["type"] == "DAGL" and not x["resigned"] and x["name"]})
    f["chair"] = sorted({x["name"] for x in roles if x["type"] == "LEDE" and not x["resigned"] and x["name"]})
    # subunits (count only; first page)
    st, u = jget(UND.format(o, 0), use_cache=use_cache)
    f["subunits_status"] = st
    f["subunit_count"] = ((u or {}).get("page") or {}).get("totalElements", 0) if st == 200 else None
    f["subunit_orgnrs_page0"] = [x["organisasjonsnummer"] for x in ((u or {}).get("_embedded") or {}).get("underenheter", [])]
    # accounts
    st, acc = jget(REG.format(o), use_cache=use_cache)
    f["accounts_status"] = st
    f["accounts"] = None
    if st == 200 and isinstance(acc, list) and acc:
        # the latest period; if several (SELSKAP/KONSERN), keep all
        f["accounts"] = acc
    st, yrs = jget(AAR.format(o), use_cache=use_cache)
    f["account_years"] = yrs if st == 200 else None
    return f


def account_numbers(acc_list):
    """Every numeric leaf in the filed accounts (the set of values that may legitimately be published)."""
    out = set()
    def walk(x):
        if isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            out.add(float(x))
    walk(acc_list or [])
    return out


def key_financials(acc):
    """Key figures from one filing (as filed)."""
    rr = acc.get("resultatregnskapResultat") or {}
    dr = rr.get("driftsresultat") or {}
    ek = acc.get("egenkapitalGjeld") or {}
    return {
        "revenue": (dr.get("driftsinntekter") or {}).get("sumDriftsinntekter"),
        "operating_result": dr.get("driftsresultat"),
        "profit_before_tax": rr.get("ordinaertResultatFoerSkattekostnad"),
        "net_result": rr.get("aarsresultat"),
        "total_assets": (acc.get("eiendeler") or {}).get("sumEiendeler"),
        "equity": (ek.get("egenkapital") or {}).get("sumEgenkapital"),
        "debt": (ek.get("gjeldOversikt") or {}).get("sumGjeld"),
        "currency": acc.get("valuta"),
        "period_from": (acc.get("regnskapsperiode") or {}).get("fraDato"),
        "period_to": (acc.get("regnskapsperiode") or {}).get("tilDato"),
        "type": acc.get("regnskapstype"),
    }


def resolve_pointer(doc, ptr):
    """RFC 6901 JSON pointer."""
    if ptr in ("", None):
        return doc
    if not ptr.startswith("/"):
        raise KeyError(ptr)
    cur = doc
    for tok in ptr[1:].split("/"):
        tok = tok.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(tok)]
        else:
            cur = cur[tok]
    return cur
