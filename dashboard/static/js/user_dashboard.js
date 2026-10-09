// Per-user token usage + composite rating + violation/decision history.
let usageChart = null;
let pollInterval = null;
let userId = "";

async function loadUser() {
  userId = document.getElementById("user-id-input").value.trim();
  if (!userId) return;
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  await refreshData();
  pollInterval = setInterval(refreshData, 3000);
}

async function refreshData() {
  if (!userId) return;
  try {
    const data = await fetchUserDashboard(userId);
    renderProfileTiles(data.profile);
    renderUsageChart(data.token_usage || []);
    renderDecisionHistory(data.recent_decisions);
  } catch (e) {
    console.warn("Live refresh failed:", e);
  }
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function renderProfileTiles(profile) {
  document.getElementById("tile-tokens-in").textContent = profile.total_tokens_in;
  document.getElementById("tile-tokens-out").textContent = profile.total_tokens_out;
  document.getElementById("tile-rating").textContent =
    profile.composite_rating != null ? profile.composite_rating.toFixed(1) : "—";
  document.getElementById("tile-violations").textContent = profile.violation_count;
}

function renderUsageChart(events) {
  const ctx = document.getElementById("token-usage-chart").getContext("2d");
  if (usageChart) usageChart.destroy();
  // One point per upstream LLM call (TokenUsageEvent), oldest first.
  const series = (key, cssName, label) => ({
    label,
    data: events.map((e) => e[key]),
    borderColor: cssVar(cssName),
    backgroundColor: cssVar(cssName),
    borderWidth: 2,
    pointRadius: 3,
    tension: 0,
  });
  usageChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: events.map((e) => new Date(e.timestamp).toLocaleTimeString()),
      datasets: [series("tokens_in", "--series-1", "Tokens in"), series("tokens_out", "--series-2", "Tokens out")],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true }, tooltip: { enabled: true } },
      scales: { y: { beginAtZero: true, grid: { color: cssVar("--gridline") } }, x: { grid: { display: false } } },
    },
  });
}

function renderDecisionHistory(decisions) {
  const container = document.getElementById("decision-history-list");
  if (!decisions.length) {
    container.innerHTML = '<div class="empty-state">No decisions recorded yet for this user.</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Type</th><th>Verdict</th><th>Reason</th><th>Time</th></tr></thead>
    <tbody>${decisions
      .slice()
      .reverse()
      .map(
        (d) => `<tr>
          <td>${escapeHtml(d.decision_type)}</td>
          <td>${escapeHtml(d.verdict)}</td>
          <td>${escapeHtml(d.reason ?? "")}</td>
          <td>${escapeHtml(new Date(d.timestamp).toLocaleString())}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

function setLive(active) {
  const badge = document.getElementById("live-indicator");
  if (badge) badge.style.display = active ? "inline" : "none";
}
document.getElementById("load-user-btn").addEventListener("click", () => {
  loadUser();
  setLive(true);
});
