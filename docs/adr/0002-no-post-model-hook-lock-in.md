# 0002. Wrap LangGraph nodes directly instead of relying on `post_model_hook`

Status: Accepted
Date: 2026-09-27

## Context

The kickoff meeting proposed LangGraph's `post_model_hook` as the interception point for multi-agent flows, since it requires no code changes beyond one config line. Govind raised an unresolved concern in that same meeting: `post_model_hook` fires at the whole-graph level, not per node — so it would miss tool calls and agent-to-agent handoffs that happen *between* nodes, which is exactly what objectives #3 and #4 require intercepting (every tool call, every handoff, independently evaluated).

## Decision

`governance_sdk` does not depend on `post_model_hook`. Instead, `governance_sdk/governance_sdk/decorators.py`'s `governed_node` wraps each node's callable directly (`governance_sdk/governance_sdk/integrations/langgraph_wrapper.py`), so every node's output is checked before the handoff to the next node, regardless of what graph-level hooks the installed LangGraph version does or doesn't expose. `post_model_hook` may still be used *in addition*, if a team finds it useful for whole-graph-level checks — it's just not the primary or only interception mechanism.

## Consequences

The integration surface is one line per node (`@governed_node`) rather than one line per graph, which is a slightly bigger integration footprint than originally hoped — but it's the only way to guarantee objective #4's "intercept every agent-to-agent handoff" claim actually holds. `governance_sdk/governance_sdk/integrations/langgraph_wrapper.py`'s `wrap_graph_nodes` helper is still a TODO against the exact installed LangGraph version's `StateGraph` internals — this needs verification (the same verification the kickoff meeting's action item asked for) before Day 2 work depends on it.
