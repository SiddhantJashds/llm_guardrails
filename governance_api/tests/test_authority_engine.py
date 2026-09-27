"""Authority Engine: default score, monotonic reduction, delegation capping.

These three properties are the entire point of the "earned authority" model
(docs/HACKATHON_PLAN.md) -- if any of them regress silently, the runtime's
core differentiator is broken even though everything still "runs".
"""
from authority.engine import AuthorityEngine, DEFAULT_SCORE


def test_new_agent_starts_at_default_score(db_session):
    engine = AuthorityEngine(db_session)
    state = engine.get_or_create("agent_a", "sess1", parent_agent_id=None)
    assert state.current_score == DEFAULT_SCORE


def test_apply_signal_decreases_score(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("agent_a", "sess1", parent_agent_id=None)
    state = engine.apply_signal("agent_a", "phi_in_output")
    assert state.current_score < DEFAULT_SCORE


def test_score_never_increases_across_repeated_signals(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("agent_a", "sess1", parent_agent_id=None)
    scores = [DEFAULT_SCORE]
    for signal in ["phi_in_output", "tool_out_of_scope", "phi_in_output"]:
        state = engine.apply_signal("agent_a", signal)
        scores.append(state.current_score)
    assert all(later <= earlier for earlier, later in zip(scores, scores[1:]))


def test_score_floors_at_zero_not_negative(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("agent_a", "sess1", parent_agent_id=None)
    for _ in range(20):
        state = engine.apply_signal("agent_a", "prompt_injection_detected")  # -25 each
    assert state.current_score == 0.0


def test_delegation_caps_child_at_parents_current_score(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("parent_agent", "sess1", parent_agent_id=None)
    engine.apply_signal("parent_agent", "phi_in_output")  # parent now at 80
    engine.apply_signal("parent_agent", "phi_in_output")  # parent now at 60

    child = engine.get_or_create("child_agent", "sess1", parent_agent_id="parent_agent")
    assert child.current_score == 60.0


def test_delegation_from_undegraded_parent_uses_default(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("parent_agent", "sess1", parent_agent_id=None)
    child = engine.get_or_create("child_agent", "sess1", parent_agent_id="parent_agent")
    assert child.current_score == DEFAULT_SCORE


def test_check_threshold(db_session):
    engine = AuthorityEngine(db_session)
    engine.get_or_create("agent_a", "sess1", parent_agent_id=None)
    assert engine.check_threshold("agent_a", required_threshold=75.0) is True
    engine.apply_signal("agent_a", "prompt_injection_detected")  # -25 -> 75
    engine.apply_signal("agent_a", "phi_in_output")  # -20 -> 55
    assert engine.check_threshold("agent_a", required_threshold=75.0) is False
