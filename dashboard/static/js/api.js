// Thin fetch wrapper around governance_api's read-only /dashboard/* endpoints.
const GOVERNANCE_API_BASE_URL = window.GOVERNANCE_API_BASE_URL || "http://localhost:8001";

// Every field rendered below comes from data the API returns -- reason,
// agent_id, user_id, etc. -- and user_id in particular is caller-supplied
// with no validation by design (docs/adr/0005-user-identity-no-auth.md), so
// it can contain anything an attacker chooses. It can end up in a receipt's
// `reason` field and from there in this dashboard. Never interpolate any of
// it into innerHTML without this -- that's a stored-XSS hole, not a
// hypothetical one.
function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

async function fetchSessionDashboard(sessionId) {
  const resp = await fetch(`${GOVERNANCE_API_BASE_URL}/dashboard/session/${encodeURIComponent(sessionId)}`);
  if (!resp.ok) throw new Error(`session dashboard fetch failed: ${resp.status}`);
  return resp.json();
}

async function fetchUserDashboard(userId) {
  const resp = await fetch(`${GOVERNANCE_API_BASE_URL}/dashboard/user/${encodeURIComponent(userId)}`);
  if (!resp.ok) throw new Error(`user dashboard fetch failed: ${resp.status}`);
  return resp.json();
}
