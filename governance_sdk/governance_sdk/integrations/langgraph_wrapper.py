"""Helpers for wrapping individual LangGraph nodes.

The graph-level `post_model_hook` alone misses inter-node tool calls (open
question raised in the kickoff meeting) -- this wraps each node directly
instead, so it works regardless of hook granularity in the installed
LangGraph version.
"""
from typing import Callable, List

from ..decorators import governed_node


def wrap_graph_nodes(graph_builder, node_names: List[str], identity_fn: Callable, pack_id: str = "hipaa"):
    """Re-wrap already-added nodes on a LangGraph StateGraph builder.

    TODO: verify the exact attribute path against the installed langgraph
    version -- this sketches the intent (wrap each node's callable), not a
    tested API surface.
    """
    for name in node_names:
        node_fn = graph_builder.nodes[name].runnable
        graph_builder.nodes[name].runnable = governed_node(identity_fn, pack_id)(node_fn)
    return graph_builder
