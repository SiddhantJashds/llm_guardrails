// Config-only admin page: tool thresholds, compliance pack actions, and
// per-user_id unredacted overrides. No login here -- see docs/adr/0005.
const ACTIONS = ["redact", "block", "hash", "log_only"];

async function apiGet(path) {
  const resp = await fetch(`${GOVERNANCE_API_BASE_URL}${path}`);
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  return resp.json();
}

async function apiPut(path, body) {
  const resp = await fetch(`${GOVERNANCE_API_BASE_URL}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`PUT ${path} failed: ${resp.status}`);
  return resp.json();
}

async function loadThresholds() {
  const rows = await apiGet("/admin/tool-thresholds");
  const container = document.getElementById("thresholds-table");
  container.innerHTML = `<table>
    <thead><tr><th>Tool</th><th>Threshold</th><th></th></tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.tool_id)}</td>
          <td><input type="number" step="0.1" value="${escapeHtml(r.threshold)}" data-tool-id="${escapeHtml(r.tool_id)}" class="threshold-input" /></td>
          <td><button data-tool-id="${escapeHtml(r.tool_id)}" class="save-threshold-btn">Save</button></td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
  container.querySelectorAll(".save-threshold-btn").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const toolId = btn.dataset.toolId;
      const input = container.querySelector(`.threshold-input[data-tool-id="${toolId}"]`);
      await apiPut(`/admin/tool-thresholds/${encodeURIComponent(toolId)}`, { threshold: parseFloat(input.value) });
      btn.textContent = "Saved";
      setTimeout(() => (btn.textContent = "Save"), 1200);
    })
  );
}

async function loadPack(packId, containerId) {
  const rows = await apiGet(`/admin/compliance-pack/${packId}`);
  const container = document.getElementById(containerId);
  container.innerHTML = `<table>
    <thead><tr><th>Identifier</th><th>Action</th><th></th></tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.identifier)}</td>
          <td><select data-identifier="${escapeHtml(r.identifier)}" class="action-select">
            ${ACTIONS.map((a) => `<option value="${escapeHtml(a)}" ${a === r.action ? "selected" : ""}>${escapeHtml(a)}</option>`).join("")}
          </select></td>
          <td><button data-identifier="${escapeHtml(r.identifier)}" class="save-action-btn">Save</button></td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
  container.querySelectorAll(".save-action-btn").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const identifier = btn.dataset.identifier;
      const select = container.querySelector(`.action-select[data-identifier="${identifier}"]`);
      await apiPut(`/admin/compliance-pack/${packId}/${encodeURIComponent(identifier)}`, { action: select.value });
      btn.textContent = "Saved";
      setTimeout(() => (btn.textContent = "Save"), 1200);
    })
  );
}

async function loadUserOverrides() {
  const rows = await apiGet("/admin/users");
  const container = document.getElementById("overrides-table");
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state">No overrides granted yet -- every user_id is fully restrictive by default.</div>';
    return;
  }
  container.innerHTML = `<table>
    <thead><tr><th>User ID</th><th>Allow unredacted</th></tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.user_id)}</td>
          <td><span class="status-badge ${r.allow_unredacted ? "warning" : "critical"}">${
          r.allow_unredacted ? "override granted" : "restrictive"
        }</span></td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
}

async function grantOverride() {
  const userId = document.getElementById("override-user-id-input").value.trim();
  const allow = document.getElementById("override-allow-checkbox").checked;
  if (!userId) return;
  await apiPut(`/admin/users/${encodeURIComponent(userId)}`, { allow_unredacted: allow });
  await loadUserOverrides();
}

document.getElementById("grant-override-btn").addEventListener("click", grantOverride);

loadThresholds();
loadPack("hipaa", "hipaa-pack-table");
loadPack("dpdp", "dpdp-pack-table");
loadUserOverrides();
