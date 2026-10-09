// User detail: live profile, token usage over time, outcome mix, their
// sessions, and decision history.
import { lines } from "../charts.js";
import {
  ago, bindRowLinks, chainOkCell, cssVar, dateTime, emptyState, esc, legend, meter, mixBar, num, outcomeChip,
  redactions, sessionHref, sessionLink, table, time,
} from "../ui.js";

export async function mount(el, params, ctx) {
  const id = params.id;
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title">
        <a href="#/users" class="crumb">Users</a>
        <h1 style="overflow-wrap:anywhere">${esc(id)}</h1>
      </div>
    </div>
    <div class="stats" id="stats"></div>
    <div class="grid-2">
      <section class="panel">
        <div class="panel__head"><h2>Token usage</h2><span class="panel__note">Cumulative, per request</span></div>
        <div id="tokens-legend"></div>
        <div class="chart-box" style="margin-top:8px" id="tokens-box"><canvas id="tokens-chart" aria-label="Cumulative tokens"></canvas></div>
      </section>
      <section class="panel">
        <div class="panel__head"><h2>Outcomes</h2><span class="panel__note" id="rating-note"></span></div>
        <div id="mix"></div>
      </section>
    </div>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Sessions</h2></div>
      <div id="sessions"></div>
    </section>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Decision history</h2><label class="check"><input type="checkbox" id="hide-allows" checked /> Show interventions only</label></div>
      <div id="decisions"></div>
    </section>`;
  bindRowLinks(el);

  let chart = null;
  let last = null;
  const hideAllows = el.querySelector("#hide-allows");
  hideAllows.addEventListener("change", () => last && renderDecisions(last));

  function renderDecisions(u) {
    const rows = u.recent_decisions.slice().reverse().filter((d) => !hideAllows.checked || d.outcome !== "allow");
    el.querySelector("#decisions").innerHTML = table(
      [
        { label: "Time", sort: "timestamp", render: (d) => `<span class="num">${esc(dateTime(d.timestamp))}</span>` },
        { label: "Outcome", sort: "outcome", render: (d) => outcomeChip(d.outcome) },
        { label: "Check", sort: "decision_type", render: (d) => esc(d.decision_type) },
        { label: "Agent", sort: "agent_id", render: (d) => `<span class="mono">${esc(d.agent_id)}</span>` },
        { label: "Detail", render: (d) => (d.identifiers.length ? redactions(d.identifiers) : `<span class="cell-wrap secondary">${esc(d.reason || "")}</span>`) },
        { label: "Session", sort: "session_id", render: (d) => sessionLink(d.session_id) },
      ],
      rows,
      { empty: hideAllows.checked ? "No interventions in the 50 most recent decisions." : "No decisions yet." },
    );
  }

  async function refresh() {
    const u = await ctx.getJSON(`/dashboard/user/${encodeURIComponent(id)}`);
    last = u;
    const p = u.profile;
    el.querySelector("#stats").innerHTML = [
      ["Tokens in", num(p.total_tokens_in)],
      ["Tokens out", num(p.total_tokens_out)],
      ["Composite rating", p.total_checks ? Number(p.composite_rating).toFixed(1) : "—"],
      ["Effective use (tokens per task)", p.effective_use_score ? Number(p.effective_use_score).toFixed(0) : "—"],
      ["Violations", num(p.violation_count)],
      ["Denials", num(p.denied_count)],
      ["Checks", num(p.total_checks)],
    ].map(([l, v]) => `<div class="stat"><span class="stat__value">${esc(v)}</span><span class="stat__label">${esc(l)}</span></div>`).join("");

    el.querySelector("#rating-note").innerHTML = p.total_checks ? `composite rating ${meter(p.composite_rating)}` : "";
    el.querySelector("#mix").innerHTML = mixBar(u.outcomes);

    // Cumulative tokens
    const box = el.querySelector("#tokens-box");
    if (!u.token_series.length) {
      box.innerHTML = emptyState("No token usage recorded.", "Token usage is recorded for requests made through the proxy or the bench bridge.");
      el.querySelector("#tokens-legend").innerHTML = "";
      chart = null;
    } else {
      if (!box.querySelector("canvas")) box.innerHTML = '<canvas id="tokens-chart" aria-label="Cumulative tokens"></canvas>';
      let tin = 0;
      let tout = 0;
      const labels = u.token_series.map((t) => time(t.timestamp));
      const series = [
        { label: "Tokens in", data: u.token_series.map((t) => (tin += t.tokens_in)), color: cssVar("--series-1") },
        { label: "Tokens out", data: u.token_series.map((t) => (tout += t.tokens_out)), color: cssVar("--series-2") },
      ];
      el.querySelector("#tokens-legend").innerHTML = legend(series.map((s) => ({ label: s.label, color: s.color, line: true })));
      if (chart) chart.update({ labels, series });
      else chart = lines(box.querySelector("canvas"), { labels, series });
    }

    el.querySelector("#sessions").innerHTML = table(
      [
        { label: "Session", sort: "session_id", render: (s) => sessionLink(s.session_id) },
        { label: "Agents", sort: (s) => s.agents.length, cls: "num", render: (s) => num(s.agents.length) },
        { label: "Decisions", sort: "decisions", cls: "num", render: (s) => num(s.decisions) },
        { label: "Flags", sort: "flags", cls: "num", render: (s) => num(s.flags) },
        { label: "Lowest score", sort: "min_score", render: (s) => meter(s.min_score) },
        { label: "Tokens", sort: (s) => s.tokens_in + s.tokens_out, cls: "num", render: (s) => num(s.tokens_in + s.tokens_out) },
        { label: "Integrity", sort: (s) => (s.chain_ok ? 1 : 0), render: (s) => chainOkCell(s.chain_ok) },
        { label: "Last activity", sort: "last_seen", render: (s) => esc(ago(s.last_seen)) },
      ],
      u.sessions,
      { rowHref: (s) => sessionHref(s.session_id), empty: "No sessions recorded for this user." },
    );
    renderDecisions(u);
  }

  await refresh();
  return { refresh, destroy: () => chart && chart.destroy() };
}
