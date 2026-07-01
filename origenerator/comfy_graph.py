"""Traversal helpers for ComfyUI API-format prompt graphs.

A prompt graph is ``{node_id: {"class_type": str, "inputs": {...}}}`` where an
input can be a link ``[source_node_id, slot]``. The importer uses these helpers
to locate the prompt and conditioning nodes when reading a graph's metadata.
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


def _model_source_files(graph: dict, model_ref) -> tuple[str | None, str | None]:
    """Walk a ``model`` link back to its UNET and LoRA source filenames.

    Follows each node's ``model`` input until it reaches a ``UNETLoader``,
    capturing the first ``LoraLoaderModelOnly``'s ``lora_name`` passed on the
    way. Returns ``(unet_name, lora_name)``, either ``None`` if unresolved.
    """
    unet = lora = None
    node = follow(graph, model_ref)
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")
        if class_type == "LoraLoaderModelOnly" and lora is None:
            name = inputs.get("lora_name")
            if isinstance(name, str):
                lora = name
        if class_type == "UNETLoader":
            name = inputs.get("unet_name")
            if isinstance(name, str):
                unet = name
            break
        node = follow(graph, inputs.get("model"))
    return unet, lora


def dual_sampler_model_files(graph: dict) -> dict:
    """The high/low UNET and LoRA filenames a WAN dual-noise graph loaded.

    WAN 2.2's two-stage sampling runs a high-noise ``KSamplerAdvanced``
    (``add_noise`` enabled) then a low-noise one (disabled). Walking each
    sampler's ``model`` input back to its UNET — and any LoRA in between — pairs
    the files with the stage that used them by graph structure, not node-id
    order. Returns whichever of ``unet_high``/``unet_low``/``lora_high``/
    ``lora_low`` it resolves; empty for a graph with no such samplers.
    """
    result: dict = {}
    for suffix, add_noise in (("high", "enable"), ("low", "disable")):
        sampler = next(
            (n for n in graph.values()
             if n.get("class_type") == "KSamplerAdvanced"
             and n.get("inputs", {}).get("add_noise") == add_noise),
            None,
        )
        if sampler is None:
            continue
        unet, lora = _model_source_files(graph, sampler.get("inputs", {}).get("model"))
        if unet:
            result[f"unet_{suffix}"] = unet
        if lora:
            result[f"lora_{suffix}"] = lora
    return result


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
