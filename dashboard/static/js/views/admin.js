// Admin (config only, no login -- docs/adr/0005): tool thresholds, pack
// actions, per-user unredacted overrides. Same endpoints as before.
// Not auto-refreshed: polling would overwrite values while you edit them.
import { esc, emptyState, icon, table } from "../ui.js";

const ACTIONS = ["redact", "block", "hash", "log_only"];

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title"><h1>Policy settings</h1><p class="secondary">Authority thresholds, compliance actions, and per-user overrides. All users are fully restricted unless an override is granted.</p></div>
    </div>
    <section class="panel panel--flush"><div class="panel__head"><h2>Tool authority thresholds</h2><span class="panel__note">Minimum trust score an agent needs to call each tool</span></div><div id="thresholds"></div></section>
    <div class="grid-halves">
      <section class="panel panel--flush"><div class="panel__head"><h2>HIPAA identifier actions</h2></div><div id="pack-hipaa"></div></section>
      <section class="panel panel--flush"><div class="panel__head"><h2>DPDP identifier actions</h2></div><div id="pack-dpdp"></div></section>
    </div>
    <section class="panel">
      <div class="panel__head"><h2>Unredacted output overrides</h2></div>
      <p class="secondary" style="margin-bottom:12px">Lets a user_id see unredacted output, still only when they explicitly ask per request (<code>x-request-unredacted: true</code>). Block and hash actions are never affected.</p>
      <div class="toolbar" style="margin-bottom:12px">
        <input class="input" id="ov-user" type="text" placeholder="user_id" aria-label="user_id" />
        <label class="check"><input id="ov-allow" type="checkbox" /> Allow unredacted</label>
        <button class="btn btn--primary" id="ov-save" type="button">Save override</button>
      </div>
      <div id="overrides"></div>
    </section>
    <section class="panel danger">
      <div class="panel__head"><h2>Reset activity data</h2></div>
      <p class="secondary" style="margin-bottom:12px">Permanently deletes all audit records, trust scores, token usage and user profiles so you can start a fresh demo. Policy settings on this page are kept. This cannot be undone.</p>
      <div class="toolbar">
        <input class="input" id="reset-confirm" type="text" placeholder="Type RESET to confirm" aria-label="Type RESET to confirm" autocomplete="off" />
        <button class="btn btn--danger" id="reset-btn" type="button" disabled>${icon("delete_forever", "icon--sm")}Reset activity data</button>
        <span id="reset-result" class="secondary"></span>
      </div>
    </section>`;

  const flash = (btn, text = "Saved") => {
    const old = btn.textContent;
    btn.textContent = text;
    setTimeout(() => (btn.textContent = old), 1200);
  };

  async function loadThresholds() {
    const rows = await ctx.getJSON("/admin/tool-thresholds");
    const box = el.querySelector("#thresholds");
    box.innerHTML = table(
      [
        { label: "Tool", sort: "tool_id", render: (r) => `<span class="mono">${esc(r.tool_id)}</span>` },
        { label: "Threshold", sort: "threshold", render: (r) => `<input class="input threshold" type="number" step="1" min="0" max="100" value="${esc(r.threshold)}" data-tool="${esc(r.tool_id)}" aria-label="threshold for ${esc(r.tool_id)}" style="width:96px" />` },
        { label: "", render: (r) => `<button class="btn save-threshold" type="button" data-tool="${esc(r.tool_id)}">Save</button>` },
      ],
      rows,
      { empty: "No tool thresholds configured. The default threshold applies." },
    );
    box.querySelectorAll(".save-threshold").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const input = [...box.querySelectorAll(".threshold")].find((i) => i.dataset.tool === btn.dataset.tool);
        await ctx.putJSON(`/admin/tool-thresholds/${encodeURIComponent(btn.dataset.tool)}`, { threshold: parseFloat(input.value) });
        flash(btn);
      }),
    );
  }

  async function loadPack(pack) {
    const rows = await ctx.getJSON(`/admin/compliance-pack/${pack}`);
    const box = el.querySelector(`#pack-${pack}`);
    box.innerHTML = table(
      [
        { label: "Identifier", sort: "identifier", render: (r) => `<span class="redact">${esc(r.identifier)}</span>` },
        { label: "Action", render: (r) => `<select class="select action" data-id="${esc(r.identifier)}" aria-label="action for ${esc(r.identifier)}">${ACTIONS.map((a) => `<option value="${a}"${a === r.action ? " selected" : ""}>${a}</option>`).join("")}</select>` },
        { label: "", render: (r) => `<button class="btn save-action" type="button" data-id="${esc(r.identifier)}">Save</button>` },
      ],
      rows,
      { empty: "No identifiers configured for this pack." },
    );
    box.querySelectorAll(".save-action").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const select = [...box.querySelectorAll(".action")].find((s) => s.dataset.id === btn.dataset.id);
        await ctx.putJSON(`/admin/compliance-pack/${pack}/${encodeURIComponent(btn.dataset.id)}`, { action: select.value });
        flash(btn);
      }),
    );
  }

  async function loadOverrides() {
    const rows = await ctx.getJSON("/admin/users");
    el.querySelector("#overrides").innerHTML = rows.length
      ? table(
          [
            { label: "User", sort: "user_id", render: (r) => `<span class="mono">${esc(r.user_id)}</span>` },
            { label: "Unredacted", render: (r) => (r.allow_unredacted ? '<span class="chip chip--redact">${icon("lock_open", "icon--xs")}Override granted</span>' : '<span class="chip chip--allow">${icon("lock", "icon--xs")}Restricted</span>') },
          ],
          rows,
        )
      : emptyState("No overrides granted.", "All users receive redacted output by default.");
  }

  el.querySelector("#ov-save").addEventListener("click", async (e) => {
    const userId = el.querySelector("#ov-user").value.trim();
    if (!userId) return;
    await ctx.putJSON(`/admin/users/${encodeURIComponent(userId)}`, { allow_unredacted: el.querySelector("#ov-allow").checked });
    flash(e.currentTarget);
    await loadOverrides();
  });

  const confirmInput = el.querySelector("#reset-confirm");
  const resetBtn = el.querySelector("#reset-btn");
  confirmInput.addEventListener("input", () => (resetBtn.disabled = confirmInput.value.trim() !== "RESET"));
  resetBtn.addEventListener("click", async () => {
    resetBtn.disabled = true;
    try {
      const resp = await fetch(`${window.__dash.apiBase}/admin/reset`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ confirm: confirmInput.value.trim() }) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      const d = data.deleted;
      el.querySelector("#reset-result").textContent = `Deleted ${d.receipts} audit records, ${d.agent_trust_state} trust states, ${d.token_usage_events} token events and ${d.user_profiles} profiles.`;
      confirmInput.value = "";
    } catch (err) {
      el.querySelector("#reset-result").textContent = `Reset failed: ${err.message}`;
      resetBtn.disabled = false;
    }
  });

  await Promise.all([loadThresholds(), loadPack("hipaa"), loadPack("dpdp"), loadOverrides()]);
  return { refresh: null, destroy() {} };
}
