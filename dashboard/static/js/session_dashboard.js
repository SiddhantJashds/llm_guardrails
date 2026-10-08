// Per-agent trust score trend + violations + denied calls for one session.
const SERIES_COLORS = ["--series-1", "--series-2", "--series-3", "--series-4"];

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

let trendChart = null;
let pollInterval = null;
let sessionId = "";

async function loadSession() {
  sessionId = document.getElementById("session-id-input").value.trim();
  if (!sessionId) return;
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  await refreshData();
  pollInterval = setInterval(refreshData, 3000);
}

async function refreshData() {
  if (!sessionId) return;
  try {
    const data = await fetchSessionDashboard(sessionId);
    renderTrendChart(data.agents);
    renderViolations(data.agents);
    renderDeniedCalls(data.agents);
  } catch (e) {
    console.warn("Live refresh failed:", e);
  }
}

function renderTrendChart(agents) {
  const ctx = document.getElementById("trust-trend-chart").getContext("2d");

  const datasets = agents.map((agent, i) => {
    const color = cssVar(SERIES_COLORS[i % SERIES_COLORS.length]);
    const scores = (agent.history || []).reduce((acc, h) => {
      const prev = acc.length ? acc[acc.length - 1] : 100;
      acc.push(prev + (h.delta || 0));
      return acc;
    }, []);
    return {
      label: agent.agent_id,
      data: scores.length ? scores : [agent.current_score ?? 100],
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      pointRadius: 3,
      tension: 0,
    };
  });

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: datasets.length ? datasets[0].data.map((_, i) => `step ${i + 1}`) : [],
      datasets,
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: agents.length >= 2 },
        tooltip: { enabled: true },
      },
      scales: {
        y: { min: 0, max: 100, grid: { color: cssVar("--gridline") } },
        x: { grid: { display: false } },
      },
    },
  });
}

function renderViolations(agents) {
  const container = document.getElementById("violations-list");
  const rows = agents.flatMap((a) => a.violations.map((v) => ({ ...v, agent_id: a.agent_id })));
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">No compliance violations recorded.</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Agent</th><th>Reason</th><th>Time</th></tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.agent_id)}</td>
          <td><span class="status-badge warning">violation</span> ${escapeHtml(r.reason ?? "")}</td>
          <td>${escapeHtml(new Date(r.timestamp).toLocaleString())}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

function renderDeniedCalls(agents) {
  const container = document.getElementById("denied-calls-list");
  const rows = agents.flatMap((a) => a.denied_calls.map((d) => ({ ...d, agent_id: a.agent_id })));
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">No denied tool calls recorded.</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>Agent</th><th>Reason</th><th>Time</th></tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.agent_id)}</td>
          <td><span class="status-badge critical">denied</span> ${escapeHtml(r.reason ?? "")}</td>
          <td>${escapeHtml(new Date(r.timestamp).toLocaleString())}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

// Show live indicator once polling starts.
function setLive(active) {
  const badge = document.getElementById("live-indicator");
  if (badge) badge.style.display = active ? "inline" : "none";
}
document.getElementById("load-session-btn").addEventListener("click", () => {
  loadSession();
  setLive(true);
});
