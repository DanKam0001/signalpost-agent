// Signalpost UI. All source-derived text is inserted with textContent; links are limited to
// http(s) and open with rel="noopener noreferrer".
"use strict";

const SECTIONS = [
  ["legal_identity_and_brand", "Legal identity and public brand"],
  ["annual_accounts", "Latest annual accounts and history"],
  ["leadership_and_workplaces", "Leadership and registered workplaces"],
  ["website_and_profiles", "Official website and company-owned profiles"],
  ["hiring_and_activity", "Hiring and dated public activity"],
  ["evidence_and_availability", "Claim-level evidence and availability"],
  ["refresh_and_changes", "Refresh and changes since the previous run"],
];
const STATE_TEXT = {
  available: "Available", not_available: "Not available", blocked: "Blocked",
  not_applicable: "Not applicable", ambiguous: "Ambiguous", failed: "Failed",
};
const EXAMPLES = [["923609016", "Equinor"], ["810034882", "Sandnes Elektriske"],
  ["974760673", "Brønnøysundregistrene"], ["921326904", "a deleted company"]];
const MONEY_FIELDS = new Set(["operating_revenue", "operating_expenses", "operating_result",
  "net_financial_items", "profit_before_tax", "net_result", "total_assets", "fixed_assets",
  "current_assets", "total_equity", "total_debt", "total_equity_and_debt"]);
const COLLAPSE_AFTER = 8;

let localBatch = null;  // envelopes opened from a file in the browser

// ---------- DOM helpers ----------
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
function safeUrl(url) {
  try {
    const u = new URL(url, location.origin);
    return (u.protocol === "http:" || u.protocol === "https:") ? u.href : null;
  } catch { return null; }
}
function extLink(url, text, attrs) {
  const href = safeUrl(url);
  if (!href) return h("span", {}, text || url || "");
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", ...(attrs || {}) },
    text || url);
}
function badge(state) {
  return h("span", { class: `badge ${state}`, "data-state": state }, STATE_TEXT[state] || state);
}
function fmtNumber(v) {
  if (typeof v === "number") return v.toLocaleString("nb-NO").replace(/ /g, " ");
  return String(v);
}
function setTitle(text) { document.title = text ? `${text} — Signalpost` : "Signalpost"; }
function main() { return document.getElementById("main"); }
function render(...nodes) { const m = main(); m.replaceChildren(...nodes); }

// ---------- organisation numbers ----------
function normalise(raw) {
  let t = String(raw || "").trim().toUpperCase();
  if (t.startsWith("NO")) t = t.slice(2);
  if (t.endsWith("MVA")) t = t.slice(0, -3);
  return t.replace(/[\s.\-]/g, "");
}
function validationError(n) {
  if (!n) return "Type a 9-digit Norwegian organisation number.";
  if (!/^\d+$/.test(n)) return "An organisation number contains only digits (spaces are fine).";
  if (n.length !== 9) return `An organisation number has exactly 9 digits — you typed ${n.length}.`;
  const w = [3, 2, 7, 6, 5, 4, 3, 2];
  let sum = 0;
  for (let i = 0; i < 8; i++) sum += Number(n[i]) * w[i];
  let check = 11 - (sum % 11);
  if (check === 11) check = 0;
  if (check === 10 || check !== Number(n[8])) {
    return "That number fails the organisation-number check digit. Check for a typo.";
  }
  return null;
}

// ---------- routing ----------
function navigate(url, replace) {
  if (replace) history.replaceState({}, "", url); else history.pushState({}, "", url);
  route();
}
document.addEventListener("click", (ev) => {
  const a = ev.target.closest("a[data-link]");
  if (a && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey && a.origin === location.origin) {
    ev.preventDefault();
    navigate(a.getAttribute("href"));
  }
});
window.addEventListener("popstate", route);
window.addEventListener("DOMContentLoaded", route);

function route() {
  const path = location.pathname;
  const params = new URLSearchParams(location.search);
  for (const a of document.querySelectorAll("[data-nav]")) a.removeAttribute("aria-current");
  const mark = (name) => document.querySelector(`[data-nav="${name}"]`)
    ?.setAttribute("aria-current", "page");
  if (path.startsWith("/company/")) {
    mark("lookup");
    return profileView(decodeURIComponent(path.slice(9)), params.get("source"));
  }
  if (path === "/compare") {
    mark("compare");
    let list = params.getAll("orgnr");
    if (!list.length && params.get("orgnrs")) list = params.get("orgnrs").split(",");
    return compareView(list.map(normalise).filter(Boolean));
  }
  if (path === "/batch") { mark("batch"); return batchView(); }
  mark("lookup");
  return startView();
}

// ---------- lookup ----------
function lookupForm(value, errorText) {
  const input = h("input", { type: "text", id: "orgnr", name: "orgnr", inputmode: "numeric",
    autocomplete: "off", placeholder: "e.g. 923 609 016", value: value || "",
    "aria-describedby": "orgnr-help orgnr-error", "aria-invalid": errorText ? "true" : null });
  const err = h("div", { id: "orgnr-error", class: "field-error", role: "alert" }, errorText || "");
  const form = h("form", { class: "lookup", role: "search", onsubmit: (ev) => {
    ev.preventDefault();
    const n = normalise(input.value);
    const problem = validationError(n);
    if (problem) {
      err.textContent = problem;
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    navigate(`/company/${n}`);
  } },
  h("label", { for: "orgnr" }, "Organisation number", input),
  h("button", { type: "submit" }, "Look up"));
  return h("div", { class: "card" }, form,
    h("div", { id: "orgnr-help", class: "muted small" },
      "Norwegian organisation number (9 digits). Profiles are built live from Brønnøysundregistrene " +
      "and the company's own verified website."), err);
}

function startView() {
  setTitle("");
  const examples = h("div", { class: "examples" },
    EXAMPLES.map(([n, label]) => h("a", { class: "button secondary", href: `/company/${n}`,
      "data-link": true }, `${label} · ${n}`)));
  render(lookupForm(""),
    h("section", { class: "card", "aria-labelledby": "start-h" },
      h("h2", { id: "start-h" }, "Look up any Norwegian company"),
      h("p", {}, "Type an organisation number to get a profile where every line links to the " +
        "exact registry field or web page it came from, with its date. Missing, blocked or " +
        "uncertain information is shown as such — never as zero."),
      examples));
  document.getElementById("orgnr").focus();
}

async function fetchEnvelope(n, source) {
  if (source === "local" && localBatch && localBatch.has(n)) return localBatch.get(n);
  const q = source === "batch" ? "?source=batch" : "";
  const resp = await fetch(`/api/company/${encodeURIComponent(n)}${q}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const e = new Error(body.message || `Server answered ${resp.status}`);
    e.kind = body.error || "server_error";
    throw e;
  }
  return body;
}

async function profileView(raw, source) {
  const n = normalise(raw);
  const problem = validationError(n);
  if (problem) {
    setTitle("Invalid number");
    render(lookupForm(raw, problem),
      h("div", { class: "error-box", role: "alert", "data-state": "validation_error" },
        h("strong", {}, "That is not a valid organisation number. "), problem));
    return;
  }
  setTitle(n);
  render(lookupForm(n), h("div", { class: "card loading", role: "status", "aria-live": "polite",
    "data-state": "loading" }, h("div", { class: "spinner", "aria-hidden": "true" }),
  h("div", {}, h("strong", {}, `Researching ${n}…`),
    h("div", { class: "muted small" }, "Reading Brønnøysundregistrene (entity, roles, " +
      "workplaces, accounts) and checking the company's own website."))));
  try {
    const env = await fetchEnvelope(n, source);
    if (location.pathname !== `/company/${raw}` && normalise(location.pathname.slice(9)) !== n) {
      return;  // the user navigated away meanwhile
    }
    renderProfile(env, source);
  } catch (e) {
    render(lookupForm(n), h("div", { class: "error-box", role: "alert", "data-state": "failed" },
      h("strong", {}, "The lookup did not complete. "),
      e.kind === "invalid_organisation_number" ? e.message
        : `${e.message}. Try again in a moment; if it keeps failing the registry may be down.`));
  }
}

// ---------- claim formatting ----------
function claimText(c) {
  const v = c.value;
  if (c.availability !== "available") return c.reason || STATE_TEXT[c.availability];
  if (v === null || v === undefined) return "—";
  if (MONEY_FIELDS.has(c.field)) return `${fmtNumber(v)} ${c.currency || ""}`.trim();
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return fmtNumber(v);
  if (typeof v === "string") return v;
  switch (c.field) {
    case "organisation_form": case "sector_code": case "industry_code":
      return `${v.code} — ${v.description || ""}`;
    case "business_address": case "postal_address":
      return [...(v.lines || []), [v.postcode, v.city].filter(Boolean).join(" "), v.country]
        .filter(Boolean).join(", ");
    case "role": {
      let s = `${v.name}${v.organisation_number ? ` (org. ${v.organisation_number})` : ""}`;
      if (v.elected_by) s += ` · ${v.elected_by}`;
      if (v.resigned || v.deregistered) s += " · no longer active";
      return s;
    }
    case "workplace": {
      const parts = [v.name, v.municipality, `org. ${v.organisation_number}`];
      if (v.employees !== undefined) parts.push(`${v.employees} employees`);
      if (v.closed_on) parts.push(`closed ${v.closed_on}`);
      return parts.filter(Boolean).join(" · ");
    }
    case "accounts_period":
      return `${v.from} – ${v.to} · ${v.account_type} · ${v.currency}`;
    case "audited":
      return v.audit_opted_out ? "No — audit opted out" : (v.audited ? "Yes" : "No");
    case "share_capital":
      return `${fmtNumber(Number(v.amount))} ${v.currency || ""}`;
    case "historical_name": return `${v.name} (${v.from || "?"} – ${v.to || "?"})`;
    case "parent_unit": return `${v.organisation_number} — ${v.relationship}`;
    case "deleted": return `Deleted${v.deleted_on ? ` on ${v.deleted_on}` : ""}`;
    case "social_profile": return `${v.platform}: ${v.url}`;
    case "job_posting":
      return `${v.title}${v.date_posted ? ` · posted ${v.date_posted}` : ""}${v.location ? ` · ${v.location}` : ""}`;
    case "news_item": return `${v.title} · ${v.date}`;
    default:
      if (Array.isArray(v)) return v.join(", ");
      return JSON.stringify(v);
  }
}
function claimLink(c) {
  const v = c.value || {};
  if (["official_website", "careers_page"].includes(c.field) && typeof c.value === "string") return c.value;
  if (["social_profile", "job_posting", "news_item"].includes(c.field)) return v.url;
  return null;
}
function claimDates(c, ev) {
  const bits = [];
  if (c.reporting_period) bits.push(`period ${c.reporting_period.from} – ${c.reporting_period.to}`);
  else if (ev && ev.record_date) bits.push(`dated ${ev.record_date}`);
  if (ev && ev.retrieved_at) bits.push(`retrieved ${ev.retrieved_at.slice(0, 16).replace("T", " ")} UTC`);
  if (c.carried_forward) bits.push(`last seen ${String(c.last_observed_at || "").slice(0, 10)}`);
  return bits.join(" · ");
}

// ---------- evidence inspector ----------
function inspector() {
  return h("aside", { class: "card inspector", id: "inspector", "aria-live": "polite",
    "aria-label": "Source of the selected fact" },
  h("h2", {}, "Source"),
  h("p", { class: "muted small" }, "Hover or focus any fact to see exactly where it came from."));
}
function showEvidence(fact, claim, evs) {
  const box = document.getElementById("inspector");
  if (!box) return;
  document.querySelectorAll(".fact.hl, .sentence.hl").forEach((el) => el.classList.remove("hl"));
  fact.classList.add("hl");
  box.classList.add("active");
  const rows = [];
  for (const ev of evs) {
    const pointer = ev.json_pointer !== undefined ? ev.json_pointer : null;
    rows.push(
      h("dt", {}, "Fact"), h("dd", {}, `${claim.label}: ${claimText(claim)}`),
      h("dt", {}, "Source"), h("dd", {}, extLink(ev.source_url, ev.source_url,
        { "data-evidence-id": ev.id })),
      ev.human_url ? h("dt", {}, "Human view") : null,
      ev.human_url ? h("dd", {}, extLink(ev.human_url, "Open in Brønnøysund")) : null,
      h("dt", {}, pointer !== null ? "JSON pointer" : "Selector"),
      h("dd", {}, h("code", {}, pointer !== null ? (pointer || "(whole document)")
        : (ev.css_selector || "(page)"))),
      ev.claim_span ? h("dt", {}, "Text on page") : null,
      ev.claim_span ? h("dd", {}, `“${ev.claim_span}”`) : null,
      h("dt", {}, "Record date"), h("dd", {}, ev.record_date || "none given by the source"),
      h("dt", {}, "Retrieved"), h("dd", {}, ev.retrieved_at),
      h("dt", {}, "Class"), h("dd", {}, ev.source_class),
      h("dt", {}, "SHA-256"), h("dd", {}, h("a", { href: `/snapshot/${ev.content_sha256}`,
        target: "_blank", rel: "noopener noreferrer" }, h("code", {}, ev.content_sha256.slice(0, 16) + "…"))),
      h("dt", {}, "Method"), h("dd", {}, ev.extraction_method));
  }
  if (!evs.length) rows.push(h("dt", {}, "Why"), h("dd", {}, claim.reason || "no evidence"));
  box.replaceChildren(h("h2", {}, "Source"), h("dl", {}, rows));
}

function factRow(c, evidence) {
  const evs = (c.evidence_ids || []).map((id) => evidence[id]).filter(Boolean);
  const first = evs[0];
  const link = claimLink(c);
  const value = link ? extLink(link, claimText(c)) : claimText(c);
  const src = first ? extLink(first.source_url, first.source_class === "company_owned"
    ? "Web page" : "Registry record", { class: "src", "data-evidence-id": first.id,
    title: first.json_pointer !== undefined ? `JSON pointer ${first.json_pointer || "/"}`
      : (first.css_selector || "") }) : h("span", { class: "src muted" }, "—");
  const row = h("li", { class: `fact${c.availability !== "available" ? " unavailable" : ""}${c.carried_forward ? " carried" : ""}`,
    tabindex: "0", "data-claim-id": c.id, "data-field": c.field },
  h("span", { class: "label" }, c.label),
  h("span", { class: "value" }, value,
    c.carried_forward ? staleTag(c) : null,
    h("span", { class: "dates" }, claimDates(c, first)),
    first && first.json_pointer !== undefined ? h("code", {}, first.json_pointer || "/") : null,
    first && first.css_selector ? h("code", {}, first.css_selector) : null),
  src);
  const show = () => showEvidence(row, c, evs);
  row.addEventListener("mouseenter", show);
  row.addEventListener("focus", show);
  return row;
}

// A carried-forward fact is the last supported value from an earlier run; say so in words.
function staleTag(c) {
  const reason = c.refresh_status && c.refresh_status.reason;
  return h("span", { class: "stale-tag", "data-stale": "true" },
    "Not refreshed this run" + (reason ? `: ${reason}` : ""));
}

// Every source (or website candidate) the section tried this run, with its outcome.
function sourcesList(sources) {
  const items = (sources || []).map((s) => {
    const url = s.url || s.robots_url;
    const bits = [s.source, s.candidate_origin && `candidate: ${s.candidate_origin}`,
      s.outcome && `outcome: ${s.outcome}`, s.availability && `state: ${s.availability}`,
      s.http_status ? `HTTP ${s.http_status}` : null, s.detail, s.reason,
      s.claim_key && `claim ${s.claim_key}`,
      s.retrieved_at && `at ${String(s.retrieved_at).slice(0, 19).replace("T", " ")}`]
      .filter(Boolean);
    return h("li", { class: "source-item" },
      url ? extLink(url, url, { class: "source-url" }) : null,
      h("span", { class: "source-meta" }, bits.join(" · ")));
  });
  return h("details", { class: "sources" },
    h("summary", {}, `Sources checked (${items.length})`),
    items.length ? h("ul", { class: "source-list" }, items)
      : h("p", { class: "muted small" }, "No sources recorded"));
}

function factList(claims, evidence) {
  if (!claims.length) return h("p", { class: "muted small" }, "No facts in this section.");
  const head = claims.slice(0, COLLAPSE_AFTER).map((c) => factRow(c, evidence));
  const list = h("ul", { class: "facts" }, head);
  if (claims.length <= COLLAPSE_AFTER) return list;
  const rest = h("ul", { class: "facts" }, claims.slice(COLLAPSE_AFTER).map((c) => factRow(c, evidence)));
  return h("div", {}, list, h("details", { class: "more" },
    h("summary", {}, `Show ${claims.length - COLLAPSE_AFTER} more`), rest));
}

// ---------- profile ----------
function statusMessage(env) {
  const reason = env.status_reason || "";
  const msg = {
    not_available: ["No such company found", "Brønnøysundregistrene has no active entity with this number. "],
    blocked: ["The registry refused the request", "Brønnøysundregistrene did not answer our request (rate limit or refusal). Try again later. "],
    failed: ["The research failed for this company", "Something broke while researching this number. "],
  }[env.status];
  if (!msg) return null;
  return h("div", { class: env.status === "not_available" ? "notice" : "error-box",
    role: "alert", "data-state": env.status },
  h("strong", {}, msg[0] + ". "), msg[1], h("span", { class: "muted" }, reason));
}

function renderProfile(env, source) {
  const evidence = Object.fromEntries((env.evidence || []).map((e) => [e.id, e]));
  const claims = env.claims || [];
  const byId = Object.fromEntries(claims.map((c) => [c.id, c]));
  const legal = env.legal_identity || {};
  setTitle(legal.name || env.organisation_number);

  const head = h("section", { class: "card", "aria-labelledby": "company-name" },
    h("div", { class: "profile-head" },
      h("div", {},
        h("h1", { id: "company-name" }, legal.name || `Organisation ${env.organisation_number}`),
        h("div", { class: "meta" },
          h("span", {}, `Org. no. ${env.organisation_number}`),
          legal.organisation_form ? h("span", {}, legal.organisation_form_description || legal.organisation_form) : null,
          legal.municipality ? h("span", {}, legal.municipality) : null,
          legal.human_url ? extLink(legal.human_url, "Brønnøysund record") : null)),
      h("div", {}, badge(env.status),
        h("div", { class: "muted small" }, `Researched ${String(env.run?.completed_at || "").slice(0, 16).replace("T", " ")} UTC`),
        source === "batch" || source === "local" ? h("div", { class: "muted small" }, "From the loaded batch file")
          : h("button", { class: "link", type: "button", onclick: () => refresh(env.organisation_number) }, "Refresh now"))));

  const citations = [];
  const sentences = (env.summary?.sentences || []).map((s) => {
    const span = h("span", { class: "sentence" }, s.text + " ");
    for (const cid of s.claim_ids.slice(0, 6)) {
      const n = citations.push(cid);
      span.append(h("button", { class: "cite", type: "button", "aria-label": `Show source ${n}`,
        onclick: () => focusClaim(cid) }, `[${n}]`));
    }
    span.append(" ");
    return span;
  });
  const summary = h("section", { class: "card summary", "aria-labelledby": "summary-h" },
    h("h2", { id: "summary-h" }, "Summary"),
    statusMessage(env),
    sentences.length ? h("p", {}, sentences) : h("p", {}, env.summary?.text || ""),
    h("p", { class: "muted small" }, "Generated deterministically from the published facts below; " +
      "each [n] opens the fact and its source."));

  const changes = env.changes || [];
  const lists = h("div", { class: "lists" },
    h("section", { class: "card", "aria-labelledby": "changes-h" },
      h("h2", { id: "changes-h" }, "What changed"),
      h("p", { class: "small" }, env.summary?.changes_text || ""),
      changes.length ? h("ul", {}, changes.map((c) => h("li", { "data-change-type": c.type },
        h("strong", {}, c.type.replace(/_/g, " ")), ` — ${c.label}: `,
        c.previous ? `${summarise(c.previous.value)} → ` : "",
        c.current ? summarise(c.current.value) : "(removed)",
        h("span", { class: "muted small" }, ` · ${c.materiality}`)))) : null),
    h("section", { class: "card", "aria-labelledby": "unknown-h" },
      h("h2", { id: "unknown-h" }, "What is unknown"),
      (env.summary?.unknowns || []).length
        ? h("ul", {}, env.summary.unknowns.map((u) => h("li", {}, badge(u.availability), " ", u.text)))
        : h("p", { class: "small" }, "Every section has published, sourced facts.")));

  const sectionCards = SECTIONS.map(([key, title]) => {
    const s = env.sections?.[key] || { availability: "failed", reason: "missing", claim_ids: [] };
    let ids = s.claim_ids || [];
    if (key === "refresh_and_changes") ids = [];
    const sectionClaims = ids.map((id) => byId[id]).filter(Boolean);
    return h("section", { class: "card", id: `section-${key}`, "data-section": key,
      "data-availability": s.availability, "aria-labelledby": `h-${key}` },
    h("div", { class: "section-head" }, h("h2", { id: `h-${key}` }, title), badge(s.availability)),
    h("p", { class: "reason" }, s.reason || ""),
    key === "refresh_and_changes" ? refreshBlock(env) : factList(sectionClaims, evidence),
    sourcesList(s.sources));
  });

  render(lookupForm(env.organisation_number), head,
    h("div", { class: "layout" }, h("div", {}, summary, lists, sectionCards), inspector()));
}

function refreshBlock(env) {
  const r = env.refresh || {};
  return h("ul", { class: "facts" },
    h("li", { class: "fact", tabindex: "0" }, h("span", { class: "label" }, "First observed"),
      h("span", { class: "value" }, r.first_observed_at || "—"), h("span", {})),
    h("li", { class: "fact", tabindex: "0" }, h("span", { class: "label" }, "Previous observation"),
      h("span", { class: "value" }, r.previous_observed_at || "none (first observation)"), h("span", {})),
    h("li", { class: "fact", tabindex: "0" }, h("span", { class: "label" }, "Changes detected"),
      h("span", { class: "value" }, String(r.change_count ?? 0)), h("span", {})));
}

function summarise(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "object") return String(v);
  if (v.name) return v.name;
  if (v.lines) return [...v.lines, v.postcode, v.city].filter(Boolean).join(" ");
  if (v.from && v.to) return `${v.from} – ${v.to}`;
  if (v.title) return v.title;
  if (Array.isArray(v)) return v.join(", ");
  return JSON.stringify(v);
}

function focusClaim(cid) {
  const row = document.querySelector(`[data-claim-id="${CSS.escape(cid)}"]`);
  if (!row) return;
  const details = row.closest("details");
  if (details) details.open = true;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.focus({ preventScroll: true });
}

async function refresh(n) {
  render(lookupForm(n), h("div", { class: "card loading", role: "status", "data-state": "loading" },
    h("div", { class: "spinner", "aria-hidden": "true" }), h("strong", {}, `Refreshing ${n}…`)));
  try {
    const resp = await fetch(`/api/company/${n}?refresh=1`);
    renderProfile(await resp.json());
  } catch (e) {
    render(lookupForm(n), h("div", { class: "error-box", role: "alert" }, `Refresh failed: ${e.message}`));
  }
}

// ---------- compare ----------
const COMPARE_ROWS = [
  ["Status", (e) => ({ text: STATE_TEXT[e.status] || e.status })],
  ["Legal name", "legal_name"], ["Organisation form", "organisation_form"],
  ["Municipality", "municipality"], ["Industry", "industry_code"], ["Founded", "founding_date"],
  ["Registered employees", "registered_employees"], ["Accounts period", "accounts_period"],
  ["Operating revenue", "operating_revenue"], ["Operating result", "operating_result"],
  ["Net result", "net_result"], ["Total assets", "total_assets"], ["Total equity", "total_equity"],
  ["CEO", (e) => roleCell(e, "DAGL")], ["Board chair", (e) => roleCell(e, "LEDE")],
  ["Workplaces", "workplace_count"], ["Official website", "official_website"],
  ["Job postings", (e) => countCell(e, "job_posting")],
  ["Dated news items", (e) => countCell(e, "news_item")],
];
function firstClaim(env, field) {
  return (env.claims || []).find((c) => c.field === field && c.availability === "available"
    && !(field === "industry_code" && !c.claim_key.endsWith(":1")));
}
function roleCell(env, code) {
  const c = (env.claims || []).find((x) => x.field === "role" && x.value.role_code === code
    && !x.value.resigned && !x.value.deregistered);
  return c ? { claim: c } : null;
}
function countCell(env, field) {
  const list = (env.claims || []).filter((c) => c.field === field && c.availability === "available");
  const sec = field === "job_posting" || field === "news_item" ? env.sections?.hiring_and_activity : null;
  return list.length ? { text: String(list.length), claim: list[0] }
    : { text: sec ? `0 (${STATE_TEXT[sec.availability]})` : "0" };
}
function compareCell(env, spec, head) {
  const td = h("td", { "data-head": head });
  if (!env) return td;
  const cell = typeof spec === "function" ? spec(env) : (firstClaim(env, spec) ? { claim: firstClaim(env, spec) } : null);
  if (!cell) { td.append(h("span", { class: "muted" }, "not available")); return td; }
  const claim = cell.claim;
  if (claim && !cell.text) {
    const evidence = Object.fromEntries((env.evidence || []).map((e) => [e.id, e]));
    const ev = evidence[claim.evidence_ids[0]];
    td.setAttribute("data-claim-id", claim.id);
    td.append(claimText(claim), " ");
    if (ev) td.append(extLink(ev.source_url, "source", { "data-evidence-id": ev.id,
      title: ev.json_pointer !== undefined ? `JSON pointer ${ev.json_pointer || "/"}` : (ev.css_selector || "") }));
  } else {
    td.append(cell.text);
    if (claim) td.setAttribute("data-claim-id", claim.id);
  }
  return td;
}

async function compareView(list) {
  setTitle("Compare");
  const inputs = [0, 1, 2, 3].map((i) => h("input", { type: "text", name: "orgnr", inputmode: "numeric",
    "aria-label": `Organisation number ${i + 1}`, placeholder: i < 2 ? "9 digits" : "optional",
    value: list[i] || "" }));
  const err = h("div", { class: "field-error", role: "alert" });
  const form = h("form", { class: "card lookup", onsubmit: (ev) => {
    ev.preventDefault();
    const nums = inputs.map((x) => normalise(x.value)).filter(Boolean);
    const bad = nums.map((n) => [n, validationError(n)]).find(([, p]) => p);
    if (nums.length < 2) { err.textContent = "Enter at least two organisation numbers."; return; }
    if (bad) { err.textContent = `${bad[0]}: ${bad[1]}`; return; }
    navigate(`/compare?${nums.map((n) => `orgnr=${n}`).join("&")}`);
  } }, inputs.map((x) => h("label", {}, x)), h("button", { type: "submit" }, "Compare"));
  const intro = h("p", { class: "muted small" }, "Compare two to four companies side by side; every cell links to its source.");
  if (list.length < 2) { render(h("h1", {}, "Compare companies"), intro, form, err); return; }
  const bad = list.map((n) => [n, validationError(n)]).find(([, p]) => p);
  if (bad) {
    render(h("h1", {}, "Compare companies"), form,
      h("div", { class: "error-box", role: "alert", "data-state": "validation_error" }, `${bad[0]}: ${bad[1]}`));
    return;
  }
  render(h("h1", {}, "Compare companies"), form, h("div", { class: "card loading", role: "status",
    "data-state": "loading" }, h("div", { class: "spinner" }), h("strong", {}, "Researching…")));
  const results = await Promise.all(list.slice(0, 4).map((n) => fetchEnvelope(n).catch((e) => ({
    organisation_number: n, status: "failed", status_reason: e.message, claims: [], evidence: [], sections: {} }))));
  const heads = results.map((e) => (e.legal_identity?.name || e.organisation_number));
  const table = h("table", { class: "grid stack", id: "compare-table" },
    h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Field"),
      results.map((e, i) => h("th", { scope: "col" }, h("a", { href: `/company/${e.organisation_number}`,
        "data-link": true }, heads[i]), h("div", { class: "muted small" }, e.organisation_number))))),
    h("tbody", {}, COMPARE_ROWS.map(([label, spec]) => h("tr", { "data-row": label },
      h("th", { scope: "row" }, label), results.map((e, i) => compareCell(e, spec, heads[i]))))));
  render(h("h1", {}, "Compare companies"), form, err, h("div", { class: "card" }, table));
}

// ---------- batch browser ----------
async function batchView() {
  setTitle("Batch");
  let data = null;
  try { data = await (await fetch("/api/batch")).json(); } catch { data = null; }
  let rows = data?.companies || [];
  let fromFile = false;
  if (localBatch) { rows = [...localBatch.values()].map(indexRow); fromFile = true; }
  const q = h("input", { type: "search", id: "batch-q", placeholder: "Name or organisation number" });
  const state = h("select", { id: "batch-state" }, h("option", { value: "" }, "All states"),
    Object.entries(STATE_TEXT).map(([k, v]) => h("option", { value: k }, v)));
  const file = h("input", { type: "file", id: "batch-file", accept: ".jsonl,.json,application/json" });
  const count = h("p", { class: "muted small", "aria-live": "polite" });
  const tbody = h("tbody");
  const draw = () => {
    const needle = q.value.trim().toLowerCase().replace(/\s/g, "");
    const wanted = state.value;
    const shown = rows.filter((r) => (!wanted || r.status === wanted) &&
      (!needle || r.organisation_number.includes(needle) ||
        String(r.name || "").toLowerCase().replace(/\s/g, "").includes(needle)));
    count.textContent = `${shown.length} of ${rows.length} companies`;
    tbody.replaceChildren(...shown.slice(0, 500).map((r) => h("tr", { "data-orgnr": r.organisation_number },
      h("td", { "data-head": "Company" }, h("a", { class: "row-link", "data-link": true,
        href: `/company/${r.organisation_number}?source=${fromFile ? "local" : "batch"}` },
      r.name || r.organisation_number)),
      h("td", { "data-head": "Org. no." }, r.organisation_number),
      h("td", { "data-head": "Municipality" }, r.municipality || "—"),
      h("td", { "data-head": "State" }, badge(r.status)),
      h("td", { "data-head": "Website" }, badge(r.sections?.website_and_profiles || "failed")),
      h("td", { "data-head": "Facts" }, String(r.claims)))));
  };
  q.addEventListener("input", draw);
  state.addEventListener("change", draw);
  file.addEventListener("change", async () => {
    const f = file.files[0];
    if (!f) return;
    try {
      const text = await f.text();
      const envs = text.trim().startsWith("[") ? JSON.parse(text)
        : text.split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
      localBatch = new Map(envs.map((e) => [e.organisation_number, e]));
      rows = envs.map(indexRow);
      fromFile = true;
      source.textContent = `Opened ${f.name}`;
      draw();
    } catch (e) {
      source.textContent = `Could not read ${f.name}: ${e.message}`;
    }
  });
  const source = h("p", { class: "small" }, data?.source ? `Loaded on the server: ${data.source}`
    : "No batch loaded on the server. Open an envelopes JSONL file from your computer.");
  render(h("h1", {}, "Batch browser"), source,
    h("div", { class: "card filters" },
      h("label", { for: "batch-q" }, "Find", q),
      h("label", { for: "batch-state" }, "State", state),
      h("label", { for: "batch-file" }, "Open envelopes file", file)),
    count,
    h("div", { class: "card" }, h("table", { class: "grid stack", id: "batch-table" },
      h("thead", {}, h("tr", {}, ["Company", "Org. no.", "Municipality", "State", "Website", "Facts"]
        .map((t) => h("th", { scope: "col" }, t)))), tbody)));
  draw();
}
function indexRow(env) {
  const legal = env.legal_identity || {};
  return { organisation_number: env.organisation_number, name: legal.name, status: env.status,
    municipality: legal.municipality,
    sections: Object.fromEntries(Object.entries(env.sections || {}).map(([k, v]) => [k, v.availability])),
    claims: (env.claims || []).filter((c) => c.availability === "available").length };
}
