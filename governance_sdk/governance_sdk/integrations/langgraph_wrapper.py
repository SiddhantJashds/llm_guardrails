"""Helpers for wrapping individual LangGraph nodes.

The graph-level `post_model_hook` alone misses inter-node tool calls (open
question raised in the kickoff meeting) -- this wraps each node directly
instead, so it works regardless of hook granularity in the installed
LangGraph version.
"""
from typing import Callable, List

from ..decorators import governed_node


def wrap_graph_nodes(graph_builder, node_names: List[str], identity_fn: Callable, pack_id: str = "hipaa"):
    """Re-wrap already-added nodes on a LangGraph StateGraph builder, so a
    graph you didn't author (e.g. handed to you by another team) gets
    governance retrofitted without rewriting its node definitions.

    Verified against the installed LangGraph API (docs/adr/0012):
    `graph_builder.nodes[name]` is a `StateNodeSpec` whose `.runnable` is a
    `RunnableCallable` wrapping the original function at `.runnable.func` --
    NOT directly callable itself (confirmed: calling it raises
    `TypeError: 'RunnableCallable' object is not callable`; it only exposes
    `.invoke()`/`.ainvoke()`). The original code assigned a plain wrapped
    function straight to `.runnable`, which would have broken the moment
    anyone actually ran the compiled graph.

    The fix: mutate `.func` on the EXISTING `RunnableCallable` in place,
    rather than replacing `.runnable` wholesale -- this preserves whatever
    config langgraph attached (tags, retry/cache policy, etc.) and is
    confirmed (by actually compiling and invoking a graph) to take effect
    through the real compiled-graph executor, not just a direct `.invoke()`
    call on the node spec.
    """
    for name in node_names:
        spec = graph_builder.nodes[name]
        original_fn = spec.runnable.func
        spec.runnable.func = governed_node(identity_fn, pack_id)(original_fn)
    return graph_builder
