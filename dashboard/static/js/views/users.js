// Users: everyone who ever made a governed call, with live ratings.
import { ago, bindRowLinks, esc, meter, num, table, userHref, userLink } from "../ui.js";

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Users</h1><p class="secondary" id="count">All users with recorded activity. Ratings are calculated from the current audit ledger.</p></div>
    </div>
    <div class="toolbar"><input class="input input--grow" id="q" type="search" placeholder="Search by user ID" aria-label="Search users" /></div>
    <section class="panel panel--flush"><div id="list"></div></section>`;
  bindRowLinks(el);
  const q = el.querySelector("#q");

  async function refresh() {
    const data = await ctx.getJSON("/dashboard/users", { q: q.value.trim(), limit: 1000 });
    el.querySelector("#count").textContent = `${num(data.total)} users.`;
    el.querySelector("#list").innerHTML = table(
      [
        { label: "User", sort: "user_id", render: (u) => userLink(u.user_id) },
        { label: "Sessions", sort: "sessions", cls: "num", render: (u) => num(u.sessions) },
        { label: "Decisions", sort: "decisions", cls: "num", render: (u) => num(u.decisions) },
        { label: "Redacted", sort: "redactions", cls: "num", render: (u) => num(u.redactions) },
        { label: "Blocked", sort: "blocks", cls: "num", render: (u) => num(u.blocks) },
        { label: "Denied", sort: "denials", cls: "num", render: (u) => num(u.denials) },
        { label: "Tokens in", sort: "tokens_in", cls: "num", render: (u) => num(u.tokens_in) },
        { label: "Tokens out", sort: "tokens_out", cls: "num", render: (u) => num(u.tokens_out) },
        { label: "Composite rating", sort: "composite_rating", render: (u) => meter(u.composite_rating) },
        { label: "Last seen", sort: "last_seen", render: (u) => `<span title="${esc(u.last_seen)}">${esc(ago(u.last_seen))}</span>` },
      ],
      data.items,
      { rowHref: (u) => userHref(u.user_id), empty: q.value ? "No users match the current search." : "No users recorded yet." },
    );
  }

  let debounce;
  q.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => refresh().then(ctx.reportOk, ctx.reportError), 250);
  });

  await refresh();
  return { refresh, destroy: () => clearTimeout(debounce) };
}
