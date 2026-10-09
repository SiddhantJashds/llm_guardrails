// Small HTML builders shared by every view. Each returns a string with all
// API data passed through escapeHtml.
import { escapeHtml as esc } from "./api.js";

export { esc };

export const DEFAULT_THRESHOLD = 60;

/** Material Icons ligature, e.g. icon("check"). Decorative by default. */
export const icon = (name, cls = "") => `<span class="icon${cls ? " " + cls : ""}" aria-hidden="true">${name}</span>`;

const OUTCOME = {
  allow: { icon: "check_circle", label: "Allowed" },
  redact: { icon: "visibility_off", label: "Redacted" },
  block: { icon: "block", label: "Blocked" },
  deny: { icon: "do_not_disturb_on", label: "Denied" },
  log_only: { icon: "info", label: "Logged" },
};

export function outcomeChip(outcome) {
  const o = OUTCOME[outcome] || { icon: "help", label: outcome };
  const cls = OUTCOME[outcome] ? outcome : "neutral";
  return `<span class="chip chip--${cls}">${icon(o.icon, "icon--xs")}${esc(o.label)}</span>`;
}

export const outcomeLabel = (o) => (OUTCOME[o] || { label: o }).label;
export const outcomeIcon = (o) => (OUTCOME[o] || { icon: "help" }).icon;

export function statusChip(status) {
  const name = { PASS: "check_circle", FAIL: "cancel", SKIP: "remove_circle_outline" }[status] || "help";
  const cls = ["PASS", "FAIL", "SKIP"].includes(status) ? status : "neutral";
  const label = { PASS: "Pass", FAIL: "Fail", SKIP: "Skipped" }[status] || status || "Unknown";
  return `<span class="chip chip--${cls}">${icon(name, "icon--xs")}${esc(label)}</span>`;
}

// One colour per kind of identifier, so a NAME is always blue, a PHONE always
// orange, etc. -- in placeholders, chips and legends alike. Fixed order of the
// validated categorical palette; rarer ID numbers share one colour.
const KIND = {
  full_name: ["NAME", 1], NAME: ["NAME", 1],
  phone_number: ["PHONE", 2], fax_number: ["PHONE", 2], PHONE: ["PHONE", 2], FAX: ["PHONE", 2],
  email_address: ["EMAIL", 3], web_url: ["EMAIL", 3], EMAIL: ["EMAIL", 3], URL: ["EMAIL", 3],
  geographic_subdivision: ["LOCATION", 4], residential_address: ["LOCATION", 4], LOCATION: ["LOCATION", 4], ADDRESS: ["LOCATION", 4],
  date_except_year: ["DATE", 5], DATE: ["DATE", 5],
  medical_record_number: ["ID", 7], health_plan_beneficiary_number: ["ID", 7], account_number: ["ID", 7],
  certificate_license_number: ["ID", 7], ssn_like: ["ID", 7], aadhaar_like: ["ID", 7], pan_like: ["ID", 7],
  MRN: ["ID", 7], PLAN_ID: ["ID", 7], ACCOUNT: ["ID", 7], LICENSE: ["ID", 7], SSN: ["ID", 7], AADHAAR: ["ID", 7], PAN: ["ID", 7],
  vehicle_identifier: ["DEVICE", 6], device_identifier: ["DEVICE", 6], VEHICLE: ["DEVICE", 6], DEVICE: ["DEVICE", 6],
};

export function kindOf(typeOrLabel) {
  const k = KIND[typeOrLabel] || KIND[String(typeOrLabel).replace(/^injection:.*/, "")];
  return k ? { kind: k[0], color: `var(--series-${k[1]})` } : { kind: "OTHER", color: "var(--neutral)" };
}

const entity = (label, typeKey, title) => {
  const k = kindOf(typeKey);
  return `<span class="ent" style="--c:${k.color}" title="${esc(title || label)}">${esc(label)}</span>`;
};

export function redactions(identifiers) {
  if (!identifiers || !identifiers.length) return "";
  return `<span class="redactions">${identifiers
    .map((i) => {
      const k = kindOf(i.type);
      return `<span class="ent" style="--c:${k.color}" title="${esc(i.type)}">${esc(i.type)}${i.count > 1 ? `<span class="ent__n">×${i.count}</span>` : ""}</span>`;
    })
    .join("")}</span>`;
}

/** Legend of identifier kinds present in a list of identifier types. */
export function kindLegend(types) {
  const seen = new Map();
  for (const t of types) {
    const k = kindOf(t);
    if (!seen.has(k.kind)) seen.set(k.kind, k.color);
  }
  return [...seen].map(([kind, color]) => `<span class="legend__item"><span class="legend__swatch" style="background:${color}"></span>${esc(kind.toLowerCase())}</span>`).join("");
}

/** Placeholders and masks inside already-escaped text -> coloured entities. */
export function decorateEntities(escaped) {
  return escaped
    .replace(/\[([A-Z][A-Z_]*?)_(\d+)\]/g, (m, label, n) => entity(`${label} ${n}`, label, `${m}: ${label.toLowerCase()} #${n}, the model never saw the real value`))
    .replace(/\[REDACTED_([A-Z_]+)\]/g, (m, label) => entity(`${label} redacted`, label, m))
    .replace(/\[HASH:([0-9a-f]+)\]/g, (m, h) => `<span class="ent ent--hash" title="${esc(m)}: one-way hash">#${esc(h)}</span>`)
    .replace(/\[REDACTED\]/g, () => `<span class="ent" style="--c:var(--neutral)">redacted</span>`);
}

export function meter(score, { threshold = DEFAULT_THRESHOLD } = {}) {
  if (score === null || score === undefined) return '<span class="muted">—</span>';
  const s = Math.max(0, Math.min(100, Number(score)));
  const level = s < threshold ? "low" : s < 80 ? "mid" : "ok";
  return `<span class="meter" title="score ${s.toFixed(1)} (default threshold ${threshold})">
    <span class="meter__track">
      <span class="meter__fill meter__fill--${level}" style="width:${s}%"></span>
      <span class="meter__mark" style="left:${threshold}%"></span>
    </span>
    <span class="meter__value">${s.toFixed(0)}</span>
  </span>`;
}

export function chainBadge(chain) {
  if (!chain || chain.checked === 0) return '<span class="status-pill status-pill--neutral">Audit integrity: no records</span>';
  if (chain.ok) {
    return `<span class="status-pill status-pill--ok" title="${chain.checked} records re-hashed and signature-checked">${icon("verified_user", "icon--sm")}Audit integrity: verified</span>`;
  }
  const kind = { link: "record is not linked to its predecessor", hash: "record was modified after signing", signature: "signature does not match the server key" }[chain.problem] || chain.problem;
  return `<span class="status-pill status-pill--critical" title="${esc(kind)}">${icon("gpp_bad", "icon--sm")}Audit integrity: failed at record ${esc(chain.broken_receipt_id)} (${esc(kind)})</span>`;
}

export function chainOkCell(ok) {
  if (ok === null || ok === undefined) return '<span class="muted">—</span>';
  return ok
    ? `<span class="status-pill status-pill--ok">${icon("verified_user", "icon--sm")}Verified</span>`
    : `<span class="status-pill status-pill--critical">${icon("gpp_bad", "icon--sm")}Failed</span>`;
}

/** Escape text, then show redaction markers ([REDACTED], [HASH:…]) as redaction bars. */
export function renderText(text) {
  return decorateEntities(esc(text));
}

export function short(value) {
  return String(value ?? "");
}

export const num = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString());

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const toDate = (iso) => (iso ? new Date(iso) : null);

export function time(iso) {
  const d = toDate(iso);
  return d ? timeFmt.format(d) : "—";
}

export function dateTime(iso) {
  const d = toDate(iso);
  return d ? dateTimeFmt.format(d) : "—";
}

export function dayTime(iso) {
  const d = toDate(iso);
  return d ? dayFmt.format(d) : "—";
}

export function ago(iso) {
  const d = toDate(iso);
  if (!d) return "—";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 90) return "1 min ago";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return dayTime(iso);
}

export function duration(fromIso, toIso) {
  const a = toDate(fromIso);
  const b = toDate(toIso);
  if (!a || !b) return "—";
  const s = Math.max(0, Math.round((b - a) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`;
}

export const sessionHref = (id) => `#/session/${encodeURIComponent(id)}`;
export const userHref = (id) => `#/user/${encodeURIComponent(id)}`;

export const sessionLink = (id) => `<a class="mono id" href="${esc(sessionHref(id))}">${esc(id)}</a>`;
export const userLink = (id) => `<a href="${esc(userHref(id))}">${esc(id)}</a>`;

/** columns: [{ label, cls?, render(row) -> html, sort?: field-name | (row) -> value }].
 * rowHref(row) makes rows clickable. Columns with `sort` get clickable headers;
 * the chosen order survives polling (kept per table key). */
const sortState = new Map();
const tables = new Map();
let autoKey = 0;

function compare(a, b) {
  const na = a === null || a === undefined || a === "";
  const nb = b === null || b === undefined || b === "";
  if (na || nb) return na === nb ? 0 : na ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function table(columns, rows, opts = {}) {
  const { rowHref, empty = "Nothing to show." } = opts;
  if (!rows.length) return emptyState(empty);
  const key = opts.key || `t${columns.map((c) => c.label).join("|")}`;
  tables.set(key, { columns, rows, opts: { ...opts, key } });
  const st = sortState.get(key);
  let ordered = rows;
  if (st && columns[st.col] && columns[st.col].sort) {
    const get = typeof columns[st.col].sort === "function" ? columns[st.col].sort : (r) => r[columns[st.col].sort];
    const dir = st.dir === "asc" ? 1 : -1;
    ordered = rows.slice().sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      const nullish = (v) => v === null || v === undefined || v === "";
      if (nullish(va) || nullish(vb)) return compare(va, vb); // empties last either way
      return compare(va, vb) * dir;
    });
  }
  const head = columns
    .map((c, i) => {
      if (!c.sort) return `<th class="${c.cls || ""}" scope="col">${esc(c.label)}</th>`;
      const active = st && st.col === i;
      const aria = active ? (st.dir === "asc" ? "ascending" : "descending") : "none";
      const arrow = active ? (st.dir === "asc" ? "arrow_upward" : "arrow_downward") : "unfold_more";
      return `<th class="${c.cls || ""}" scope="col" aria-sort="${aria}"><button class="th-sort${active ? " th-sort--on" : ""}" type="button" data-sort-table="${esc(key)}" data-sort-col="${i}">${esc(c.label)}${icon(arrow, "icon--xs")}</button></th>`;
    })
    .join("");
  const body = ordered
    .map((row) => {
      const href = rowHref ? rowHref(row) : null;
      const cells = columns.map((c) => `<td class="${c.cls || ""}">${c.render(row)}</td>`).join("");
      return `<tr${href ? ` data-href="${esc(href)}"` : ""}>${cells}</tr>`;
    })
    .join("");
  return `<div class="table-wrap" data-table="${esc(key)}"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-sort-table]");
  if (!btn) return;
  const key = btn.dataset.sortTable;
  const col = Number(btn.dataset.sortCol);
  const prev = sortState.get(key);
  // first click: largest/newest first (desc); then asc; then back to desc
  sortState.set(key, { col, dir: prev && prev.col === col && prev.dir === "desc" ? "asc" : "desc" });
  const t = tables.get(key);
  const wrap = btn.closest("[data-table]");
  if (t && wrap) {
    wrap.outerHTML = table(t.columns, t.rows, t.opts);
    document.querySelector(`[data-table="${CSS.escape(key)}"] button[data-sort-col="${col}"]`)?.focus();
  }
});

/** Make data-href rows navigate on click (links inside still work normally). */
export function bindRowLinks(root) {
  root.addEventListener("click", (e) => {
    if (e.target.closest("a, button, input, select, summary")) return;
    const row = e.target.closest("tr[data-href]");
    if (row) location.hash = row.dataset.href;
  });
}

export function emptyState(message, detail = "") {
  return `<div class="empty"><strong>${esc(message)}</strong>${detail}</div>`;
}

export function legend(items) {
  return `<div class="legend">${items
    .map((i) => `<span class="legend__item"><span class="legend__swatch${i.line ? " legend__swatch--line" : ""}" style="background:${i.color}"></span>${esc(i.label)}</span>`)
    .join("")}</div>`;
}

export function mixBar(outcomes) {
  const order = ["allow", "redact", "block", "deny", "log_only"];
  const total = order.reduce((n, o) => n + (outcomes[o] || 0), 0);
  if (!total) return '<span class="muted">No decisions yet</span>';
  const segs = order
    .filter((o) => outcomes[o])
    .map((o) => `<span class="mix--${o}" style="flex:${outcomes[o]}" title="${esc(outcomeLabel(o))}: ${outcomes[o]}"></span>`)
    .join("");
  const leg = order
    .filter((o) => outcomes[o])
    .map((o) => `<span class="legend__item">${outcomeChip(o)} <span class="num">${num(outcomes[o])}</span></span>`)
    .join("");
  return `<div class="mix" role="img" aria-label="outcome mix">${segs}</div><div class="legend" style="margin-top:8px">${leg}</div>`;
}

export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const OUTCOME_COLOR_VARS = { allow: "--ok", redact: "--warn", block: "--serious", deny: "--critical", log_only: "--neutral" };
export const SERIES_VARS = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6", "--series-7", "--series-8"];
