// Overview: headline metrics, audit integrity, the most recent audit
// records, decision volume, detected identifiers, recent sessions and
// decisions. Loads with no input.
import { stackedBars } from "../charts.js";
import {
  OUTCOME_COLOR_VARS, ago, bindRowLinks, icon, chainOkCell, cssVar, emptyState, esc, legend, meter, num, outcomeChip,
  outcomeIcon, outcomeLabel, redactions, sessionHref, sessionLink, table, time, userLink,
} from "../ui.js";

const OUTCOMES = ["allow", "redact", "block", "deny", "log_only"];

function integrityPill(chain) {
  if (!chain.sessions_checked) return '<span class="status-pill status-pill--neutral">Audit integrity: no records</span>';
  if (!chain.broken.length) {
    return `<span class="status-pill status-pill--ok" title="All ${chain.sessions_checked} session chains re-hashed and signature-checked">${icon("verified_user", "icon--sm")}Audit integrity: verified</span>`;
  }
  return `<a class="status-pill status-pill--critical" href="${esc(sessionHref(chain.broken[0].session_id))}">${icon("gpp_bad", "icon--sm")}Audit integrity: ${chain.broken.length} of ${chain.sessions_checked} sessions failed</a>`;
}

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Overview</h1><p class="secondary">Governance activity across all sessions.</p></div>
      <div class="page-meta" id="integrity"></div>
    </div>
    <div class="stats" id="stats"></div>
    <section class="panel">
      <div class="panel__head"><h2>Recent audit records</h2><span class="panel__note">C = compliance check, A = authority check</span></div>
      <div class="chain" id="chain" aria-label="Most recent audit records, oldest first"></div>
      <div class="chain-caption"><span id="chain-from"></span><span>Latest</span></div>
      <div id="chain-legend" style="margin-top:12px"></div>
    </section>
    <div class="grid-2">
      <section class="panel">
        <div class="panel__head"><h2>Decision volume</h2><span class="panel__note" id="activity-note"></span></div>
        <div id="activity-legend"></div>
        <div class="chart-box" id="activity-box" style="margin-top:8px"><canvas aria-label="Decision volume by outcome"></canvas></div>
      </section>
      <section class="panel">
        <div class="panel__head"><h2>Detected identifiers</h2><span class="panel__note">across all compliance checks</span></div>
        <div id="identifiers"></div>
      </section>
    </div>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Recent sessions</h2><a href="#/sessions">View all sessions</a></div>
      <div id="recent-sessions"></div>
    </section>
    <section class="panel">
      <div class="panel__head"><h2>Recent decisions</h2><a href="#/ledger">Open audit ledger</a></div>
      <ul class="feed" id="feed"></ul>
    </section>`;
  bindRowLinks(el);

  let chart = null;
  let seen = null;

  async function refresh() {
    const [ov, feed] = await Promise.all([ctx.getJSON("/dashboard/overview"), ctx.getJSON("/dashboard/feed", { limit: 40 })]);
    const t = ov.totals;

    el.querySelector("#integrity").innerHTML = integrityPill(ov.chain) + (ov.chain.sessions_checked ? `<span>${num(ov.chain.sessions_checked)} sessions checked</span>` : "");

    el.querySelector("#stats").innerHTML = [
      ["Decisions", t.decisions],
      ["Sessions", t.sessions],
      ["Users", t.users],
      ["Redactions", t.redactions],
      ["Blocks", t.blocks],
      ["Denials", t.denials],
      ["Tokens processed", t.tokens_in + t.tokens_out],
    ]
      .map(([label, v]) => `<div class="stat"><span class="stat__value">${num(v)}</span><span class="stat__label">${esc(label)}</span></div>`)
      .join("");

    // Recent audit records, oldest left -> newest right
    const items = feed.items.slice().reverse();
    const firstDraw = seen === null;
    el.querySelector("#chain").innerHTML = items.length
      ? items
          .map((r, i) => {
            const tip = `${time(r.timestamp)}  ${outcomeLabel(r.outcome)}\nAgent: ${r.agent_id}\nCheck: ${r.decision_type}${r.ref_id ? ` (${r.ref_id})` : ""}${r.identifiers.length ? `\nDetected: ${r.identifiers.map((x) => x.type).join(", ")}` : ""}\nSession: ${r.session_id}\nHash: ${r.hash}`;
            const isNew = !firstDraw && !seen.has(r.receipt_id);
            return `${i ? '<span class="chain__link" aria-hidden="true"></span>' : ""}<a class="chain__block chain__block--${esc(r.outcome)}${isNew ? " chain__block--new" : ""}" href="${esc(sessionHref(r.session_id))}" title="${esc(tip)}" aria-label="${esc(outcomeLabel(r.outcome))} record">${icon(outcomeIcon(r.outcome), "icon--sm chain__glyph")}<span class="chain__glyph" aria-hidden="true">${r.decision_type === "authority" ? "A" : "C"}</span></a>`;
          })
          .join("")
      : emptyState("No audit records yet.", "Records appear here once requests pass through the proxy, an SDK integration, or the bench bridge.");
    const chainEl = el.querySelector("#chain");
    chainEl.scrollLeft = chainEl.scrollWidth;
    seen = new Set(items.map((i) => i.receipt_id));
    el.querySelector("#chain-from").textContent = items.length ? `${items.length} most recent records, from ${time(items[0].timestamp)}` : "";
    el.querySelector("#chain-legend").innerHTML = `<div class="legend">${OUTCOMES.filter((o) => o !== "log_only").map((o) => `<span class="legend__item">${outcomeChip(o)}</span>`).join("")}</div>`;

    // Decision volume
    const buckets = ov.activity.buckets;
    const labels = buckets.map((b) => time(b.start));
    const present = OUTCOMES.filter((o) => buckets.some((b) => b[o]));
    const series = present.map((o) => ({ label: outcomeLabel(o), data: buckets.map((b) => b[o]), color: cssVar(OUTCOME_COLOR_VARS[o]) }));
    el.querySelector("#activity-note").textContent = buckets.length ? `${ov.activity.bucket_seconds / 60}-minute intervals` : "";
    el.querySelector("#activity-legend").innerHTML = present.length > 1 ? legend(series.map((s) => ({ label: s.label, color: s.color }))) : "";
    const box = el.querySelector("#activity-box");
    if (!buckets.length) {
      box.innerHTML = emptyState("No decisions recorded yet.");
      chart = null;
    } else {
      if (!box.querySelector("canvas")) {
        box.innerHTML = '<canvas aria-label="Decision volume by outcome"></canvas>';
        chart = null;
      }
      if (chart) chart.update({ labels, series });
      else chart = stackedBars(box.querySelector("canvas"), { labels, series });
    }

    // Detected identifiers
    const ids = ov.identifiers;
    const max = Math.max(1, ...ids.map((i) => i.count));
    el.querySelector("#identifiers").innerHTML = ids.length
      ? `<div class="idbars">${ids
          .map((i) => `<div class="idbar"><span class="idbar__name">${esc(i.type)}</span><span class="idbar__track"><span class="idbar__fill" style="display:block;width:${(i.count / max) * 100}%"></span></span><span class="num">${num(i.count)}</span></div>`)
          .join("")}</div>`
      : emptyState("No identifiers detected yet.");

    el.querySelector("#recent-sessions").innerHTML = table(
      [
        { label: "Session and user", sort: "session_id", render: (s) => `${sessionLink(s.session_id)}<br>${s.user_id ? userLink(s.user_id) : '<span class="muted">No user</span>'}` },
        { label: "Flags", sort: "flags", cls: "num", render: (s) => num(s.flags) },
        { label: "Lowest score", sort: "min_score", render: (s) => meter(s.min_score) },
        { label: "Integrity", sort: (s) => (s.chain_ok ? 1 : 0), render: (s) => chainOkCell(s.chain_ok) },
        { label: "Last activity", sort: "last_seen", render: (s) => esc(ago(s.last_seen)) },
      ],
      ov.recent_sessions,
      { key: "overview-sessions", rowHref: (s) => sessionHref(s.session_id), empty: "No sessions yet." },
    );

    el.querySelector("#feed").innerHTML = feed.items.length
      ? feed.items
          .slice(0, 14)
          .map(
            (r) => `<li><span class="muted num">${esc(time(r.timestamp))}</span><span>${outcomeChip(r.outcome)}</span><span class="feed__who"><span><span class="mono">${esc(r.agent_id)}</span> <span class="muted">${esc(r.decision_type)}${r.ref_id ? ` (${esc(r.ref_id)})` : ""}</span></span>${redactions(r.identifiers)}<a class="mono muted id" href="${esc(sessionHref(r.session_id))}">${esc(r.session_id)}</a></span></li>`,
          )
          .join("")
      : `<li>${emptyState("No decisions recorded yet.")}</li>`;
  }

  await refresh();
  return { refresh, destroy: () => chart && chart.destroy() };
}
