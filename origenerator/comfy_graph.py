"""Traversal helpers for ComfyUI API-format prompt graphs.

A prompt graph is ``{node_id: {"class_type": str, "inputs": {...}}}`` where an
input can be a link ``[source_node_id, slot]``. The importer reads prompts out
of these graphs; replay writes new prompts into them — both need to locate the
same nodes, so that logic lives here once.
"""

_COND_NODES = ("WanImageToVideo", "WanFirstLastFrameToVideo")


def follow(graph: dict, ref) -> dict | None:
    """Resolve an input link ``[node_id, slot]`` to its source node, or None."""
    if isinstance(ref, list) and ref:
        return graph.get(str(ref[0]))
    return None


def conditioning_node(graph: dict) -> dict | None:
    """The Wan video conditioning node (i2v/flf2v), if the graph has one."""
    return next(
        (n for n in graph.values() if n.get("class_type") in _COND_NODES),
        None,
    )


def clip_prompt_nodes(graph: dict):
    """Return the (positive, negative) CLIPTextEncode nodes.

    Found structurally via a Wan conditioning node's links when present (which
    is title-independent), otherwise by CLIPTextEncode node titles.
    """
    cond = conditioning_node(graph)
    if cond:
        ci = cond.get("inputs", {})
        return follow(graph, ci.get("positive")), follow(graph, ci.get("negative"))
    positive = negative = None
    for node in graph.values():
        if node.get("class_type") == "CLIPTextEncode":
            title = node.get("_meta", {}).get("title", "")
            if "Negative" in title:
                negative = node
            elif positive is None:
                positive = node
    return positive, negative
