// Fetch wrappers around governance_api's read-only /dashboard/* endpoints
// (and the admin PUTs). The API base can be overridden with ?api=<url>,
// window.GOVERNANCE_API_BASE_URL, or defaults to localhost:8001.
const params = new URLSearchParams(location.search);
export const API_BASE = (params.get("api") || window.GOVERNANCE_API_BASE_URL || "http://localhost:8001").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function url(path, query) {
  const u = new URL(API_BASE + path);
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== "" && v !== false) u.searchParams.set(k, v);
  }
  return u;
}

async function request(method, path, { query, body } = {}) {
  let resp;
  try {
    resp = await fetch(url(path, query), {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, `Can't reach the governance API at ${API_BASE}.`);
  }
  if (!resp.ok) throw new ApiError(resp.status, `${method} ${path} failed with HTTP ${resp.status}.`);
  return resp.json();
}

export const getJSON = (path, query) => request("GET", path, { query });
export const putJSON = (path, body) => request("PUT", path, { body });

// Every field rendered by the dashboard comes from the API, and user_id in
// particular is caller-supplied with no validation by design
// (docs/adr/0005-user-identity-no-auth.md): it can contain anything an
// attacker chooses, and it flows into receipts and from there onto this
// page. Never interpolate API data into HTML without this -- that's a
// stored-XSS hole, not a hypothetical one. Escapes quotes too, so it's safe
// inside attribute values.
export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
