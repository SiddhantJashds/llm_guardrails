// App shell: hash router, one poll loop for the current view, live/pause,
// theme toggle, and the "API unreachable" banner.
import { API_BASE, ApiError, escapeHtml, getJSON, putJSON } from "./api.js";
import { initChat } from "./chat.js";

const POLL_MS = 5000;

const ROUTES = [
  { pattern: /^#\/overview$/, nav: "overview", load: () => import("./views/overview.js") },
  { pattern: /^#\/sessions$/, nav: "sessions", load: () => import("./views/sessions.js") },
  { pattern: /^#\/session\/(.+)$/, nav: "sessions", load: () => import("./views/session.js"), param: "id" },
  { pattern: /^#\/users$/, nav: "users", load: () => import("./views/users.js") },
  { pattern: /^#\/user\/(.+)$/, nav: "users", load: () => import("./views/user.js"), param: "id" },
  { pattern: /^#\/ledger$/, nav: "ledger", load: () => import("./views/ledger.js") },
  { pattern: /^#\/live$/, nav: "live", load: () => import("./views/live.js") },
  { pattern: /^#\/bench$/, nav: "bench", load: () => import("./views/bench.js") },
  { pattern: /^#\/bench\/(.+)$/, nav: "bench", load: () => import("./views/bench.js"), param: "name" },
  { pattern: /^#\/admin$/, nav: "admin", load: () => import("./views/admin.js") },
];

const viewEl = document.getElementById("view");
const bannerEl = document.getElementById("banner");
const liveBtn = document.getElementById("live-toggle");
const apiStatusEl = document.getElementById("api-status");

let current = null; // { view, token }
let mountToken = 0;
let paused = false;
let timer = null;
let pending = 0; // timers scheduled -- the smoke script asserts this stays <= 1

const ctx = {
  getJSON,
  putJSON,
  navigate: (hash) => (location.hash = hash),
  reportError,
  reportOk,
};

function reportError(err) {
  const msg = err instanceof ApiError && err.status === 0
    ? `${err.message} Start the services with ./run.sh. Retrying every ${POLL_MS / 1000} seconds.`
    : err.message || String(err);
  bannerEl.textContent = msg;
  bannerEl.hidden = false;
  liveBtn.classList.add("live--down");
  apiStatusEl.innerHTML = `<span class="api-status__state api-status__state--down">Not connected</span><span class="api-status__url">${escapeHtml(API_BASE)}</span>`;
}

function reportOk() {
  bannerEl.hidden = true;
  liveBtn.classList.remove("live--down");
  apiStatusEl.innerHTML = `<span class="api-status__state api-status__state--ok">Connected</span><span class="api-status__url">${escapeHtml(API_BASE)}</span><span>Updated ${escapeHtml(new Date().toLocaleTimeString())}</span>`;
}

function schedule() {
  clearTimeout(timer);
  pending = 1;
  timer = setTimeout(tick, POLL_MS);
}

async function tick() {
  pending = 0;
  const mine = current;
  if (!paused && mine && mine.view.refresh && document.visibilityState !== "hidden") {
    try {
      await mine.view.refresh();
      if (mine === current) reportOk();
    } catch (err) {
      if (mine === current) reportError(err);
    }
  }
  schedule();
}

function matchRoute(hash) {
  for (const r of ROUTES) {
    const m = hash.match(r.pattern);
    if (m) return { route: r, params: r.param ? { [r.param]: decodeURIComponent(m[1]) } : {} };
  }
  return null;
}

async function render() {
  const hash = location.hash || "#/overview";
  const found = matchRoute(hash);
  if (!found) {
    location.replace("#/overview");
    return;
  }
  const token = ++mountToken;
  if (current) {
    try { current.view.destroy && current.view.destroy(); } catch (_) { /* view already gone */ }
    current = null;
  }
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.nav === found.route.nav) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  viewEl.innerHTML = '<div class="loading">Loading…</div>';
  try {
    const mod = await found.route.load();
    if (token !== mountToken) return;
    viewEl.innerHTML = "";
    const view = await mod.mount(viewEl, found.params, ctx);
    if (token !== mountToken) {
      view.destroy && view.destroy();
      return;
    }
    current = { view };
    reportOk();
  } catch (err) {
    if (token !== mountToken) return;
    reportError(err);
    viewEl.innerHTML = `<div class="panel empty"><strong>This page couldn't load.</strong>${
      err instanceof ApiError ? "Check that governance_api is running, then it will retry on its own." : ""
    }</div>`;
    // Retry the mount on the next tick so a page that failed while the API
    // was down comes back by itself.
    current = { view: { refresh: async () => { await render(); } } };
  }
  schedule();
}

// Live / pause
liveBtn.addEventListener("click", () => {
  paused = !paused;
  liveBtn.classList.toggle("live--paused", paused);
  liveBtn.querySelector(".live__label").textContent = paused ? "Auto-refresh off" : "Auto-refresh on";
  liveBtn.setAttribute("aria-pressed", String(!paused));
  if (!paused) tick();
});

// Theme: follow system, or pin light/dark. Stored per browser.
const themeButtons = document.querySelectorAll("[data-theme-choice]");
function applyTheme(theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  themeButtons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeChoice === theme)));
}
let theme = "system";
try { theme = localStorage.getItem("dash-theme") || "system"; } catch (_) { /* storage blocked */ }
applyTheme(theme);
themeButtons.forEach((b) =>
  b.addEventListener("click", () => {
    if (b.dataset.themeChoice === theme) return;
    theme = b.dataset.themeChoice;
    try { localStorage.setItem("dash-theme", theme); } catch (_) { /* storage blocked */ }
    applyTheme(theme);
    render(); // charts re-read colour tokens on mount
  }),
);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => theme === "system" && render());

window.addEventListener("hashchange", render);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !paused) tick();
});

window.__dash = { activePolls: () => pending, apiBase: API_BASE };

initChat(ctx);
render();
