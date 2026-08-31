"""What a stored ComfyUI graph says about the enhancement that ran.

The row itself is vague. A row the import scan reconstructed keeps the tail's
numbers under the generic names any sampler has — ``steps`` and ``denoise`` — and
says nothing at all about the upscale, so folding it on its params alone would
file the level with a blank settings line and leave the Enhance panel unable to
tell it apart from a level it has not made yet. The graph that ran is exact about
all of it, and it is stored on the row.

Which of the knobs it finds are wanted is the caller's business, so the keys to
keep come in as an argument: this reads a graph and says what is in it. That is
workflow knowledge rather than gallery knowledge — its home is beside the
workflows that write these graphs, which is the first half of the audit's
`E_workflows_gallery_voice/design/002`, and it sits here until a change to that
package can land alongside.

Every step of the read is guarded, because a graph on a row was written by an
older version of this app, by ComfyUI, or by hand.
"""

import json

from origenerator.workflows.base import UPSCALE_MODEL_FACTOR
from origenerator.workflows.detail_parts import detector_part_label


# What each node type of the enhance tail says about the run, given its inputs.
# One entry per node the tail lays down; anything else in the graph is scenery.
_KNOBS_BY_NODE = {
    "CheckpointLoaderSimple": lambda inputs: {"checkpoint": inputs.get("ckpt_name")},
    "UpscaleModelLoader": lambda inputs: {"upscale_model": inputs.get("model_name")},
    # ImageScaleBy holds the fraction of the upscale model's own 4x output the
    # result was taken back down to, so the scale a reader wants is the product.
    "ImageScaleBy": lambda inputs: (
        {"enhance_scale": inputs["scale_by"] * UPSCALE_MODEL_FACTOR}
        if isinstance(inputs.get("scale_by"), (int, float)) else {}
    ),
    "KSampler": lambda inputs: {"enhance_steps": inputs.get("steps"),
                                "enhance_denoise": inputs.get("denoise")},
}

_DETAIL_PASS = "DetailerForEach"


def graph_level_params(row: dict, keys) -> dict:
    """The enhance knobs a row's stored ComfyUI graph gives up, kept to *keys*.

    The upscale model by name, the scale as the fraction of that model's own 4x
    output the result was taken back down to, the sampler's numbers, and the
    detail pass by whether its detector nodes are there at all.
    """
    graph = _graph_of(row)
    found = {}
    for _node_id, inputs, node_type in _nodes_of(graph):
        found.update(_KNOBS_BY_NODE.get(node_type, lambda _inputs: {})(inputs))
    fixes = _detail_fixes(graph)
    if fixes:
        found["enhance_detail_fixes"] = fixes
    return {k: v for k, v in found.items() if v is not None and k in keys}


def _graph_of(row: dict) -> dict:
    """The row's stored graph, or ``{}`` when there is nothing readable there.

    Guarded because a graph on a row was written by an older version of this
    app, by ComfyUI, or by hand.
    """
    try:
        graph = json.loads(row.get("workflow_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return graph if isinstance(graph, dict) else {}


def _nodes_of(graph: dict):
    """``(node_id, inputs, class_type)`` for each thing in *graph* shaped like a
    node, skipping whatever is not."""
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            yield node_id, inputs, node.get("class_type")


def _detail_fixes(graph: dict) -> dict:
    """Each detail pass in the graph as ``part -> denoise``, in the order they
    ran.

    Sorted by node id rather than taken in the graph's own key order, which only
    happens to agree. Each pass says which part it redrew only by way of the
    detector two nodes back, so the part is read off the model that found the
    regions; a pass whose detector cannot be followed names no part and is left
    out.
    """
    passes = sorted(((_node_order(node_id), inputs)
                     for node_id, inputs, node_type in _nodes_of(graph)
                     if node_type == _DETAIL_PASS),
                    key=lambda pair: pair[0])
    fixes = {}
    for _order, inputs in passes:
        segs = _linked_inputs(graph, inputs.get("segs"))
        model = _linked_inputs(graph, segs.get("bbox_detector")).get("model_name")
        denoise = inputs.get("denoise")
        if isinstance(model, str) and isinstance(denoise, (int, float)):
            fixes[detector_part_label(model.rsplit("/", 1)[-1])] = denoise
    return fixes


def _node_order(node_id) -> int:
    """A graph node's id as a number, for reading the order the workflow built
    its nodes in. Non-numeric ids (a hand-authored graph) sort last, together."""
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return 1 << 30


def _linked_inputs(graph: dict, ref) -> dict:
    """The inputs of the node one input links to, or ``{}`` where there is none.

    A ComfyUI link is ``[node_id, output_index]``; anything else on an input is
    a literal.
    """
    if not (isinstance(ref, (list, tuple)) and ref and isinstance(ref[0], (str, int))):
        return {}
    node = graph.get(str(ref[0]))
    inputs = node.get("inputs") if isinstance(node, dict) else None
    return inputs if isinstance(inputs, dict) else {}
