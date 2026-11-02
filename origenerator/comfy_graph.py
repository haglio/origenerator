from __future__ import annotations

from typing import NamedTuple

_COND_NODES = ("WanImageToVideo", "WanFirstLastFrameToVideo")
_LORA_LOADERS = ("LoraLoaderModelOnly", "LoraLoader")
_JOINED_PROMPTS = "ConditioningConcat"


class ModelChain(NamedTuple):
    unet: str | None
    lora: str | None
    lora_strength: float | None


def follow(graph: dict, ref) -> dict | None:
    if isinstance(ref, list) and ref:
        return graph.get(str(ref[0]))
    return None


def conditioning_node(graph: dict) -> dict | None:
    return next(
        (n for n in graph.values() if n.get("class_type") in _COND_NODES),
        None,
    )


def _takes_no_links(node: dict) -> bool:
    return not any(isinstance(value, list) for value in node.get("inputs", {}).values())


def empty_latent(graph: dict) -> dict | None:
    for node in graph.values():
        source = follow(graph, node.get("inputs", {}).get("latent_image"))
        if source is not None and _takes_no_links(source):
            return source
    return None


def _model_chain(graph: dict, model_ref) -> ModelChain:
    unet = lora = strength = None
    node = follow(graph, model_ref)
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")
        if class_type in _LORA_LOADERS and lora is None:
            name = inputs.get("lora_name")
            if isinstance(name, str):
                lora = name
                strength = _number(inputs.get("strength_model"))
        if class_type == "UNETLoader":
            name = inputs.get("unet_name")
            if isinstance(name, str):
                unet = name
            break
        node = follow(graph, inputs.get("model"))
    return ModelChain(unet, lora, strength)


def _number(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _base_sampler_models(graph: dict) -> dict:
    sampler = next((n for n in graph.values() if n.get("class_type") == "KSampler"), {})
    chain = _model_chain(graph, sampler.get("inputs", {}).get("model"))
    return {key: value for key, value in (("unet", chain.unet), ("lora", chain.lora),
                                          ("lora_strength", chain.lora_strength))
            if value is not None}


def dual_sampler_model_files(graph: dict) -> dict:
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
        chain = _model_chain(graph, sampler.get("inputs", {}).get("model"))
        if chain.unet:
            result[f"unet_{suffix}"] = chain.unet
        if chain.lora:
            result[f"lora_{suffix}"] = chain.lora
        if chain.lora_strength is not None:
            result[f"lora_strength_{suffix}"] = chain.lora_strength
    return result


def graph_model_params(graph: dict) -> dict:
    params: dict = {}
    for node in graph.values():
        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")
        if class_type == "CheckpointLoaderSimple" and isinstance(inputs.get("ckpt_name"), str):
            params["checkpoint"] = inputs["ckpt_name"]
        elif class_type == "UnetLoaderGGUF" and isinstance(inputs.get("unet_name"), str):
            params["unet"] = inputs["unet_name"]
    params.update(_base_sampler_models(graph))
    params.update(dual_sampler_model_files(graph))
    return params


def guidance_params(graph: dict) -> dict:
    found = [strength for node in graph.values()
             if node.get("class_type") == "FluxGuidance"
             and (strength := _number(node.get("inputs", {}).get("guidance"))) is not None]
    return {"guidance": found[-1]} if found else {}


_SOUND_INPUTS = {
    "HunyuanFoleySampler": {"seed": "audio_seed", "prompt": "audio_prompt",
                            "negative_prompt": "audio_negative_prompt"},
    "HunyuanModelLoader": {"model_name": "foley_model"},
    "HunyuanDependenciesLoader": {"vae_name": "foley_vae", "synchformer_name": "foley_synchformer"},
}


def sound_params(graph: dict) -> dict:
    params: dict = {}
    for node in graph.values():
        for input_name, key in _SOUND_INPUTS.get(node.get("class_type", ""), {}).items():
            value = node.get("inputs", {}).get(input_name)
            if isinstance(value, (int, str)) and not isinstance(value, bool):
                params[key] = value
    return params


def driving_video_params(graph: dict) -> dict:
    for node in graph.values():
        inputs = node.get("inputs", {})
        video = inputs.get("video") if node.get("class_type") == "VHS_LoadVideoPath" else None
        if not isinstance(video, str):
            continue
        rate, skipped = inputs.get("force_rate"), inputs.get("skip_first_frames")
        if rate and isinstance(skipped, (int, float)):
            return {"video": video, "video_start": skipped / rate}
        return {"video": video}
    return {}


def input_image_name(graph: dict) -> str | None:
    result = None
    for node in graph.values():
        if node.get("class_type") == "LoadImage":
            image = node.get("inputs", {}).get("image")
            if isinstance(image, str):
                result = image
    return result


def clip_prompt_nodes(graph: dict):
    titled_positive, titled_negative = _titled_prompt_nodes(graph)
    return (_encoder_feeding(graph, "positive") or titled_positive,
            _encoder_feeding(graph, "negative") or titled_negative)


def _titled_prompt_nodes(graph: dict):
    positive = negative = None
    for node in graph.values():
        if node.get("class_type") == "CLIPTextEncode":
            title = node.get("_meta", {}).get("title", "")
            if "Negative" in title:
                negative = node
            elif positive is None:
                positive = node
    return positive, negative


def texts_read(graph: dict, node: dict | None) -> list[str]:
    texts: list[str] = []
    seen: set[int] = set()

    def read(source: dict | None) -> None:
        if source is None or id(source) in seen:
            return
        seen.add(id(source))
        inputs = source.get("inputs", {})
        if source.get("class_type") == _JOINED_PROMPTS:
            read(follow(graph, inputs.get("conditioning_to")))
            read(follow(graph, inputs.get("conditioning_from")))
        elif isinstance(inputs.get("text"), str):
            texts.append(inputs["text"])

    read(node)
    return texts


def _encoder_feeding(graph: dict, side: str) -> dict | None:
    for node in graph.values():
        source = follow(graph, node.get("inputs", {}).get(side))
        seen: set[int] = set()
        while source is not None and id(source) not in seen:
            if source.get("class_type") in ("CLIPTextEncode", _JOINED_PROMPTS):
                return source
            seen.add(id(source))
            inputs = source.get("inputs", {})
            source = follow(graph, inputs.get(side)) or follow(graph, inputs.get("conditioning"))
    return None
