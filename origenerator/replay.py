"""Re-run a captured ComfyUI prompt graph with a few overridden fields.

Every generated/imported row stores the exact API graph that produced it
(``workflow_json``). Generic replay resubmits that graph after swapping in a new
prompt / seed / input image, so any past generation can be reproduced or nudged
without a hand-coded workflow template. Overrides are best-effort: a field the
graph doesn't express (e.g. an input image in a video-to-video workflow) is left
untouched.
"""
from copy import deepcopy
from pathlib import Path

from origenerator.comfy_graph import clip_prompt_nodes

_VIDEO_LOADERS = ("VHS_LoadVideoPath", "VHS_LoadVideo", "LoadVideo")


def apply_overrides(graph: dict, *, positive=None, negative=None,
                    seed=None, input_image=None) -> dict:
    """Return a deep copy of *graph* with the given fields overridden in place."""
    g = deepcopy(graph)

    # Prompts: WanVideoTextEncode carries both on one node; otherwise the
    # positive/negative CLIPTextEncode nodes.
    wvte = [n for n in g.values() if n.get("class_type") == "WanVideoTextEncode"]
    if wvte:
        for node in wvte:
            if positive is not None:
                node.setdefault("inputs", {})["positive_prompt"] = positive
            if negative is not None:
                node.setdefault("inputs", {})["negative_prompt"] = negative
    else:
        pos_node, neg_node = clip_prompt_nodes(g)
        if positive is not None and pos_node is not None:
            pos_node.setdefault("inputs", {})["text"] = positive
        if negative is not None and neg_node is not None:
            neg_node.setdefault("inputs", {})["text"] = negative

    if input_image is not None:
        for node in g.values():
            if node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = input_image

    if seed is not None:
        for node in g.values():
            inp = node.get("inputs", {})
            # Leave an explicit refine pass (add_noise disabled) on its own seed.
            if node.get("class_type") == "KSamplerAdvanced" and inp.get("add_noise") == "disable":
                continue
            for key in ("seed", "noise_seed"):
                if isinstance(inp.get(key), int):
                    inp[key] = seed

    return g


def extract_output_files(history_data: dict) -> list[dict]:
    """All saved output files in a /history entry, across SaveImage/SaveVideo
    (``images``) and VHS_VideoCombine (``gifs``) nodes."""
    files = []
    for node_out in (history_data.get("outputs") or {}).values():
        for key in ("images", "gifs"):
            for f in node_out.get(key, []) or []:
                if isinstance(f, dict) and f.get("filename"):
                    files.append(f)
    return files


def missing_inputs(graph: dict, input_dir) -> list[str]:
    """Referenced input files that don't exist, so a replay can be blocked
    before it fails mid-run.

    Checks LoadImage images (resolved under ComfyUI's input dir) and video
    loaders (absolute paths or paths under the input dir).
    """
    input_dir = Path(input_dir)
    missing = []
    for node in graph.values():
        ct = node.get("class_type")
        inp = node.get("inputs", {})
        if ct == "LoadImage":
            name = inp.get("image")
            if isinstance(name, str) and name and not (input_dir / name).exists():
                missing.append(name)
        elif ct in _VIDEO_LOADERS:
            path = inp.get("video") or inp.get("file")
            if isinstance(path, str) and path:
                if not Path(path).exists() and not (input_dir / path).exists():
                    missing.append(path)
    return missing
