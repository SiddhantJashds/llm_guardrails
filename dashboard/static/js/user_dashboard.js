// Per-user token usage + composite rating + violation/decision history.
let usageChart = null;

async function loadUser() {
  const userId = document.getElementById("user-id-input").value.trim();
  if (!userId) return;

  const data = await fetchUserDashboard(userId);
  renderProfileTiles(data.profile);
  renderUsageChart(data.profile);
  renderDecisionHistory(data.recent_decisions);
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

function renderUsageChart(profile) {
  const ctx = document.getElementById("token-usage-chart").getContext("2d");
  if (usageChart) usageChart.destroy();
  // TODO: replace this single-point placeholder with the real time series
  // once data_pipeline/ingestion/token_usage_pipeline.py is populating events.
  usageChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: ["tokens in", "tokens out"],
      datasets: [
        {
          label: "Total tokens",
          data: [profile.total_tokens_in, profile.total_tokens_out],
          backgroundColor: [cssVar("--series-1"), cssVar("--series-2")],
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: { y: { grid: { color: cssVar("--gridline") } }, x: { grid: { display: false } } },
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

document.getElementById("load-user-btn").addEventListener("click", loadUser);
