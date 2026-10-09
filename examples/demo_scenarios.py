"""SWE#1 Day2 #11: the 3 canonical demo-script scenarios (docs/HACKATHON_PLAN.md
"Demo Script Coverage"; same texts as governance_api/tests/test_demo_scenarios.py)
run through BOTH integration paths, for real:

  * LangChain single-agent -- a `langchain.agents.create_agent` loop with
    `GovernanceCallbackHandler` attached (per-tool-call tool-check + per-turn
    outbound compliance-check).
  * LangGraph multi-agent -- a compiled orchestrator -> worker graph, the
    orchestrator wrapped with `@governed_node` and the worker retrofitted with
    `wrap_graph_nodes`, the worker's tool wrapped with `@governed_tool`.

The three scenarios, per path:
  1. Benign action succeeds   -- clean text, tool allowed, score stays 100.
  2. Violation caught         -- PHI in the output is detected, receipted, and
                                 costs the offending agent -20 (and ONLY it).
  3. Out-of-scope action denied -- the same violating flow repeated until the
                                 now-degraded agent is denied, with an explicit
                                 reason, and the tool body never runs.

After each scenario the script reads `/dashboard/session/{id}` -- the same
endpoint the dashboard UI polls -- and asserts the score, violations and
denials landed on the right `agent_id`. The "model" is a deterministic
`ScriptedChatModel` (no API key); what's under test is the governance wiring.

Scenario 3 repeats the violating flow until governance denies (rather than a
hard-coded count) because the point at which `sql_query_tool` is denied depends
on its admin-editable threshold (75 as seeded, 60 if unseeded).

Redaction, honestly: both of these paths DETECT, receipt and score the leak, but
neither rewrites the leaked text the agent/graph carries forward -- only the
reverse proxy does (docs/MOCKED_VS_PRODUCTION.md). The script prints the
governance decision's `cleaned_text` where the API returns one.

Run (repo root, in the project venv):
  python examples/demo_scenarios.py          # in-process governance_api, throwaway DB
  python examples/demo_scenarios.py --live   # a running governance_api, so the
                                             # dashboard shows these sessions
`--live` targets $GOVERNANCE_API_URL (default http://localhost:8001).
"""
import argparse
import atexit
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(_REPO_ROOT))

import httpx  # noqa: E402
from langchain.agents import create_agent  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from example_config import DEFAULT_USER_ID  # noqa: E402
from governance_sdk.governance_sdk import decorators as sdk_decorators  # noqa: E402
from governance_sdk.governance_sdk.client import GovernanceClient  # noqa: E402
from governance_sdk.governance_sdk.decorators import governed_node, governed_tool  # noqa: E402
from governance_sdk.governance_sdk.integrations.langchain_callback import GovernanceCallbackHandler  # noqa: E402
from governance_sdk.governance_sdk.integrations.langgraph_wrapper import wrap_graph_nodes  # noqa: E402
from langchain_single_agent import ScriptedChatModel  # noqa: E402
from shared.identity import new_session_id  # noqa: E402

TOOL_ID = "sql_query_tool"
BENIGN_TEXT = "The weather today is pleasant and the clinic is open as usual."
PHI_TEXT = "Patient phone is 555-123-4567"
PHI_VALUE = "555-123-4567"
PHI_IDENTIFIER = "phone_number"
MAX_ROUNDS = 6  # scenario 3 gives up (and fails) if nothing is denied by then

TOOL_CHECK = "/governance/tool-check"
COMPLIANCE_CHECK = "/governance/compliance-check"
HANDOFF_CHECK = "/governance/handoff-check"


# -- helpers ------------------------------------------------------------------


def _expect(label, actual, expected):
    ok = actual == expected
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
    assert ok, f"{label}: expected {expected!r}, got {actual!r}"


def _ensure(label, condition, detail=""):
    print(f"    [{'PASS' if condition else 'FAIL'}] {label}")
    assert condition, f"{label} {detail}".strip()


class _Tap(GovernanceClient):
    """A GovernanceClient that remembers every (path, payload, response), so a
    scenario can assert on the actual decision the API returned (receipt id,
    verdict, cleaned_text, reason), not just on the resulting score."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def _post(self, path, payload):
        response = super()._post(path, payload)
        self.calls.append((path, payload, response))
        return response

    def responses(self, path, agent_id):
        return [r for p, payload, r in self.calls if p == path and payload["identity"]["agent_id"] == agent_id]


class Demo:
    """One session on one integration path: three scenarios, one identity
    each, read back through the dashboard endpoint."""

    def __init__(self, http):
        self.http = http  # TestClient (in-process) or httpx.Client (live) -- same .get/.post
        self.gov = _Tap(client=http)
        self.session_id = new_session_id()

    def identity(self, agent_id, parent_agent_id=None):
        return {
            "user_id": DEFAULT_USER_ID,
            "session_id": self.session_id,
            "agent_id": agent_id,
            "parent_agent_id": parent_agent_id,
        }

    def row(self, agent_id):
        """This agent's row in the dashboard's session view."""
        agents = self.http.get(f"/dashboard/session/{self.session_id}").json()["agents"]
        row = next((a for a in agents if a["agent_id"] == agent_id), None)
        assert row is not None, f"dashboard has no row for agent_id={agent_id!r} in {self.session_id}"
        return row


@contextlib.contextmanager
def _sdk_client(gov):
    """`governed_tool`/`governed_node` read a module-level singleton client
    (the callback handler takes one in its constructor) -- point it at this
    demo's client for the duration, then put it back."""
    previous = sdk_decorators._client
    sdk_decorators._client = gov
    try:
        yield
    finally:
        sdk_decorators._client = previous


# -- LangChain single-agent path -----------------------------------------------

_TOOL_TURN = AIMessage(content="", tool_calls=[{"name": TOOL_ID, "args": {"query": "x"}, "id": "call_1"}])


def _run_lc_agent(demo, identity, tool_result, final_text, ran):
    """One real create_agent loop: call the tool, then answer with `final_text`.
    Returns the final answer; raises PermissionError if governance denies the
    tool call. Each time the tool BODY executes, `ran` gets an entry -- the
    caller owns the list so it's still readable when the run raises."""

    @tool(TOOL_ID)
    def sql_query_tool(query: str) -> str:
        """Run a read-only patient lookup."""
        ran.append(query)
        return tool_result

    agent = create_agent(
        ScriptedChatModel(responses=[_TOOL_TURN, AIMessage(content=final_text)]), tools=[sql_query_tool]
    )
    handler = GovernanceCallbackHandler(identity=identity, client=demo.gov)
    result = agent.invoke({"messages": [HumanMessage(content="look up the patient")]}, config={"callbacks": [handler]})
    return result["messages"][-1].content


def lc_benign(demo):
    agent_id = "lc_benign"
    print(f"  1. benign action succeeds  (agent_id={agent_id})")
    ran = []
    answer = _run_lc_agent(demo, demo.identity(agent_id), "no sensitive data here", BENIGN_TEXT, ran)

    _expect("tool body ran", len(ran), 1)
    _expect("final answer", answer, BENIGN_TEXT)
    tool_check = demo.gov.responses(TOOL_CHECK, agent_id)[0]
    _ensure("tool-check allowed, with a receipt", tool_check["allowed"] is True and bool(tool_check["receipt_id"]))
    _expect("compliance verdicts", [r["verdict"] for r in demo.gov.responses(COMPLIANCE_CHECK, agent_id)], ["allow"])
    row = demo.row(agent_id)
    _expect("dashboard score", row["current_score"], 100.0)
    _expect("dashboard violations / denials", (len(row["violations"]), len(row["denied_calls"])), (0, 0))


def lc_violation(demo):
    agent_id = "lc_violation"
    print(f"  2. violation caught  (agent_id={agent_id})")
    ran = []
    _run_lc_agent(demo, demo.identity(agent_id), PHI_TEXT, PHI_TEXT, ran)

    _expect("tool body ran", len(ran), 1)
    flagged = [r for r in demo.gov.responses(COMPLIANCE_CHECK, agent_id) if r["verdict"] != "allow"]
    _expect("flagged compliance checks", len(flagged), 1)
    _ensure(f"{PHI_IDENTIFIER} named in the violation", PHI_IDENTIFIER in flagged[0]["violations"])
    _ensure("decision's cleaned_text has no raw PHI", PHI_VALUE not in flagged[0]["cleaned_text"])
    print(f"         governance decision: {flagged[0]['verdict']} -> {flagged[0]['cleaned_text']!r}")
    row = demo.row(agent_id)
    _expect("dashboard score", row["current_score"], 80.0)
    _expect("dashboard violations", len(row["violations"]), 1)
    _expect("dashboard denials", len(row["denied_calls"]), 0)


def lc_denied(demo):
    agent_id = "lc_denied"
    print(f"  3. out-of-scope action denied  (agent_id={agent_id})")
    identity = demo.identity(agent_id)
    completed, denial, ran = 0, None, []
    for _ in range(MAX_ROUNDS):
        ran = []
        try:
            _run_lc_agent(demo, identity, PHI_TEXT, PHI_TEXT, ran)
        except PermissionError as error:
            denial = error
            break
        completed += 1
    _ensure("the repeating agent was eventually denied", denial is not None, f"(no denial in {MAX_ROUNDS} rounds)")
    _ensure("it degraded through its own violations first", completed >= 1, f"(completed={completed})")
    print(f"         denied after {completed} violating run(s): {denial}")
    _ensure("denial is a real authority decision, not an outage", "governance_api_unreachable" not in str(denial))

    last_tool_check = demo.gov.responses(TOOL_CHECK, agent_id)[-1]
    _expect("tool-check allowed", last_tool_check["allowed"], False)
    _expect("tool body runs in the denied round", len(ran), 0)
    row = demo.row(agent_id)
    _expect("dashboard score", row["current_score"], 100.0 - 20 * completed)
    _expect("dashboard violations", len(row["violations"]), completed)
    _expect("dashboard denials", len(row["denied_calls"]), 1)
    _ensure("dashboard's denial reason is the one the agent saw", row["denied_calls"][0]["reason"] in str(denial))
    _ensure("reason is explicit", "below required" in row["denied_calls"][0]["reason"])


def run_langchain_path(http):
    demo = Demo(http)
    print(f"\n=== LangChain single-agent path  (session {demo.session_id}) ===")
    lc_benign(demo)
    lc_violation(demo)
    lc_denied(demo)
    return demo


# -- LangGraph multi-agent path --------------------------------------------------


def _lg_ids(name):
    return f"lg_{name}_orchestrator", f"lg_{name}_worker"


def _run_lg_graph(demo, orchestrator_id, worker_id, tool_result, ran):
    """One real compiled orchestrator -> worker graph. Returns the final state;
    raises PermissionError if governance denies the tool call or blocks a
    handoff. `ran` gets an entry each time the worker's tool BODY executes (the
    caller owns the list so it's still readable when the run raises)."""
    orchestrator = demo.identity(orchestrator_id)
    worker = demo.identity(worker_id, parent_agent_id=orchestrator_id)

    @governed_tool(TOOL_ID, identity_fn=lambda state: worker)
    def sql_query(state):
        ran.append(1)
        return tool_result

    @governed_node(identity_fn=lambda state: orchestrator)
    def orchestrator_node(state):
        return {**state, "plan": "ask the sql agent for the record"}

    def worker_node(state):  # undecorated on purpose: governance is retrofitted below
        return {**state, "sql_result": sql_query(state)}

    graph = StateGraph(dict)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("worker", worker_node)
    graph.add_edge(START, "orchestrator")
    graph.add_edge("orchestrator", "worker")
    graph.add_edge("worker", END)
    wrap_graph_nodes(graph, ["worker"], lambda state: worker)

    with _sdk_client(demo.gov):
        return graph.compile().invoke({"task": "find the patient"})


def lg_benign(demo):
    orchestrator_id, worker_id = _lg_ids("benign")
    print(f"  1. benign action succeeds  (orchestrator={orchestrator_id}, worker={worker_id})")
    ran = []
    state = _run_lg_graph(demo, orchestrator_id, worker_id, BENIGN_TEXT, ran)

    _expect("worker's tool body ran", len(ran), 1)
    _expect("worker's result reached the final state", state["sql_result"], BENIGN_TEXT)
    tool_check = demo.gov.responses(TOOL_CHECK, worker_id)[0]
    _ensure("tool-check allowed, with a receipt", tool_check["allowed"] is True and bool(tool_check["receipt_id"]))
    for agent_id in (orchestrator_id, worker_id):
        handoffs = demo.gov.responses(HANDOFF_CHECK, agent_id)
        _ensure(f"{agent_id}: handoff allowed", len(handoffs) == 1 and handoffs[0]["allowed"] is True)
        row = demo.row(agent_id)
        _expect(f"{agent_id}: dashboard score / violations / denials",
                (row["current_score"], len(row["violations"]), len(row["denied_calls"])), (100.0, 0, 0))


def lg_violation(demo):
    orchestrator_id, worker_id = _lg_ids("violation")
    print(f"  2. violation caught  (orchestrator={orchestrator_id}, worker={worker_id})")
    ran = []
    _run_lg_graph(demo, orchestrator_id, worker_id, PHI_TEXT, ran)

    _expect("worker's tool body ran", len(ran), 1)
    flagged = [r for r in demo.gov.responses(HANDOFF_CHECK, worker_id) if r["verdict"] != "allow"]
    _expect("flagged worker handoffs", len(flagged), 1)
    _ensure("flagged handoff was still allowed through (score above threshold)", flagged[0]["allowed"] is True)
    print(f"         governance decision on the worker's handoff: {flagged[0]['verdict']}")
    worker_row, orchestrator_row = demo.row(worker_id), demo.row(orchestrator_id)
    _expect("worker: dashboard score", worker_row["current_score"], 80.0)
    _expect("worker: dashboard score history", worker_row["history"], [{"signal": "phi_in_output", "delta": -20.0}])
    _expect("orchestrator: dashboard score / history (penalty hit only the leaker)",
            (orchestrator_row["current_score"], orchestrator_row["history"]), (100.0, []))
    if not worker_row["violations"]:
        # handoff-check writes an `authority` receipt only, never a `compliance` one, and the
        # dashboard's violations table is built from compliance receipts.
        print("         NOTE: the dashboard's violations table has no row for this leak (score + history only)"
              " -- see docs/MOCKED_VS_PRODUCTION.md")


def lg_denied(demo):
    orchestrator_id, worker_id = _lg_ids("denied")
    print(f"  3. out-of-scope action denied  (orchestrator={orchestrator_id}, worker={worker_id})")
    completed, denial, ran = 0, None, []
    for _ in range(MAX_ROUNDS):
        ran = []
        try:
            _run_lg_graph(demo, orchestrator_id, worker_id, PHI_TEXT, ran)
        except PermissionError as error:
            denial = error
            break
        completed += 1
    _ensure("the repeating worker was eventually denied", denial is not None, f"(no denial in {MAX_ROUNDS} rounds)")
    _ensure("it degraded through its own violations first", completed >= 1, f"(completed={completed})")
    print(f"         denied after {completed} violating run(s): {denial}")
    _ensure("denial is a real authority decision, not an outage", "governance_api_unreachable" not in str(denial))
    if str(denial).startswith("governance denied tool"):  # vs. a session-level handoff block, after the tool already ran
        _expect("tool body runs in the denied round", len(ran), 0)

    worker_row, orchestrator_row = demo.row(worker_id), demo.row(orchestrator_id)
    penalties = [h for h in worker_row["history"] if h["signal"] == "phi_in_output"]
    _ensure("worker's score history has (at least) its completed runs' leaks", len(penalties) >= completed)
    _expect("worker: score tracks its history", worker_row["current_score"], 100.0 + sum(h["delta"] for h in worker_row["history"]))
    _expect("worker: dashboard denials", len(worker_row["denied_calls"]), 1)
    _ensure("worker: dashboard's denial reason is the one the graph saw", worker_row["denied_calls"][0]["reason"] in str(denial))
    _expect("orchestrator: never denied, never penalized",
            (orchestrator_row["current_score"], len(orchestrator_row["violations"]), len(orchestrator_row["denied_calls"])),
            (100.0, 0, 0))


def run_langgraph_path(http):
    demo = Demo(http)
    print(f"\n=== LangGraph multi-agent path  (session {demo.session_id}) ===")
    lg_benign(demo)
    lg_violation(demo)
    lg_denied(demo)  # last on purpose: a degraded worker blocks later handoffs session-wide
    return demo


# -- entry point -----------------------------------------------------------------


def _in_process_http():
    """The real governance_api app, seeded exactly like `scripts/init_db.py`
    seeds a live one, on a throwaway SQLite file -- never the repo's
    governance.db. DATABASE_URL has to be set before shared.db is imported."""
    tmp = tempfile.mkdtemp(prefix="demo_scenarios_")
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'demo.db'}"
    os.environ.setdefault("RECEIPT_SIGNING_SECRET", "demo-signing-secret")
    sys.path.insert(0, str(_REPO_ROOT / "governance_api"))
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

    from fastapi.testclient import TestClient

    import init_db
    import main as governance_main  # governance_api/main.py

    with contextlib.redirect_stdout(io.StringIO()):
        init_db.main()
    return TestClient(governance_main.app)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--live",
        action="store_true",
        help="drive a running governance_api ($GOVERNANCE_API_URL, default http://localhost:8001) so the "
        "dashboard shows these sessions, instead of an in-process one",
    )
    args = parser.parse_args(argv)

    if args.live:
        base_url = os.getenv("GOVERNANCE_API_URL", "http://localhost:8001")
        print(f"driving the live governance_api at {base_url}")
        http = httpx.Client(base_url=base_url, timeout=10.0)
    else:
        print("driving an in-process governance_api on a throwaway DB (use --live for a running stack)")
        http = _in_process_http()

    sessions = [run_langchain_path(http).session_id, run_langgraph_path(http).session_id]
    print("\n=== All 3 demo scenarios verified through both paths ===")
    print("dashboard session ids: " + ", ".join(sessions))


if __name__ == "__main__":
    main()
