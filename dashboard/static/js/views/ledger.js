// Ledger: the raw audit log as a filterable, paged table.
import { dateTime, esc, num, outcomeChip, redactions, renderText, sessionLink, table, userLink } from "../ui.js";

const PAGE = 100;

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Audit ledger</h1><p class="secondary">Signed, hash-chained audit records, newest first. Any modification to a record invalidates its session chain.</p></div>
    </div>
    <div class="toolbar">
      <select class="select" id="type" aria-label="Check type"><option value="">All check types</option><option value="compliance">compliance</option><option value="authority">authority</option></select>
      <select class="select" id="verdict" aria-label="Verdict"><option value="">All verdicts</option><option>allow</option><option>redact</option><option>hash</option><option>block</option><option>log_only</option><option>deny</option></select>
      <input class="input" id="user" type="search" placeholder="user_id" aria-label="Filter by user" />
      <input class="input" id="session" type="search" placeholder="session_id" aria-label="Filter by session" />
      <input class="input" id="agent" type="search" placeholder="agent_id" aria-label="Filter by agent" />
      <input class="input input--grow" id="q" type="search" placeholder="Search reason or tool" aria-label="Search reasons" />
    </div>
    <section class="panel panel--flush">
      <div id="list"></div>
      <div class="pager"><span id="range"></span><span class="toolbar"><button class="btn" id="prev" type="button">Previous</button><button class="btn" id="next" type="button">Next</button></span></div>
    </section>`;

  let offset = 0;
  const f = (sel) => el.querySelector(sel);

  async function refresh() {
    const data = await ctx.getJSON("/dashboard/ledger", {
      decision_type: f("#type").value,
      verdict: f("#verdict").value,
      user_id: f("#user").value.trim(),
      session_id: f("#session").value.trim(),
      agent_id: f("#agent").value.trim(),
      q: f("#q").value.trim(),
      limit: PAGE,
      offset,
    });
    f("#range").textContent = data.total ? `Showing ${num(offset + 1)} to ${num(offset + data.items.length)} of ${num(data.total)}` : "";
    f("#prev").disabled = offset === 0;
    f("#next").disabled = offset + data.items.length >= data.total;
    f("#list").innerHTML = table(
      [
        { label: "Time", sort: "timestamp", render: (r) => `<span class="num">${esc(dateTime(r.timestamp))}</span>` },
        { label: "Check", sort: "decision_type", render: (r) => `${esc(r.decision_type)}<br><span class="muted">${esc(r.ref_id || "")}</span>` },
        { label: "Outcome", sort: "outcome", render: (r) => `${outcomeChip(r.outcome)}${r.verdict !== r.outcome ? `<br><span class="muted">${esc(r.verdict)}</span>` : ""}` },
        { label: "User", sort: "user_id", render: (r) => userLink(r.user_id) },
        { label: "Session", sort: "session_id", render: (r) => sessionLink(r.session_id) },
        { label: "Agent", sort: "agent_id", render: (r) => `<span class="mono">${esc(r.agent_id)}</span>` },
        { label: "Detail", render: (r) => `${r.identifiers.length ? redactions(r.identifiers) : `<span class="cell-wrap secondary">${esc(r.reason || "")}</span>`}${r.text ? `<div class="cell-text">${renderText(r.text)}</div>` : r.blocked ? '<div class="cell-text muted">Blocked, not forwarded</div>' : ""}` },
        { label: "Hash (prev)", render: (r) => `<span class="mono muted hash">${esc(r.hash)}<br>prev ${esc(r.prev_hash)}</span>` },
      ],
      data.items,
      { empty: "No records match the current filters." },
    );
  }

  let debounce;
  const kick = () => {
    offset = 0;
    clearTimeout(debounce);
    debounce = setTimeout(() => refresh().then(ctx.reportOk, ctx.reportError), 250);
  };
  el.querySelectorAll(".toolbar input, .toolbar select").forEach((x) => x.addEventListener(x.tagName === "SELECT" ? "change" : "input", kick));
  f("#prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); refresh().then(ctx.reportOk, ctx.reportError); });
  f("#next").addEventListener("click", () => { offset += PAGE; refresh().then(ctx.reportOk, ctx.reportError); });

  await refresh();
  return { refresh, destroy: () => clearTimeout(debounce) };
}
