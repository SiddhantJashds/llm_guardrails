// Live bench: follow a GuardRailBench run (python run_all.py) as it happens.
// Reads the bench bridge's live feed every 1.5 s. Events are grouped into
// runs by the user-id suffix the bench assigns per run (alice-ce70,
// bob-ce70 -> run ce70); once the run's report is written, it is linked.
import { renderMarkdown } from "../markdown.js";
import {
  bindRowLinks, emptyState, esc, icon, num, outcomeChip, renderText, sessionHref, statusChip, table, time,
} from "../ui.js";

const FAST_MS = 1500;
const RUNNING_WINDOW_MS = 10000;
const HOOKS = {
  on_prompt_received: { icon: "input", label: "Prompt received" },
  on_completion_received: { icon: "output", label: "Completion" },
  on_tool_call: { icon: "build", label: "Tool call" },
  on_tool_result: { icon: "dataset", label: "Tool result" },
  on_session_end: { icon: "flag", label: "Session end" },
};

function runOf(userId) {
  if (userId === "contract-check") return "contract-check";
  const m = /^[A-Za-z]+-([0-9a-f]{3,})$/.exec(userId || "");
  return m ? m[1] : "other";
}

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Live bench</h1><p class="secondary">Follow a GuardRailBench run in real time. Start one with <code>python run_all.py</code> in the GuardRailBench-Sample folder.</p></div>
      <div class="page-meta" id="live-status"></div>
    </div>
    <div id="runs" class="live-runs"></div>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Hook events</h2><span class="panel__note" id="filter-note">Newest first. Text is shown after governance cleaned it.</span></div>
      <div id="stream"></div>
    </section>`;
  bindRowLinks(el);

  const cfg = await ctx.getJSON("/dashboard/config");
  const bridge = (cfg.bridge_url || "http://localhost:8080").replace(/\/+$/, "");
  const events = [];
  let lastSeq = 0;
  let bridgeStartedAt = null;
  let connected = null;
  let reports = [];
  let selectedRun = null;
  let timer = null;
  let stopped = false;

  el.querySelector("#runs").addEventListener("click", (e) => {
    const card = e.target.closest("[data-run]");
    if (!card || e.target.closest("a")) return;
    selectedRun = selectedRun === card.dataset.run ? null : card.dataset.run;
    render();
  });

  function render() {
    const now = Date.now();
    const lastTs = events.length ? Date.parse(events[events.length - 1].timestamp) : 0;
    const running = connected && lastTs && now - lastTs < RUNNING_WINDOW_MS;
    el.querySelector("#live-status").innerHTML = connected === false
      ? `<span class="status-pill status-pill--critical">${icon("link_off", "icon--sm")}Bench bridge not reachable</span><span class="mono">${esc(bridge)}</span>`
      : running
        ? `<span class="status-pill status-pill--ok live-pulse">${icon("sensors", "icon--sm")}Run in progress</span><span>${num(events.length)} events</span>`
        : `<span class="status-pill status-pill--neutral">${icon("sensors_off", "icon--sm")}Idle, waiting for a run</span><span>${events.length ? `Last event ${esc(time(events[events.length - 1].timestamp))}` : "No events since the bridge started"}</span>`;

    // Runs
    const byRun = new Map();
    for (const e of events) {
      const r = runOf(e.user_id);
      if (!byRun.has(r)) byRun.set(r, { id: r, events: [], users: new Set(), sessions: new Set(), outcomes: {}, hooks: {}, first: e.timestamp, last: e.timestamp });
      const g = byRun.get(r);
      g.events.push(e);
      g.users.add(e.user_id);
      g.sessions.add(e.session_id);
      g.outcomes[e.outcome] = (g.outcomes[e.outcome] || 0) + 1;
      g.hooks[e.hook] = (g.hooks[e.hook] || 0) + 1;
      g.last = e.timestamp;
    }
    const runs = [...byRun.values()].sort((a, b) => Date.parse(b.last) - Date.parse(a.last));
    el.querySelector("#runs").innerHTML = runs.length
      ? runs
          .map((g) => {
            const isRunning = now - Date.parse(g.last) < RUNNING_WINDOW_MS;
            const report = reports.find((rep) => Object.values(rep.users || {}).some((u) => g.users.has(u)));
            const title = g.id === "contract-check" ? "Contract check" : g.id === "other" ? "Other traffic" : `Run ${g.id}`;
            const outcomes = ["allow", "redact", "block", "deny"].filter((o) => g.outcomes[o]).map((o) => `<span class="legend__item">${outcomeChip(o)}<span class="num">${num(g.outcomes[o])}</span></span>`).join("");
            const hooks = Object.entries(g.hooks).map(([h, n]) => `<span class="signal">${esc((HOOKS[h] || { label: h }).label)} ${num(n)}</span>`).join("");
            const scen = report ? (report.scenario_status || []).map((s) => `<span class="legend__item">${statusChip(s.status)}<span>${esc(s.number)}. ${esc(s.name)}</span></span>`).join("") : "";
            return `<article class="panel live-run${selectedRun === g.id ? " live-run--selected" : ""}" data-run="${esc(g.id)}" role="button" tabindex="0" aria-pressed="${selectedRun === g.id}">
              <div class="panel__head"><h2>${esc(title)}</h2>${isRunning ? `<span class="status-pill status-pill--ok live-pulse">${icon("sensors", "icon--sm")}Running</span>` : report ? `<a class="status-pill status-pill--neutral" href="#/bench/${encodeURIComponent(report.name)}">${icon("description", "icon--sm")}Report ${esc(report.name)}</a>` : `<span class="status-pill status-pill--neutral">Finished</span>`}</div>
              <dl class="page-meta"><div><dt>Users</dt><dd class="mono">${esc([...g.users].join(", "))}</dd></div><div><dt>Sessions</dt><dd>${num(g.sessions.size)}</dd></div><div><dt>Events</dt><dd>${num(g.events.length)}</dd></div><div><dt>Started</dt><dd>${esc(time(g.first))}</dd></div></dl>
              <div class="legend" style="margin-top:10px">${outcomes || '<span class="muted">No decisions yet</span>'}</div>
              <div class="agent__signals" style="margin-top:8px">${hooks}</div>
              ${scen ? `<div class="legend" style="margin-top:10px">${scen}</div>` : ""}
            </article>`;
          })
          .join("")
      : `<div class="panel">${emptyState(connected === false ? "The bench bridge is not running." : "Waiting for bench traffic.", connected === false ? `Start the stack with <code>WITH_BRIDGE=1</code> in .env, then <code>./run.sh</code>.` : `Run <code>python run_all.py</code> in GuardRailBench-Sample. Events appear here as each hook is called.`)}</div>`;

    // Stream
    const shown = events.filter((e) => !selectedRun || runOf(e.user_id) === selectedRun).slice(-300).reverse();
    el.querySelector("#filter-note").innerHTML = selectedRun
      ? `Showing ${esc(selectedRun === "contract-check" ? "the contract check" : `run ${selectedRun}`)}. Select the run again to show all.`
      : "Newest first. Text is shown after governance cleaned it.";
    el.querySelector("#stream").innerHTML = table(
      [
        { label: "Time", sort: "timestamp", render: (e) => `<span class="num">${esc(time(e.timestamp))}</span>` },
        { label: "Hook", sort: "hook", render: (e) => `<span class="hook-name">${icon((HOOKS[e.hook] || { icon: "bolt" }).icon, "icon--sm")}${esc((HOOKS[e.hook] || { label: e.hook }).label)}</span>${e.tool ? `<br><span class="mono muted">${esc(e.tool)}</span>` : ""}` },
        { label: "Agent", sort: "agent_id", render: (e) => `<span class="mono">${esc(e.agent_id)}</span>${e.parent_agent_id ? `<br><span class="muted mono" style="font-size:12px">via ${esc(e.parent_agent_id)}</span>` : ""}` },
        { label: "Outcome", sort: "outcome", render: (e) => (e.outcome === "end" ? '<span class="chip chip--neutral">Ended</span>' : outcomeChip(e.outcome)) },
        { label: "Content", render: (e) => (e.text ? `<div class="cell-text live-text">${e.hook === "on_tool_call" || e.hook === "on_session_end" ? renderText(e.text) : renderMarkdown(e.text)}</div>` : '<span class="muted">—</span>') },
        { label: "Session", sort: "session_id", render: (e) => `<a class="mono id" href="${esc(sessionHref(e.session_id))}">${esc(e.session_id)}</a><br><span class="muted">${esc(e.user_id)}</span>` },
      ],
      shown,
      { key: "live-stream", empty: selectedRun ? "No events for this run." : "No hook events yet." },
    );
  }

  async function poll() {
    if (stopped) return;
    try {
      const resp = await fetch(`${bridge}/live/events?after=${lastSeq}&limit=2000`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (bridgeStartedAt && data.bridge_started_at !== bridgeStartedAt) {
        events.length = 0; // bridge restarted: its sequence starts over
        lastSeq = 0;
      }
      bridgeStartedAt = data.bridge_started_at;
      for (const e of data.events) events.push(e);
      if (events.length > 5000) events.splice(0, events.length - 5000);
      lastSeq = Math.max(lastSeq, data.last_seq);
      connected = true;
    } catch (_) {
      connected = false;
    }
    render();
    if (!stopped) timer = setTimeout(poll, FAST_MS);
  }

  async function refreshReports() {
    try {
      reports = (await ctx.getJSON("/dashboard/bench/runs")).items || [];
    } catch (_) {
      reports = [];
    }
  }

  await refreshReports();
  await poll();
  return {
    // The app-level 5 s tick refreshes the report list (a run's report lands when it finishes)
    refresh: async () => {
      await refreshReports();
      render();
    },
    destroy() {
      stopped = true;
      clearTimeout(timer);
    },
  };
}
