// Bench runs: every GuardRailBench report, a scenario x run matrix to spot
// regressions, and per-run detail down to each hook's input and output.
// Rendered generically so new editions/scenarios on Day 2 show up as-is.
import { bindRowLinks, dateTime, icon, emptyState, esc, num, sessionHref, sessionLink, short, statusChip, table } from "../ui.js";

const runHref = (name) => `#/bench/${encodeURIComponent(name)}`;

function totalsChips(totals) {
  if (!totals) return '<span class="muted">—</span>';
  return Object.entries(totals)
    .map(([k, v]) => `<span class="legend__item">${statusChip(k)} <span class="num">${num(v)}</span></span>`)
    .join(" ");
}

export async function mount(el, params, ctx) {
  return params.name ? mountRun(el, params.name, ctx) : mountList(el, ctx);
}

async function mountList(el, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Evaluations</h1><p class="secondary" id="dir">GuardRailBench evaluation reports, newest first.</p></div>
    </div>
    <section class="panel panel--flush"><div class="panel__head"><h2>Runs</h2></div><div id="runs"></div></section>
    <section class="panel panel--flush"><div class="panel__head"><h2>Scenario results by run</h2><span class="panel__note">Newest run first. A change from pass to fail indicates a regression.</span></div><div id="matrix"></div></section>`;
  bindRowLinks(el);

  async function refresh() {
    const data = await ctx.getJSON("/dashboard/bench/runs");
    el.querySelector("#dir").innerHTML = `Reports are read from <code>${esc(data.dir)}</code>. Set <code>BENCH_REPORTS_DIR</code> on governance_api to use a different location.`;
    if (!data.available) {
      el.querySelector("#runs").innerHTML = emptyState("Reports folder not found.", `Nothing at <code>${esc(data.dir)}</code>. Run <code>python run_all.py --report reports/&lt;name&gt;.json</code> in GuardRailBench-Sample, or set <code>BENCH_REPORTS_DIR</code>.`);
      el.querySelector("#matrix").innerHTML = "";
      return;
    }
    el.querySelector("#runs").innerHTML = table(
      [
        { label: "Started", sort: "started_at", render: (r) => esc(dateTime(r.started_at)) },
        { label: "Report", sort: "name", render: (r) => `<a class="mono" href="${esc(runHref(r.name))}">${esc(r.name)}</a>` },
        { label: "Edition", sort: "edition", render: (r) => esc(r.edition || "—") },
        { label: "Scenarios", render: (r) => esc((r.scenarios_run || []).join(", ")) },
        { label: "Result", render: (r) => totalsChips(r.totals) },
        { label: "Duration", sort: "duration_s", cls: "num", render: (r) => (r.duration_s != null ? `${Number(r.duration_s).toFixed(1)}s` : "—") },
        { label: "Governance", render: (r) => `<span class="mono muted">${esc(r.governance_url || "—")}</span>` },
      ],
      data.items,
      { rowHref: (r) => runHref(r.name), empty: "No reports found. Reports appear here after a GuardRailBench run." },
    );

    // Scenario x run matrix (up to 12 newest runs)
    const runs = data.items.slice(0, 12);
    const scen = new Map();
    runs.forEach((r) => (r.scenario_status || []).forEach((s) => scen.set(String(s.number), s.name)));
    if (!scen.size) {
      el.querySelector("#matrix").innerHTML = emptyState("No scenarios recorded yet.");
      return;
    }
    const keys = [...scen.keys()].sort((a, b) => Number(a) - Number(b));
    const head = runs.map((r) => `<th class="matrix__run" scope="col" title="${esc(r.name)}"><a href="${esc(runHref(r.name))}">${esc(r.name.replace(/\.json$/, ""))}</a><br><span class="muted">${esc(dateTime(r.started_at))}</span></th>`).join("");
    const body = keys
      .map((k) => {
        const cells = runs
          .map((r) => {
            const s = (r.scenario_status || []).find((x) => String(x.number) === k);
            return `<td class="matrix__cell">${s ? statusChip(s.status) : '<span class="muted">—</span>'}</td>`;
          })
          .join("");
        return `<tr><td><strong>${esc(k)}</strong> ${esc(scen.get(k) || "")}</td>${cells}</tr>`;
      })
      .join("");
    el.querySelector("#matrix").innerHTML = `<div class="table-wrap"><table class="data matrix"><thead><tr><th scope="col">Scenario</th>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  await refresh();
  return { refresh, destroy() {} };
}

async function mountRun(el, name, ctx) {
  const run = await ctx.getJSON(`/dashboard/bench/runs/${encodeURIComponent(name)}`);
  const users = run.users ? Object.entries(run.users).map(([role, id]) => `${role}: ${id}`).join(", ") : "—";
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title">
        <a href="#/bench" class="crumb">Evaluations</a>
        <h1 class="mono" style="font-size:20px">${esc(name)}</h1>
        <div class="hero__sub" style="font-size:14px"><span>${esc(dateTime(run.started_at))}</span><span>${esc(run.edition || "")} edition</span><span>${run.duration_s != null ? esc(Number(run.duration_s).toFixed(1)) + "s" : ""}</span>${totalsChips(run.totals)}</div>
      </div>
    </div>
    <div class="grid-halves">
      <section class="panel">
        <div class="panel__head"><h2>Run</h2></div>
        <dl class="kv">
          <dt>Governance URL</dt><dd class="mono">${esc(run.governance_url || "—")}</dd>
          <dt>Users</dt><dd class="mono">${esc(users)}</dd>
          <dt>Scenarios run</dt><dd>${esc((run.scenarios_run || []).join(", ") || "—")}</dd>
        </dl>
      </section>
      <section class="panel panel--flush">
        <div class="panel__head"><h2>Per user</h2></div>
        <div id="per-user"></div>
      </section>
    </div>
    <section class="panel panel--flush">
      <div class="panel__head"><h2>Scenarios</h2><span class="panel__note">Open a hook log to see the input and output of each governance hook.</span></div>
      <div id="scenarios"></div>
    </section>`;

  const per = Object.entries(run.per_user_summary || {}).map(([user, s]) => ({ user, ...s }));
  const perKeys = [...new Set(per.flatMap((p) => Object.keys(p).filter((k) => k !== "user")))];
  el.querySelector("#per-user").innerHTML = table(
    [{ label: "User", sort: "user", render: (p) => `<span class="mono">${esc(p.user)}</span>` }, ...perKeys.map((k) => ({ label: k.replace(/_/g, " "), cls: "num", render: (p) => num(p[k]) }))],
    per,
    { empty: "No per-user summary in this report." },
  );

  el.querySelector("#scenarios").innerHTML = (run.scenarios || [])
    .map((s, idx) => {
      const checks = (s.checks || [])
        .map((c) => `<li>${statusChip(c.result)}<span>${esc(c.name)}${c.detail ? ` <span class="muted">${esc(c.detail)}</span>` : ""}</span></li>`)
        .join("");
      const sessions = (s.session_ids || []).map((id) => sessionLink(id)).join(", ");
      const requests = (s.requests || [])
        .map((r, i) => {
          const response = r.response && typeof r.response === "object" ? r.response.output ?? JSON.stringify(r.response, null, 2) : r.response;
          return `<details><summary>Request ${i + 1}: <span class="mono">${esc(r.endpoint || "")}</span> as <span class="mono">${esc(r.user_id || "")}</span></summary>
            <div class="textblock">${esc(r.request ?? "")}</div>
            <div class="textblock">${esc(response ?? "")}</div></details>`;
        })
        .join("");
      return `<article class="scenario">
        <div class="scenario__head">${statusChip(s.status)}<span class="scenario__title">${esc(s.number)}. ${esc(s.name)}</span><span class="muted">${esc(s.role || "")} as <span class="mono">${esc(s.user || "")}</span>${s.duration_s != null ? `, ${esc(Number(s.duration_s).toFixed(1))}s` : ""}</span></div>
        <p class="secondary">${esc(s.reason || "")}</p>
        ${checks ? `<ul class="checks">${checks}</ul>` : ""}
        ${sessions ? `<div>Sessions: ${sessions}</div>` : ""}
        ${requests}
        <details class="hooks-details" data-index="${idx}"><summary>Hook log (${num(s.hook_events)} events)</summary><div class="hooks-body"><div class="loading">Loading…</div></div></details>
      </article>`;
    })
    .join("") || emptyState("This report has no scenarios.");

  // Hook logs load on first open
  el.querySelectorAll(".hooks-details").forEach((d) =>
    d.addEventListener("toggle", async () => {
      if (!d.open || d.dataset.loaded) return;
      d.dataset.loaded = "1";
      const body = d.querySelector(".hooks-body");
      try {
        const data = await ctx.getJSON(`/dashboard/bench/runs/${encodeURIComponent(name)}/scenarios/${d.dataset.index}/hooks`);
        body.innerHTML = renderHooks(data.items);
      } catch (err) {
        body.innerHTML = emptyState("Couldn't load the hook log.", esc(err.message));
        delete d.dataset.loaded;
      }
    }),
  );

  return { refresh: async () => {}, destroy() {} };
}

function renderHooks(items) {
  if (!items.length) return emptyState("No hook events recorded.");
  const t0 = Number(items[0].timestamp) || 0;
  const rows = items
    .map((h) => {
      const input = h.input ?? "";
      const output = h.output ?? "";
      const changed = String(input) !== String(output);
      const io = changed
        ? `<div class="hook-io"><span><span class="muted">in </span>${esc(input)}</span><span><span class="muted">out </span>${esc(output)}</span></div>`
        : `<div class="hook-io"><span>${esc(input)}</span></div>`;
      const tool = h.tool_name && h.tool_name !== "None" ? `<br><span class="mono muted">${esc(h.tool_name)}</span>` : "";
      return `<tr class="${changed ? "changed" : ""}">
        <td class="num muted">+${esc(((Number(h.timestamp) || t0) - t0).toFixed(2))}s</td>
        <td class="mono">${esc(h.hook)}${tool}</td>
        <td class="mono">${esc(h.agent_id || "")}${h.parent_agent_id && h.parent_agent_id !== "None" ? `<br><span class="muted">via ${esc(h.parent_agent_id)}</span>` : ""}</td>
        <td>${changed ? '<span class="chip chip--redact">${icon("edit_note", "icon--xs")}Modified</span>' : '<span class="muted">Unchanged</span>'}</td>
        <td>${io}</td>
      </tr>`;
    })
    .join("");
  return `<div class="table-wrap"><table class="data hooks"><thead><tr><th>t</th><th>Hook</th><th>Agent</th><th>Governance</th><th>Input and output</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
