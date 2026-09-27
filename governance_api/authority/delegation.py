"""Delegation capping, kept separate from engine.py so the rule is auditable
and testable on its own (docs/HACKATHON_PLAN.md, SWE#1 Day 2 #8): a sub-agent
spawned by a degraded parent can never start above the parent's current score.
"""
from typing import Optional


def capped_initial_score(default_score: float, parent_current_score: Optional[float]) -> float:
    if parent_current_score is None:
        return default_score
    return min(default_score, parent_current_score)
