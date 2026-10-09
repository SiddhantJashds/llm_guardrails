// Headless Chrome DevTools smoke check for the governance console.
// Connects to Chrome on port 9333, navigates to the dashboard, and verifies
// that views render cleanly without console errors.

const CDP_PORT = process.env.CDP_PORT || 9333;
const DASHBOARD_URL = process.env.DASHBOARD_URL || "http://localhost:8081/?api=http://localhost:8001";

async function run() {
  console.log(`[smoke] Connecting to Chrome DevTools on port ${CDP_PORT}...`);
  const targetsResp = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`);
  const targets = await targetsResp.json();
  const page = targets.find((t) => t.type === "page");
  if (!page) {
    throw new Error("No page target found in Chrome DevTools.");
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 1;
  const pending = new Map();
  const errors = [];

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const msgId = id++;
      pending.set(msgId, { resolve, reject });
      ws.send(JSON.stringify({ id: msgId, method, params }));
    });
  }

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message));
      else resolve(msg.result);
    } else if (msg.method === "Runtime.exceptionThrown") {
      const desc = msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text;
      errors.push(desc);
      console.error(`[smoke browser error] ${desc}`);
    } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
      const args = msg.params.args.map((a) => a.value || a.description).join(" ");
      errors.push(args);
      console.error(`[smoke console.error] ${args}`);
    }
  };

  await send("Page.enable");
  await send("Runtime.enable");

  console.log(`[smoke] Navigating to ${DASHBOARD_URL}#/admin ...`);
  await send("Page.navigate", { url: `${DASHBOARD_URL}#/admin` });

  // Wait for rendering
  await new Promise((r) => setTimeout(r, 2500));

  async function evaluate(expression) {
    const res = await send("Runtime.evaluate", { expression, returnByValue: true });
    return res.result?.value;
  }

  console.log("[smoke] Inspecting Policy settings DOM...");
  const adminTitle = await evaluate("document.querySelector('h1')?.textContent");
  console.log(`[smoke] Title: "${adminTitle}"`);

  const packButtons = await evaluate("document.querySelectorAll('#pack-toggle button').length");
  console.log(`[smoke] Pack toggle buttons found: ${packButtons}`);

  const identifierRules = await evaluate("document.querySelectorAll('#identifier-rules tr').length");
  console.log(`[smoke] Identifier rule rows: ${identifierRules}`);

  const rolesMatrixRows = await evaluate("document.querySelectorAll('#roles-matrix tr').length");
  console.log(`[smoke] Roles matrix rows: ${rolesMatrixRows}`);

  const userRolesBox = await evaluate("Boolean(document.querySelector('#user-roles-list'))");
  console.log(`[smoke] User roles box present: ${userRolesBox}`);

  console.log("[smoke] Checking test console toggles...");
  const restoreSenderToggle = await evaluate("Boolean(document.querySelector('#chat-restore-sender'))");
  const requestUnredactedToggle = await evaluate("Boolean(document.querySelector('#chat-request-unredacted'))");
  console.log(`[smoke] chat-restore-sender toggle: ${restoreSenderToggle}`);
  console.log(`[smoke] chat-request-unredacted toggle: ${requestUnredactedToggle}`);

  console.log("[smoke] Checking sample cases count...");
  await evaluate("document.querySelector('[data-tab=\"cases\"]')?.click()");
  await new Promise((r) => setTimeout(r, 800));
  const casesCount = await evaluate("document.querySelectorAll('.case').length");
  console.log(`[smoke] Total sample cases rendered: ${casesCount}`);

  console.log("[smoke] Running all non-model sample cases...");
  await evaluate("document.querySelector('#cases-run-all')?.click()");

  // Wait for all 29 non-model cases to complete
  let passedSummary = "";
  for (let i = 0; i < 45; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    passedSummary = await evaluate("document.querySelector('#cases-summary')?.textContent || ''");
    const isRunning = await evaluate("Boolean(document.querySelector('.case [data-case] .chip--neutral'))");
    if (passedSummary.startsWith("29 of 29") || (passedSummary && !isRunning && parseInt(passedSummary, 10) >= 29)) {
      break;
    }
  }
  console.log(`[smoke] Sample cases summary: "${passedSummary}"`);

  const failCards = await evaluate("document.querySelectorAll('.chip--FAIL').length");
  if (failCards > 0) {
    console.error(`[smoke FAIL] ${failCards} sample cases failed.`);
    process.exit(1);
  }

  ws.close();

  if (errors.length > 0) {
    console.error(`[smoke FAIL] Encountered ${errors.length} browser errors.`);
    process.exit(1);
  }

  if (!adminTitle || packButtons !== 2 || identifierRules === 0 || rolesMatrixRows === 0 || !restoreSenderToggle || casesCount < 30) {
    console.error("[smoke FAIL] Missing expected UI components.");
    process.exit(1);
  }

  console.log("[smoke PASS] All checks passed successfully!");
}

run().catch((err) => {
  console.error(`[smoke ERROR] ${err.message}`);
  process.exit(1);
});
