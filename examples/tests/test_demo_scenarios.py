"""SWE#1 Day2 #11: the demo script's 3 scenarios, each through both the
LangChain single-agent and LangGraph multi-agent paths, against the real
governance_api. The scenario functions assert their own outcomes (including
dashboard attribution); these tests just run each one on a fresh session.
"""
import demo_scenarios as demo
import pytest


def test_langchain_benign_action_succeeds(demo_http):
    demo.lc_benign(demo.Demo(demo_http))


def test_langchain_violation_is_caught_and_attributed(demo_http):
    demo.lc_violation(demo.Demo(demo_http))


def test_langchain_repeating_agent_is_denied_with_an_explicit_reason(demo_http):
    demo.lc_denied(demo.Demo(demo_http))


def test_langgraph_benign_action_succeeds(demo_http):
    demo.lg_benign(demo.Demo(demo_http))


def test_langgraph_violation_is_caught_and_attributed_to_the_leaking_agent(demo_http):
    demo.lg_violation(demo.Demo(demo_http))


def test_langgraph_repeating_worker_is_denied_with_an_explicit_reason(demo_http):
    demo.lg_denied(demo.Demo(demo_http))


def test_full_script_runs_both_paths_in_order(demo_http):
    demo.run_langchain_path(demo_http)
    demo.run_langgraph_path(demo_http)


@pytest.mark.xfail(
    strict=True,
    reason="handoff-check writes only an `authority` receipt, so a leak it detects and penalizes never reaches the "
    "dashboard's compliance-violations table (it shows only as a score drop). Fix in governance_api/routes/"
    "governance.py::handoff_check (also write a `compliance` receipt) and remove this marker.",
)
def test_langgraph_leak_appears_in_the_dashboards_violations_table(demo_http):
    d = demo.Demo(demo_http)
    orchestrator_id, worker_id = demo._lg_ids("xfail")
    demo._run_lg_graph(d, orchestrator_id, worker_id, demo.PHI_TEXT, [])
    assert len(d.row(worker_id)["violations"]) == 1
