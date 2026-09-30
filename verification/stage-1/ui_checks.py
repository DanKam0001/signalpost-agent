#!/usr/bin/env python3
"""Web UI checks (R-1.49..R-1.56) through the documented serve command, driven by headless Chromium.

usage: .cache/vvenv/bin/python ui_checks.py --repo CLONE --tag TAG [--batch ENVELOPES.jsonl] [--port 8765]
Screenshots + results go to logs/<tag>/ui/.
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__))
EQUINOR, OTHER, UNKNOWN, DELETED, BADCD = "923609016", "982463718", "908660242", "921326904", "923609017"


def get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--batch"); ap.add_argument("--port", type=int, default=8765); a = ap.parse_args()
    out = os.path.join(HERE, "logs", a.tag, "ui"); os.makedirs(out, exist_ok=True)
    cmd = [os.path.join(a.repo, ".venv/bin/python"), "-m", "signalpost", "serve", "--host", "0.0.0.0", "--port", str(a.port)]
    if a.batch:
        # copy the batch and inject an HTML/JS payload into the first envelope's name and every string claim value
        envs_ = [json.loads(l) for l in open(a.batch, encoding="utf-8")]
        pay = '<img src="x" onerror="window.__xss=1"><b id="vfxinj">VFXINJ</b>'
        e0 = envs_[0]
        if isinstance(e0.get("legal_identity"), dict): e0["legal_identity"]["name"] = pay + (e0["legal_identity"].get("name") or "")
        for c_ in e0.get("claims") or []:
            if isinstance(c_.get("value"), str): c_["value"] = pay + c_["value"]
        if isinstance(e0.get("summary"), dict): e0["summary"]["text"] = pay + (e0["summary"].get("text") or "")
        for sn in (e0.get("summary") or {}).get("sentences") or []: sn["text"] = pay + sn.get("text", "")
        # UI aids (lead 00028): a carried fact in envelope 1, and injected text in envelope 0's section sources
        e1 = envs_[1]
        cc = next(c_ for c_ in e1.get("claims") or [] if c_.get("availability") == "available" and isinstance(c_.get("value"), str))
        cc["carried_forward"] = True
        cc["refresh_status"] = {"status": "not_refetched", "availability": "failed", "reason": "VFXCARRY source unreachable this run"}
        for sname, sec_ in (e0.get("sections") or {}).items():
            sec_.setdefault("sources", []).append({"source": "site.candidate", "url": "https://vfx.invalid/?q=<b>x</b>",
                "candidate_origin": "input_row", "outcome": "no_proof", "availability": "not_available",
                "detail": pay + "VFXSRC", "retrieved_at": "2026-09-29T00:00:00Z"})
            break
        a.carried = (e1["organisation_number"], cc.get("id"))
        xb = os.path.join(out, "batch-with-injection.jsonl")
        open(xb, "w", encoding="utf-8").write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in envs_))
        a.batch = xb
        cmd += ["--batch", a.batch]
    env = dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    srv = subprocess.Popen(cmd, cwd=a.repo, stdout=open(os.path.join(out, "serve.log"), "w"), stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{a.port}"
    R = {}
    def chk(rid, name, ok, detail=None):
        R.setdefault(rid, {"pass": True, "items": []})
        R[rid]["items"].append({"check": name, "pass": bool(ok), "detail": detail})
        if not ok: R[rid]["pass"] = False
    try:
        for _ in range(60):
            if get(base + "/", 2)[0] == 200: break
            time.sleep(0.5)
        # --- JSON API ---
        t = time.time(); st, body = get(f"{base}/api/company/{EQUINOR}", 120); dt = time.time() - t
        chk("R-1.49", "api 200", st == 200, st)
        chk("R-1.49", "profile within seconds (<=15s)", dt <= 15, round(dt, 1))
        try: env_json = json.loads(body)
        except Exception: env_json = {}
        chk("R-1.49", "api returns envelope", env_json.get("organisation_number") == EQUINOR, body[:200])
        for num, want in ((UNKNOWN, "not_available"), (DELETED, "not_available"), (BADCD, "failed")):
            st2, b2 = get(f"{base}/api/company/{num}", 120)
            try: s2 = json.loads(b2).get("status")
            except Exception: s2 = None
            chk("R-1.52", f"api {num} -> {want}", s2 == want or (want == "failed" and st2 in (400, 422)), (st2, s2))
        with sync_playwright() as p:
            b = p.chromium.launch()
            for w, h, label in ((1280, 900, "desktop"), (375, 812, "mobile")):
                pg = b.new_page(viewport={"width": w, "height": h})
                pg.goto(base + "/"); pg.wait_for_load_state("networkidle")
                pg.screenshot(path=os.path.join(out, f"{label}-start.png"), full_page=True)
                inp = pg.locator("input").first
                chk("R-1.49", f"{label}: start page has an input", inp.count() > 0)
                # validation error
                inp.fill("12345"); inp.press("Enter"); pg.wait_for_timeout(1500)
                txt = pg.inner_text("body")
                chk("R-1.52", f"{label}: validation message for 12345", re.search(r"9|digit|siffer|invalid|ugyldig|check", txt, re.I) is not None, txt[:200])
                pg.screenshot(path=os.path.join(out, f"{label}-invalid.png"), full_page=True)
                inp.fill(EQUINOR); inp.press("Enter")
                try:
                    pg.wait_for_selector("text=EQUINOR", timeout=60000)
                except Exception:
                    pass
                pg.wait_for_timeout(2000)
                txt = pg.inner_text("body")
                pg.screenshot(path=os.path.join(out, f"{label}-profile.png"), full_page=True)
                chk("R-1.49", f"{label}: profile rendered", "EQUINOR" in txt.upper())
                for s in ("identity", "accounts", "leader", "website", "hiring", "evidence", "change"):
                    chk("R-1.51", f"{label}: section '{s}' visible", s in txt.lower())
                chk("R-1.51", f"{label}: availability badges", len(re.findall(r"available|not.available|blocked|ambiguous|failed", txt, re.I)) >= 7)
                chk("R-1.51", f"{label}: unknown list", re.search(r"unknown|not found|ukjent", txt, re.I) is not None)
                links = pg.eval_on_selector_all("a[href^='http']", "els => els.map(e => [e.href, e.rel])")
                brreg = [l for l in links if "data.brreg.no" in l[0]]
                chk("R-1.50", f"{label}: links to exact Brreg API records", len(brreg) >= 5, len(brreg))
                chk("R-1.50", f"{label}: JSON pointer shown", re.search(r"/(navn|forretningsadresse|naeringskode1|organisasjonsform)", txt + pg.content()) is not None)
                chk("R-1.56", f"{label}: outbound links noopener noreferrer", all("noopener" in (l[1] or "") and "noreferrer" in (l[1] or "") for l in links), [l for l in links if "noopener" not in (l[1] or "")][:3])
                chk("R-1.50", f"{label}: dates shown", re.search(r"20\d\d-\d\d-\d\d", txt) is not None)
                if label == "mobile":
                    sw = pg.evaluate("document.documentElement.scrollWidth")
                    chk("R-1.55", "mobile 375: no horizontal scroll", sw <= 376, sw)
                    small = pg.evaluate("""() => [...document.querySelectorAll('a,button,input,select,[role=button]')]
                        .filter(e => {const r=e.getBoundingClientRect(); return r.width>0 && r.height>0 && getComputedStyle(e).display!='inline' && (r.height<40)})
                        .map(e => (e.tagName+' '+(e.innerText||e.value||'').slice(0,30)+' h='+Math.round(e.getBoundingClientRect().height)))""")
                    btns = pg.evaluate("""() => [...document.querySelectorAll('button,input,select')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0 && r.height<40}).length""")
                    chk("R-1.55", "mobile: buttons/inputs >= 40px tall", btns == 0, small[:8])
                # keyboard: Tab reaches the input and a link
                pg.keyboard.press("Tab"); foc = pg.evaluate("document.activeElement && document.activeElement.tagName")
                chk("R-1.55", f"{label}: keyboard focus moves", foc not in (None, "BODY"), foc)
                pg.close()
            # hover/focus highlights source (R-1.50): look for a change in style/attribute on focus
            pg = b.new_page(viewport={"width": 1280, "height": 900}); pg.goto(base + "/")
            pg.locator("input").first.fill(EQUINOR); pg.locator("input").first.press("Enter")
            try: pg.wait_for_selector("text=EQUINOR", timeout=60000)
            except Exception: pass
            pg.wait_for_timeout(1500)
            before = pg.content()
            facts = pg.locator("[data-claim-id]")
            chk("R-1.50", "facts carry data-claim-id", facts.count() >= 10, facts.count())
            chk("R-1.50", "source links carry data-evidence-id", pg.locator("[data-evidence-id]").count() >= 5, pg.locator("[data-evidence-id]").count())
            if facts.count():
                facts.nth(0).hover(); pg.wait_for_timeout(400)
                chk("R-1.50", "hover on a fact changes the page (source highlight)", pg.content() != before)
            else:
                chk("R-1.50", "hover on a fact changes the page (source highlight)", False, "no fact elements found")
            # states
            for num, word in ((UNKNOWN, r"not.available|no such|finnes ikke|not found"), (DELETED, r"deleted|slettet|not.available"),
                              (BADCD, r"check digit|invalid|ugyldig|kontrollsiffer")):
                pg.goto(base + "/"); pg.locator("input").first.fill(num); pg.locator("input").first.press("Enter")
                pg.wait_for_timeout(5000); t2 = pg.inner_text("body")
                pg.screenshot(path=os.path.join(out, f"state-{num}.png"), full_page=True)
                chk("R-1.52", f"state for {num}", re.search(word, t2, re.I) is not None, t2[:200])
            def render(path, wait_text, wait=60000):
                q = b.new_page(viewport={"width": 1280, "height": 900}); r = q.goto(base + path)
                try: q.wait_for_selector(f"text={wait_text}", timeout=wait)
                except Exception: pass
                q.wait_for_timeout(1500); t = q.inner_text("body")
                q.screenshot(path=os.path.join(out, "page-" + re.sub(r"[^a-z0-9]+", "_", path.lower())[:60] + ".png"), full_page=True)
                q.close(); return (r.status if r else 0), t
            st, prof = render(f"/company/{EQUINOR}", "EQUINOR")
            chk("R-1.49", "/company/{orgnr} renders profile", st == 200 and "EQUINOR" in prof.upper(), st)
            for q_ in (f"orgnr={EQUINOR}&orgnr={OTHER}", f"orgnrs={EQUINOR},{OTHER}"):
                st, cmp = render(f"/compare?{q_}", "TELENOR", 90000)
                chk("R-1.53", f"compare view ?{q_} renders both", st == 200 and "EQUINOR" in cmp.upper() and "TELENOR" in cmp.upper(), (st, cmp[:200]))
            if a.batch:
                st, bb = render("/batch", "available")
                chk("R-1.54", "batch browser lists the batch", st == 200 and len(re.findall(r"\d{9}|\d{3} \d{3} \d{3}", bb)) >= 10, (st, bb[:200]))
                q = b.new_page(viewport={"width": 1280, "height": 900}); q.goto(base + "/batch"); q.wait_for_timeout(2500)
                first = [json.loads(l) for l in open(a.batch)][0]
                nm = (first.get("legal_identity") or {}).get("name") or ""
                box = q.locator("input[type=search], input[type=text]").first
                if box.count() and nm:
                    box.fill(nm[:8]); q.wait_for_timeout(1000); t = q.inner_text("body")
                    chk("R-1.54", "batch search by name finds the company", nm[:8].upper() in t.upper(), nm)
                    box.fill(first["organisation_number"]); q.wait_for_timeout(1000); t = q.inner_text("body")
                    chk("R-1.54", "batch search by orgnr", first["organisation_number"] in t.replace(" ", ""), first["organisation_number"])
                else:
                    chk("R-1.54", "batch search box present", False, nm)
                chk("R-1.54", "batch state filter present", q.locator("select").count() > 0 or "filter" in q.inner_text("body").lower())
                q.close()
            # escaping (R-1.56): the served batch has an injected payload in the first company's name and claim values
            if a.batch:
                o0 = json.loads(open(a.batch).readline())["organisation_number"]
                for path in (f"/company/{o0}?source=batch", "/batch"):
                    q = b.new_page(viewport={"width": 1280, "height": 900}); q.goto(base + path); q.wait_for_timeout(4000)
                    x = q.evaluate("() => [window.__xss === 1, document.querySelectorAll('img[src=\"x\"], b#vfxinj').length]")
                    chk("R-1.56", f"payload rendered as text, not HTML ({path})", x == [False, 0], x)
                    chk("R-1.56", f"payload text visible escaped ({path})", "VFXINJ" in q.inner_text("body"), path)
                    q.close()
            # UI aids (lead 00028, R-1.50/R-1.51)
            if a.batch:
                o1, cid = a.carried
                for w, h, label in ((1280, 900, "desktop"), (375, 812, "mobile")):
                    q = b.new_page(viewport={"width": w, "height": h}); q.goto(f"{base}/company/{o1}?source=batch"); q.wait_for_timeout(4000)
                    fact = q.locator(f'[data-claim-id="{cid}"]').first
                    ftxt = fact.inner_text() if fact.count() else ""
                    chk("R-1.50", f"{label}: carried fact shows a text tag", re.search(r"not refreshed|not refetched", ftxt, re.I) is not None, ftxt[:200])
                    chk("R-1.50", f"{label}: carried fact shows refresh_status.reason", "VFXCARRY" in ftxt, ftxt[:200])
                    det = q.evaluate("""() => [...document.querySelectorAll('details')].filter(d => /source/i.test((d.querySelector('summary')||{}).innerText||'')).map(d => d.open)""")
                    chk("R-1.51", f"{label}: per-section 'Sources checked' details (>=7)", len(det) >= 7, det)
                    chk("R-1.51", f"{label}: sources lists collapsed by default", det and not any(det), det)
                    q.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)"); q.wait_for_timeout(500)
                    if label == "mobile":
                        sw = q.evaluate("document.documentElement.scrollWidth")
                        small = q.evaluate("""() => [...document.querySelectorAll('a,button,input,select,summary')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&(r.height<40||r.width<40)}).map(e=>e.tagName+' '+(e.innerText||'').slice(0,30)+' '+Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height))""")
                        chk("R-1.55", "mobile: sources lists open, no horizontal scroll", sw <= 376, sw)
                        chk("R-1.55", "mobile: sources lists open, all controls >= 40x40", not small, small[:8])
                    q.close()
                o0 = json.loads(open(a.batch).readline())["organisation_number"]
                q = b.new_page(viewport={"width": 1280, "height": 900}); q.goto(f"{base}/company/{o0}?source=batch"); q.wait_for_timeout(4000)
                q.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)"); q.wait_for_timeout(500)
                srcl = q.eval_on_selector_all("a[href*='vfx.invalid']", "els => els.map(e => [e.href, e.rel, e.innerText])")
                chk("R-1.51", "sources list renders candidate URL as a link", bool(srcl), srcl[:2])
                chk("R-1.56", "sources links rel=noopener noreferrer", all("noopener" in (l[1] or "") and "noreferrer" in (l[1] or "") for l in srcl), srcl[:2])
                x = q.evaluate("() => [window.__xss === 1, document.querySelectorAll('img[src=\"x\"], b#vfxinj').length]")
                chk("R-1.56", "sources detail rendered as text", x == [False, 0] and "VFXSRC" in q.inner_text("body"), x)
                q.close()
            b.close()
    finally:
        srv.terminate()
        try: srv.wait(10)
        except Exception: srv.kill()
    json.dump(R, open(os.path.join(out, "ui.json"), "w"), indent=1, default=str)
    for k, v in sorted(R.items()):
        print(k, "PASS" if v["pass"] else "FAIL", [i["check"] for i in v["items"] if not i["pass"]])


if __name__ == "__main__":
    main()
