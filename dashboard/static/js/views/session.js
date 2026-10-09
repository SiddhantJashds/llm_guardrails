// Session detail: agents (delegation tree), the conversation as each party
// sent it after governance cleaned it, trust score history, detected
// identifiers, denied tool calls, and the full decision log. Select an agent
// to filter the conversation and decision log to that agent.
import { lines } from "../charts.js";
import { renderMarkdown } from "../markdown.js";
import {
  DEFAULT_THRESHOLD, SERIES_VARS, chainBadge, icon, cssVar, dateTime, duration, emptyState, esc, legend, meter, num,
  outcomeChip, redactions, renderText, table, time, userLink,
} from "../ui.js";

function turnLabel(t) {
  if (t.blocked) return "Blocked, not forwarded";
  if (t.kind === "tool_result") return "Tool result";
  if (t.kind === "output") return "Output";
  return t.parent_agent_id ? `Input from ${t.parent_agent_id}` : "User input";
}

export async function mount(el, params, ctx) {
  const id = params.id;
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title">
        <a href="#/sessions" class="crumb">Sessions</a>
        <h1>Session</h1>
        <span class="mono id">${esc(id)}</span>
      </div>
      <button class="btn" id="open-console" type="button">${icon("terminal", "icon--sm")}Open in test console</button>
    </div>
    <dl class="page-meta" id="meta"></dl>
    <div class="stats" id="stats"></div>
    <section class="panel">
      <div class="panel__head"><h2>Agents</h2><span class="panel__note">Select an agent to filter the conversation and decision log.</span></div>
      <div class="agents" id="agents"></div>
    </section>
    <div id="filter"></div>
    <section class="panel">
      <div class="panel__head"><h2>Conversation</h2><span class="panel__note">Text as forwarded after redaction. Raw identifiers are never stored.</span></div>
      <div class="turns" id="turns"></div>
    </section>
    <div class="grid-2">
      <section class="panel">
        <div class="panel__head"><h2>Trust score history</h2><span class="panel__note" id="trust-note"></span></div>
        <div id="trust-legend"></div>
        <div class="chart-box chart-box--tall" id="trust-box" style="margin-top:8px"><canvas aria-label="Trust score history per agent"></canvas></div>
      </section>
      <section class="panel">
        <div class="panel__head"><h2>Detected identifiers</h2></div>
        <div id="caught"></div>
        <h3 style="margin:20px 0 8px">Denied tool calls</h3>
        <div id="denied"></div>
      </section>
    </div>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Decision log</h2><span class="panel__note" id="timeline-note"></span></div>
      <div id="timeline"></div>
    </section>`;

  el.querySelector("#open-console").addEventListener("click", () => window.__chat && window.__chat.load(id));

  let chart = null;
  let selected = null; // agent_id filter
  let last = null;

  el.querySelector("#agents").addEventListener("click", (e) => {
    const row = e.target.closest("[data-agent]");
    if (!row) return;
    selected = selected === row.dataset.agent ? null : row.dataset.agent;
    render(last);
  });
  el.querySelector("#agents").addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-agent]")) {
      e.preventDefault();
      e.target.click();
    }
  });
  el.querySelector("#filter").addEventListener("click", (e) => {
    if (e.target.closest("#clear-filter")) {
      selected = null;
      render(last);
    }
  });

  function render(s) {
    if (!s) return;
    if (!s.decisions && !s.agents.length) {
      el.querySelector("#meta").innerHTML = "";
      el.querySelector("#stats").innerHTML = "";
      el.querySelector("#agents").innerHTML = emptyState("Session not found.", `No records exist for this session ID. <a href="#/sessions">View all sessions</a>.`);
      el.querySelector("#turns").innerHTML = "";
      return;
    }
    el.querySelector("#meta").innerHTML = `
      <div><dt>User</dt><dd>${s.user_ids.map(userLink).join(", ") || "—"}</dd></div>
      <div><dt>Started</dt><dd>${esc(dateTime(s.first_seen))}</dd></div>
      <div><dt>Duration</dt><dd>${esc(duration(s.first_seen, s.last_seen))}</dd></div>
      <div>${chainBadge(s.chain)}</div>`;
    el.querySelector("#stats").innerHTML = [
      ["Decisions", s.decisions], ["Redactions", s.redactions], ["Blocks", s.blocks], ["Denials", s.denials],
      ["Agents", s.agents.length], ["Tokens in", s.tokens_in], ["Tokens out", s.tokens_out],
    ].map(([l, v]) => `<div class="stat"><span class="stat__value">${num(v)}</span><span class="stat__label">${esc(l)}</span></div>`).join("");

    const colorOf = {};
    s.agents.forEach((a, i) => (colorOf[a.agent_id] = cssVar(SERIES_VARS[i % SERIES_VARS.length])));
    if (selected && !colorOf[selected]) selected = null;

    el.querySelector("#agents").innerHTML = s.agents
      .map((a) => {
        const signals = (a.history || []).map((h) => `<span class="signal">${esc(h.signal)} ${esc(Number(h.delta).toFixed(0))}</span>`).join("");
        const path = a.initial_score === null
          ? "No trust state (no penalties)"
          : `Initial score ${num(a.initial_score)}${a.initial_score < 100 ? " (capped by parent)" : ""}, current ${num(a.current_score)}${a.approximate ? " (approximate)" : ""}`;
        const sel = selected === a.agent_id;
        return `<div class="agent agent--selectable${sel ? " agent--selected" : ""}" style="--depth:${Number(a.depth) || 0}" data-agent="${esc(a.agent_id)}" role="button" tabindex="0" aria-pressed="${sel}">
          <div class="agent__name">${a.depth ? icon("subdirectory_arrow_right", "icon--sm agent__branch") : ""}<span class="agent__swatch" style="background:${colorOf[a.agent_id]}"></span>
            <span style="min-width:0"><span class="agent__id">${esc(a.agent_id)}</span><br><span class="agent__path">${esc(path)}</span></span></div>
          <div>${meter(a.current_score)}</div>
          <div class="agent__signals">${signals || '<span class="muted">No penalties</span>'}</div>
          <div class="agent__tokens">${num(a.decisions)} decisions<br>${num(a.tokens_in + a.tokens_out)} tokens</div>
        </div>`;
      })
      .join("");

    el.querySelector("#filter").innerHTML = selected
      ? `<div class="filter-note">Showing records for agent <span class="mono">${esc(selected)}</span><button class="btn btn--quiet" id="clear-filter" type="button" style="height:26px">Show all agents</button></div>`
      : "";

    // Conversation
    const turns = (s.conversation || []).filter((t) => !selected || t.agent_id === selected);
    el.querySelector("#turns").innerHTML = turns.length
      ? turns
          .map((t) => `<article class="turn turn--${t.blocked ? "blocked" : esc(t.kind)}">
            <div class="turn__meta">
              <span class="turn__who"><span class="agent__swatch" style="background:${colorOf[t.agent_id] || cssVar("--neutral")}"></span><span class="mono">${esc(t.agent_id)}</span></span>
              <span>${esc(turnLabel(t))}</span>
              <span class="muted num">${esc(time(t.timestamp))}</span>
              ${outcomeChip(t.outcome)}
              ${redactions(t.identifiers)}
            </div>
            ${t.blocked ? '<div class="turn__text muted">The content was blocked by the compliance policy and was not forwarded.</div>' : `<div class="turn__text">${t.kind === "input" ? renderText(t.text) : renderMarkdown(t.text)}</div>`}
          </article>`)
          .join("")
      : emptyState(
          selected ? "No messages recorded for this agent." : "No message text recorded for this session.",
          "Message text is captured for compliance checks made after message capture was enabled. Earlier records contain only the detected identifier types, shown in the decision log below.",
        );

    // Trust score history
    const withState = s.agents.filter((a) => a.trajectory.length && (!selected || a.agent_id === selected));
    const steps = Math.max(1, ...withState.map((a) => a.trajectory.length));
    const labels = Array.from({ length: steps }, (_, i) => (i === 0 ? "Initial" : `Signal ${i}`));
    const series = [
      ...withState.map((a) => ({ label: a.agent_id, data: a.trajectory.map((p) => p.score), color: colorOf[a.agent_id] })),
      { label: `Default threshold (${DEFAULT_THRESHOLD})`, data: labels.map(() => DEFAULT_THRESHOLD), color: cssVar("--ink-3"), dashed: true },
    ];
    el.querySelector("#trust-legend").innerHTML = legend(series.map((x) => ({ label: x.label, color: x.color, line: true })));
    el.querySelector("#trust-note").textContent = withState.length ? "One step per penalty signal" : "No penalties recorded";
    const box = el.querySelector("#trust-box");
    if (chart) chart.update({ labels, series });
    else chart = lines(box.querySelector("canvas"), { labels, series, yMin: 0, yMax: 100 });

    const agentsInView = s.agents.filter((a) => !selected || a.agent_id === selected);
    const ids = {};
    (s.timeline || []).filter((r) => !selected || r.agent_id === selected).forEach((r) => r.identifiers.forEach((i) => (ids[i.type] = (ids[i.type] || 0) + i.count)));
    const idList = Object.entries(ids).sort((a, b) => b[1] - a[1]).map(([type, count]) => ({ type, count }));
    el.querySelector("#caught").innerHTML = idList.length ? redactions(idList) : emptyState("No identifiers detected.");
    const denied = agentsInView.flatMap((a) => a.denied_calls.map((d) => ({ ...d, agent_id: a.agent_id })));
    el.querySelector("#denied").innerHTML = table(
      [
        { label: "Time", sort: "timestamp", render: (d) => esc(time(d.timestamp)) },
        { label: "Agent", sort: "agent_id", render: (d) => `<span class="mono">${esc(d.agent_id)}</span>` },
        { label: "Tool", sort: "tool", render: (d) => `<span class="mono">${esc(d.tool || "—")}</span>` },
        { label: "Reason", render: (d) => `<span class="cell-wrap">${esc(d.reason || "")}</span>` },
      ],
      denied,
      { key: "session-denied", empty: "No tool calls were denied." },
    );

    const rows = (s.timeline || []).filter((r) => !selected || r.agent_id === selected);
    el.querySelector("#timeline-note").textContent = `${num(rows.length)} records`;
    el.querySelector("#timeline").innerHTML = table(
      [
        { label: "Time", sort: "timestamp", render: (r) => `<span class="num">${esc(time(r.timestamp))}</span>` },
        { label: "Agent", sort: "agent_id", render: (r) => `<span class="mono">${esc(r.agent_id)}</span>${r.parent_agent_id ? `<br><span class="muted mono" style="font-size:12px">via ${esc(r.parent_agent_id)}</span>` : ""}` },
        { label: "Check", sort: "decision_type", render: (r) => `${esc(r.decision_type)}<br><span class="muted">${esc(r.ref_id || "")}</span>` },
        { label: "Outcome", sort: "outcome", render: (r) => outcomeChip(r.outcome) },
        { label: "Detail", render: (r) => `${r.identifiers.length ? redactions(r.identifiers) : `<span class="cell-wrap secondary">${esc(r.reason || "")}</span>`}${r.text ? `<div class="cell-text">${renderText(r.text)}</div>` : ""}` },
        { label: "Record hash", render: (r) => `<span class="mono muted hash">${esc(r.hash)}</span>` },
      ],
      rows,
      { key: "session-timeline", empty: "No decisions recorded." },
    );
  }

  async function refresh() {
    last = await ctx.getJSON(`/dashboard/session/${encodeURIComponent(id)}`);
    render(last);
  }

  await refresh();
  return { refresh, destroy: () => chart && chart.destroy() };
}
