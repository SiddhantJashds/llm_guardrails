// Admin policy settings (docs/adr/0005, docs/adr/0016):
//  - Tool authority thresholds
//  - Compliance identifier rules per pack (HIPAA / DPDP toggle)
//  - Redaction roles matrix (identifiers x roles)
//  - User role assignments
//  - Legacy unredacted output overrides
//  - Activity data reset (type RESET)
// Not auto-refreshed: polling would overwrite values while you edit them.
import { esc, emptyState, icon, kindOf, renderText, table } from "../ui.js";

const ACTIONS = ["redact", "block", "hash", "log_only"];
const STYLES = ["token", "partial", "masked"];
const APPLIES_TO = ["both", "inbound", "outbound"];
const LEVELS = ["hidden", "partial", "full"];

function previewHtml(id, action, style, keepLast, placeholder) {
  if (action === "block") return '<span class="chip chip--block">Block request</span>';
  if (action === "log_only") return '<span class="chip chip--neutral">Raw value (logged)</span>';
  if (action === "hash") return '<span class="ent ent--hash">#8f3c1a</span>';
  if (style === "masked") {
    const k = kindOf(id);
    return `<span class="ent" style="--c:${k.color}">[REDACTED_${esc(k.kind)}]</span>`;
  }
  if (style === "partial") {
    const n = Math.max(0, Math.min(12, Number(keepLast) || 0));
    const k = kindOf(id);
    let sample = "••••";
    if (id.includes("phone") || id.includes("fax")) sample = `(••••) •••-${"7788".slice(-n) || "••••"}`;
    else if (id.includes("email")) sample = "a••••@example.com";
    else sample = `••••${"4321".slice(-n) || "••••"}`;
    return `<span class="ent" style="--c:${k.color}">${esc(sample)}</span>`;
  }
  return renderText(placeholder || `[${kindOf(id).kind}_1]`);
}

export async function mount(el, _params, ctx) {
  el.innerHTML = `
    <div class="view-head">
      <div class="view-head__title">
        <h1>Policy settings</h1>
        <p class="secondary">Authority thresholds, compliance identifier rules, redaction roles, and user assignments.</p>
      </div>
    </div>

    <section class="panel panel--flush">
      <div class="panel__head">
        <h2>Tool authority thresholds</h2>
        <span class="panel__note">Minimum trust score an agent needs to call each tool</span>
      </div>
      <div id="thresholds"></div>
    </section>

    <section class="panel panel--flush" style="margin-top:var(--s-4)">
      <div class="panel__head">
        <div style="display:flex;align-items:center;gap:var(--s-3)">
          <h2>Identifier rules</h2>
          <div class="segmented" id="pack-toggle" role="tablist">
            <button type="button" data-pack="hipaa" aria-pressed="true">HIPAA</button>
            <button type="button" data-pack="dpdp" aria-pressed="false">DPDP</button>
          </div>
        </div>
        <span class="panel__note">How sensitive identifiers are transformed before reaching the model</span>
      </div>
      <div id="identifier-rules"></div>
    </section>

    <section class="panel" style="margin-top:var(--s-4)">
      <div class="panel__head">
        <h2>Redaction roles</h2>
        <span class="panel__note">Caps what callers see when requesting unredacted output</span>
      </div>
      <p class="secondary" style="margin-bottom:var(--s-3)">
        Roles are a cap, not a default: without an explicit request (<code>x-request-unredacted: true</code>),
        everyone receives placeholders. Block and hash actions are never relaxed.
      </p>
      <div class="toolbar" style="margin-bottom:var(--s-3)">
        <input class="input" id="new-role-id" type="text" placeholder="role_id (e.g. nurse)" aria-label="Role ID" style="width:160px" />
        <input class="input" id="new-role-label" type="text" placeholder="Label (e.g. Nurse)" aria-label="Role label" style="width:160px" />
        <input class="input" id="new-role-desc" type="text" placeholder="Description" aria-label="Role description" style="flex:1;min-width:200px" />
        <button class="btn btn--primary" id="add-role-btn" type="button">${icon("add", "icon--sm")}Add role</button>
      </div>
      <div class="table-wrap" id="roles-matrix"></div>
    </section>

    <div class="grid-halves" style="margin-top:var(--s-4)">
      <section class="panel">
        <div class="panel__head">
          <h2>User role assignments</h2>
          <span class="panel__note">Assign users to redaction roles</span>
        </div>
        <div class="toolbar" style="margin-bottom:var(--s-3)">
          <input class="input" id="ur-user" type="text" placeholder="user_id" aria-label="User ID" style="width:150px" />
          <select class="select" id="ur-role" aria-label="Role"><option value="">Select role...</option></select>
          <button class="btn btn--primary" id="ur-save" type="button">Assign</button>
        </div>
        <div id="user-roles-list"></div>
      </section>

      <section class="panel">
        <div class="panel__head">
          <h2>Unredacted output overrides (legacy)</h2>
          <span class="panel__note">Per-user bypass behaves like an all-full role</span>
        </div>
        <p class="secondary" style="margin-bottom:var(--s-3)">
          Lets a user_id see unredacted output when they explicitly ask per request. Block and hash are never relaxed.
        </p>
        <div class="toolbar" style="margin-bottom:var(--s-3)">
          <input class="input" id="ov-user" type="text" placeholder="user_id" aria-label="user_id" style="width:150px" />
          <label class="check"><input id="ov-allow" type="checkbox" /> Allow unredacted</label>
          <button class="btn btn--primary" id="ov-save" type="button">Save override</button>
        </div>
        <div id="overrides"></div>
      </section>
    </div>

    <section class="panel danger" style="margin-top:var(--s-4)">
      <div class="panel__head"><h2>Reset activity data</h2></div>
      <p class="secondary" style="margin-bottom:var(--s-3)">
        Permanently deletes all audit records, trust scores, token usage, user profiles, and clears the session placeholder vault.
        Policy settings on this page are kept. This cannot be undone.
      </p>
      <div class="toolbar">
        <input class="input" id="reset-confirm" type="text" placeholder="Type RESET to confirm" aria-label="Type RESET to confirm" autocomplete="off" />
        <button class="btn btn--danger" id="reset-btn" type="button" disabled>${icon("delete_forever", "icon--sm")}Reset activity data</button>
        <span id="reset-result" class="secondary"></span>
      </div>
    </section>`;

  let currentPack = "hipaa";
  let cachedRoles = [];
  let cachedIdentifiers = [];

  const flash = (btn, text = "Saved") => {
    const old = btn.textContent;
    btn.textContent = text;
    setTimeout(() => (btn.textContent = old), 1200);
  };

  // ---------------- Tool authority thresholds ----------------
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

  // ---------------- Identifier rules table ----------------
  async function loadIdentifierRules() {
    const rows = await ctx.getJSON(`/admin/identifier-policy/${currentPack}`);
    cachedIdentifiers = rows.map((r) => r.identifier);
    const box = el.querySelector("#identifier-rules");

    box.innerHTML = table(
      [
        {
          label: "Identifier",
          sort: "identifier",
          render: (r) => {
            const k = kindOf(r.identifier);
            return `<span class="ent" style="--c:${k.color}">${esc(r.identifier)}</span>`;
          },
        },
        {
          label: "Action",
          render: (r) => `<select class="select ir-action" data-id="${esc(r.identifier)}" aria-label="Action for ${esc(r.identifier)}">
            ${ACTIONS.map((a) => `<option value="${a}"${a === r.action ? " selected" : ""}>${a}</option>`).join("")}
          </select>`,
        },
        {
          label: "Model sees (style)",
          render: (r) => `<select class="select ir-style" data-id="${esc(r.identifier)}" aria-label="Style for ${esc(r.identifier)}"${r.action !== "redact" ? " disabled" : ""}>
            ${STYLES.map((s) => `<option value="${s}"${s === r.style ? " selected" : ""}>${s}</option>`).join("")}
          </select>`,
        },
        {
          label: "Keep last",
          render: (r) => `<input class="input ir-keep" type="number" min="0" max="12" value="${esc(r.keep_last ?? 4)}" data-id="${esc(r.identifier)}" aria-label="Keep last for ${esc(r.identifier)}" style="width:68px"${r.action !== "redact" || r.style !== "partial" ? " disabled" : ""} />`,
        },
        {
          label: "Restore to sender",
          render: (r) => `<label class="check"><input type="checkbox" class="ir-restore" data-id="${esc(r.identifier)}"${r.restore_to_sender ? " checked" : ""}${r.action !== "redact" || r.style !== "token" ? " disabled" : ""} /> Yes</label>`,
        },
        {
          label: "Applies to",
          render: (r) => `<select class="select ir-applies" data-id="${esc(r.identifier)}" aria-label="Applies to for ${esc(r.identifier)}">
            ${APPLIES_TO.map((d) => `<option value="${d}"${d === r.applies_to ? " selected" : ""}>${d}</option>`).join("")}
          </select>`,
        },
        {
          label: "Example preview",
          render: (r) => `<span class="ir-preview" data-id="${esc(r.identifier)}" data-placeholder="${esc(r.placeholder)}">${previewHtml(r.identifier, r.action, r.style, r.keep_last, r.placeholder)}</span>`,
        },
        {
          label: "",
          render: (r) => `<button class="btn btn--sm save-ir" type="button" data-id="${esc(r.identifier)}">Save</button>`,
        },
      ],
      rows,
      { empty: "No identifiers configured for this pack." },
    );

    function updateRowControls(rowEl) {
      const actionSel = rowEl.querySelector(".ir-action");
      const styleSel = rowEl.querySelector(".ir-style");
      const keepInput = rowEl.querySelector(".ir-keep");
      const restoreChk = rowEl.querySelector(".ir-restore");
      const previewEl = rowEl.querySelector(".ir-preview");
      const id = actionSel.dataset.id;
      const placeholder = previewEl.dataset.placeholder;

      const isRedact = actionSel.value === "redact";
      styleSel.disabled = !isRedact;
      keepInput.disabled = !isRedact || styleSel.value !== "partial";
      restoreChk.disabled = !isRedact || styleSel.value !== "token";

      previewEl.innerHTML = previewHtml(id, actionSel.value, styleSel.value, keepInput.value, placeholder);
    }

    box.querySelectorAll("tr").forEach((tr) => {
      const actionSel = tr.querySelector(".ir-action");
      if (!actionSel) return;
      const styleSel = tr.querySelector(".ir-style");
      const keepInput = tr.querySelector(".ir-keep");

      actionSel.addEventListener("change", () => updateRowControls(tr));
      styleSel.addEventListener("change", () => updateRowControls(tr));
      keepInput.addEventListener("input", () => updateRowControls(tr));
    });

    box.querySelectorAll(".save-ir").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        const tr = btn.closest("tr");
        const action = tr.querySelector(".ir-action").value;
        const style = tr.querySelector(".ir-style").value;
        const keep_last = parseInt(tr.querySelector(".ir-keep").value, 10) || 0;
        const restore_to_sender = tr.querySelector(".ir-restore").checked;
        const applies_to = tr.querySelector(".ir-applies").value;

        await ctx.putJSON(`/admin/identifier-policy/${currentPack}/${encodeURIComponent(id)}`, {
          action,
          style,
          keep_last,
          restore_to_sender,
          applies_to,
        });
        flash(btn);
      }),
    );
  }

  // Pack toggle buttons
  el.querySelectorAll("#pack-toggle button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      el.querySelectorAll("#pack-toggle button").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      currentPack = btn.dataset.pack;
      await loadIdentifierRules();
    });
  });

  // ---------------- Redaction roles matrix ----------------
  async function loadRolesMatrix() {
    const [roles, hipaaRows, dpdpRows] = await Promise.all([
      ctx.getJSON("/admin/roles"),
      ctx.getJSON("/admin/identifier-policy/hipaa"),
      ctx.getJSON("/admin/identifier-policy/dpdp"),
    ]);
    cachedRoles = roles;

    // Update role select in user-role assignments toolbar
    const urRoleSelect = el.querySelector("#ur-role");
    urRoleSelect.innerHTML = '<option value="">Select role...</option>' +
      roles.map((r) => `<option value="${esc(r.role_id)}">${esc(r.label)} (${esc(r.role_id)})</option>`).join("");

    const idSet = new Set([...hipaaRows.map((r) => r.identifier), ...dpdpRows.map((r) => r.identifier)]);
    const allIdentifiers = [...idSet].sort();

    const box = el.querySelector("#roles-matrix");
    if (!roles.length) {
      box.innerHTML = emptyState("No roles configured.", "Add a role above to configure visibility levels.");
      return;
    }

    const headCols = roles
      .map(
        (r) => `<th scope="col" style="min-width:140px">
          <div><strong>${esc(r.label)}</strong></div>
          <div class="secondary" style="font-size:var(--t-xs)">${esc(r.role_id)}</div>
        </th>`,
      )
      .join("");

    const defaultRowCells = roles
      .map(
        (r) => `<td>
          <select class="select role-def-level" data-role="${esc(r.role_id)}" aria-label="Default level for ${esc(r.label)}">
            ${LEVELS.map((lvl) => `<option value="${lvl}"${lvl === r.default_level ? " selected" : ""}>${lvl}</option>`).join("")}
          </select>
        </td>`,
      )
      .join("");

    const idRows = allIdentifiers
      .map((id) => {
        const k = kindOf(id);
        const cells = roles
          .map((r) => {
            const currentLevel = (r.visibility && r.visibility[id]) ? r.visibility[id] : r.default_level;
            return `<td>
              <select class="select role-id-level" data-role="${esc(r.role_id)}" data-id="${esc(id)}" aria-label="${esc(id)} for ${esc(r.label)}">
                ${LEVELS.map((lvl) => `<option value="${lvl}"${lvl === currentLevel ? " selected" : ""}>${lvl}</option>`).join("")}
              </select>
            </td>`;
          })
          .join("");

        return `<tr>
          <td><span class="ent" style="--c:${k.color}">${esc(id)}</span></td>
          ${cells}
        </tr>`;
      })
      .join("");

    const actionCells = roles
      .map(
        (r) => `<td>
          <div style="display:flex;gap:4px;flex-wrap:wrap">
            <button class="btn btn--primary btn--sm save-role-btn" type="button" data-role="${esc(r.role_id)}">Save</button>
            <button class="btn btn--danger btn--sm del-role-btn" type="button" data-role="${esc(r.role_id)}">Delete</button>
          </div>
        </td>`,
      )
      .join("");

    box.innerHTML = `
      <table class="data">
        <thead>
          <tr>
            <th scope="col" style="width:220px">Identifier</th>
            ${headCols}
          </tr>
        </thead>
        <tbody>
          <tr style="background:var(--surface-sunk);font-weight:600">
            <td><em>Default level</em></td>
            ${defaultRowCells}
          </tr>
          ${idRows}
          <tr style="background:var(--surface-sunk)">
            <td><em>Actions</em></td>
            ${actionCells}
          </tr>
        </tbody>
      </table>`;

    // Save role handler
    box.querySelectorAll(".save-role-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const roleId = btn.dataset.role;
        const roleObj = cachedRoles.find((r) => r.role_id === roleId);
        if (!roleObj) return;

        const defSelect = box.querySelector(`.role-def-level[data-role="${CSS.escape(roleId)}"]`);
        const default_level = defSelect ? defSelect.value : "hidden";

        const visibility = {};
        box.querySelectorAll(`.role-id-level[data-role="${CSS.escape(roleId)}"]`).forEach((sel) => {
          visibility[sel.dataset.id] = sel.value;
        });

        await ctx.putJSON(`/admin/roles/${encodeURIComponent(roleId)}`, {
          label: roleObj.label,
          description: roleObj.description,
          default_level,
          visibility,
        });
        flash(btn);
      });
    });

    // Delete role handler
    box.querySelectorAll(".del-role-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const roleId = btn.dataset.role;
        const resp = await fetch(`${window.__dash.apiBase}/admin/roles/${encodeURIComponent(roleId)}`, {
          method: "DELETE",
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          alert(`Could not delete role: ${err.detail || resp.status}`);
          return;
        }
        await Promise.all([loadRolesMatrix(), loadUserRoles()]);
      });
    });
  }

  // Add role handler
  el.querySelector("#add-role-btn").addEventListener("click", async (e) => {
    const idInput = el.querySelector("#new-role-id");
    const labelInput = el.querySelector("#new-role-label");
    const descInput = el.querySelector("#new-role-desc");
    const roleId = idInput.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    const label = labelInput.value.trim();
    if (!roleId || !label) return;

    await ctx.putJSON(`/admin/roles/${encodeURIComponent(roleId)}`, {
      label,
      description: descInput.value.trim(),
      default_level: "hidden",
      visibility: {},
    });
    idInput.value = "";
    labelInput.value = "";
    descInput.value = "";
    flash(e.currentTarget, "Added");
    await Promise.all([loadRolesMatrix(), loadUserRoles()]);
  });

  // ---------------- User role assignments ----------------
  async function loadUserRoles() {
    const rows = await ctx.getJSON("/admin/user-roles");
    const box = el.querySelector("#user-roles-list");

    box.innerHTML = rows.length
      ? table(
          [
            { label: "User", sort: "user_id", render: (r) => `<span class="mono">${esc(r.user_id)}</span>` },
            {
              label: "Assigned role",
              sort: "role_id",
              render: (r) => {
                const roleObj = cachedRoles.find((c) => c.role_id === r.role_id);
                return `<span class="chip chip--neutral">${icon("badge", "icon--xs")}${esc(roleObj ? roleObj.label : r.role_id)}</span>`;
              },
            },
            {
              label: "",
              render: (r) => `<button class="btn btn--sm ur-remove" type="button" data-user="${esc(r.user_id)}">Remove</button>`,
            },
          ],
          rows,
        )
      : emptyState("No user roles assigned.", "All users without assignments are fully restricted.");

    box.querySelectorAll(".ur-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const userId = btn.dataset.user;
        await ctx.putJSON(`/admin/user-roles/${encodeURIComponent(userId)}`, { role_id: null });
        await loadUserRoles();
      });
    });
  }

  el.querySelector("#ur-save").addEventListener("click", async (e) => {
    const userId = el.querySelector("#ur-user").value.trim();
    const roleId = el.querySelector("#ur-role").value;
    if (!userId || !roleId) return;

    await ctx.putJSON(`/admin/user-roles/${encodeURIComponent(userId)}`, { role_id: roleId });
    el.querySelector("#ur-user").value = "";
    flash(e.currentTarget, "Assigned");
    await loadUserRoles();
  });

  // ---------------- Legacy overrides ----------------
  async function loadOverrides() {
    const rows = await ctx.getJSON("/admin/users");
    el.querySelector("#overrides").innerHTML = rows.length
      ? table(
          [
            { label: "User", sort: "user_id", render: (r) => `<span class="mono">${esc(r.user_id)}</span>` },
            {
              label: "Unredacted",
              render: (r) =>
                r.allow_unredacted
                  ? `<span class="chip chip--redact">${icon("lock_open", "icon--xs")}Override granted</span>`
                  : `<span class="chip chip--allow">${icon("lock", "icon--xs")}Restricted</span>`,
            },
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

  // ---------------- Reset activity data ----------------
  const confirmInput = el.querySelector("#reset-confirm");
  const resetBtn = el.querySelector("#reset-btn");
  confirmInput.addEventListener("input", () => (resetBtn.disabled = confirmInput.value.trim() !== "RESET"));
  resetBtn.addEventListener("click", async () => {
    resetBtn.disabled = true;
    try {
      const resp = await fetch(`${window.__dash.apiBase}/admin/reset`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ confirm: confirmInput.value.trim() }),
      });
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

  await Promise.all([loadThresholds(), loadIdentifierRules(), loadRolesMatrix(), loadUserRoles(), loadOverrides()]);
  return { refresh: null, destroy() {} };
}
