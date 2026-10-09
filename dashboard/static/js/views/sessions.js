// Sessions: every session that ever existed, searchable and filterable.
import { ago, bindRowLinks, chainOkCell, esc, meter, num, sessionHref, sessionLink, table, userLink } from "../ui.js";

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Sessions</h1><p class="secondary" id="count">All sessions recorded by the governance runtime.</p></div>
    </div>
    <div class="toolbar">
      <input class="input input--grow" id="q" type="search" placeholder="Search by session, user, or agent ID" aria-label="Search sessions" />
      <input class="input" id="user" type="search" placeholder="Exact user_id" aria-label="Filter by user" />
      <label class="check"><input type="checkbox" id="flagged" /> Show only sessions with interventions</label>
    </div>
    <section class="panel panel--flush"><div id="list"></div></section>`;
  bindRowLinks(el);

  const q = el.querySelector("#q");
  const user = el.querySelector("#user");
  const flagged = el.querySelector("#flagged");

  async function refresh() {
    const data = await ctx.getJSON("/dashboard/sessions", { q: q.value.trim(), user_id: user.value.trim(), flagged: flagged.checked ? "true" : "", limit: 1000 });
    el.querySelector("#count").textContent = `${num(data.total)} sessions${data.total > data.items.length ? `, showing the newest ${data.items.length}` : ""}.`;
    el.querySelector("#list").innerHTML = table(
      [
        { label: "Session", sort: "session_id", render: (s) => sessionLink(s.session_id) },
        { label: "User", sort: (s) => s.user_ids.join(", "), render: (s) => s.user_ids.map(userLink).join(", ") || "—" },
        { label: "Agents", sort: (s) => s.agents.length, render: (s) => `<span class="num">${s.agents.length}</span> <span class="muted mono id">${esc(s.agents.join(", "))}</span>` },
        { label: "Decisions", sort: "decisions", cls: "num", render: (s) => num(s.decisions) },
        { label: "Redacted", sort: "redactions", cls: "num", render: (s) => num(s.redactions) },
        { label: "Blocked", sort: "blocks", cls: "num", render: (s) => num(s.blocks) },
        { label: "Denied", sort: "denials", cls: "num", render: (s) => num(s.denials) },
        { label: "Lowest score", sort: "min_score", render: (s) => meter(s.min_score) },
        { label: "Tokens", sort: (s) => s.tokens_in + s.tokens_out, cls: "num", render: (s) => num(s.tokens_in + s.tokens_out) },
        { label: "Integrity", sort: (s) => (s.chain_ok ? 1 : 0), render: (s) => chainOkCell(s.chain_ok) },
        { label: "Last activity", sort: "last_seen", render: (s) => `<span title="${esc(s.last_seen)}">${esc(ago(s.last_seen))}</span>` },
      ],
      data.items,
      { rowHref: (s) => sessionHref(s.session_id), empty: q.value || user.value || flagged.checked ? "No sessions match the current filters." : "No sessions recorded yet." },
    );
  }

  let debounce;
  const kick = () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => refresh().then(ctx.reportOk, ctx.reportError), 250);
  };
  q.addEventListener("input", kick);
  user.addEventListener("input", kick);
  flagged.addEventListener("change", kick);

  await refresh();
  return { refresh, destroy: () => clearTimeout(debounce) };
}
