from __future__ import annotations

from origenerator.content import load_content

GOOD_STEP_SPACING = {
    "dpmpp_2m": ("karras", "exponential"),
    "dpmpp_2m_sde": ("karras", "exponential"),
    "dpmpp_2m_sde_gpu": ("karras", "exponential"),
    "dpmpp_3m_sde": ("exponential", "karras"),
    "dpmpp_3m_sde_gpu": ("exponential", "karras"),
    "dpmpp_sde": ("karras",),
    "dpmpp_sde_gpu": ("karras",),
    "dpmpp_2s_ancestral": ("karras",),
    "dpm_2": ("karras",),
    "dpm_2_ancestral": ("karras",),
    "lms": ("karras",),
    "ddim": ("ddim_uniform", "normal"),
    "lcm": ("sgm_uniform", "simple"),
}
_PASSES = ("high", "low")


def model_recommendations() -> dict:
    return load_content().get("model_recommendations") or {}


def lora_recommendations() -> dict:
    return load_content().get("lora_recommendations") or {}


def fresh_settings(defaults: dict, checkpoint: str | None) -> dict:
    start = model_recommendations().get(checkpoint or "", {}).get("start") or {}
    return {**defaults, **{key: value for key, value in start.items() if key in defaults}}


def recommended_choices(params: dict) -> dict[str, tuple[str, ...]]:
    samplers = _model_page(params).get("samplers") or {}
    sampler = params.get("sampler_name")
    spacings = samplers.get(sampler) or GOOD_STEP_SPACING.get(sampler) or ()
    return {"sampler_name": tuple(samplers), "scheduler": tuple(spacings)}


def _model_page(params: dict) -> dict:
    return model_recommendations().get(params.get("checkpoint") or "") or {}


def setting_advice(params: dict) -> dict[str, str]:
    advice = _model_advice(params)
    for key, text in _lora_advice(params).items():
        advice.setdefault(key, text)
    return advice


def _model_advice(params: dict) -> dict[str, str]:
    advice: dict[str, str] = {}
    sampler, spacing = params.get("sampler_name"), params.get("scheduler")
    page = _model_page(params)
    name, choices = page.get("name"), recommended_choices(params)
    if choices["sampler_name"] and sampler not in choices["sampler_name"]:
        advice["sampler_name"] = f"{name}'s page recommends {_either(choices['sampler_name'])}."
    if choices["scheduler"] and spacing not in choices["scheduler"]:
        paired_by_page = bool((page.get("samplers") or {}).get(sampler))
        pairs = f"{name}'s page pairs {sampler}" if paired_by_page else f"{sampler} works best"
        advice["scheduler"] = f"{pairs} with {_either(choices['scheduler'])}."
    for key, unit in (("steps", " steps"), ("cfg", "")):
        if _outside(params.get(key), page.get(key)):
            advice[key] = f"{name}'s page recommends {_span(page[key])}{unit}."
    return advice


def _lora_advice(params: dict) -> dict[str, str]:
    loras = lora_recommendations()
    pages = {side: loras.get(params.get(f"lora_{side}") or "") for side in _PASSES
             if f"lora_{side}" in params}
    advice: dict[str, str] = {}
    for side, page in pages.items():
        if page is None:
            continue
        if _outside(params.get(f"lora_strength_{side}"), page.get("strength")):
            advice[f"lora_strength_{side}"] = (
                f"{page['name']}'s page recommends a strength of {_span(page['strength'])}.")
        cfg_key = f"cfg_{side}" if f"cfg_{side}" in params else "cfg"
        if _outside(params.get(cfg_key), page.get("cfg")):
            advice.setdefault(cfg_key, _with(page, page["cfg"]))
    shared = list(pages.values())
    if shared and all(page is not None for page in shared):
        page = shared[0]
        if _outside(params.get("steps"), page.get("steps")):
            advice["steps"] = _with(page, page["steps"], " steps")
        shift_key = "shift_high" if "shift_high" in params else "shift"
        if _outside(params.get(shift_key), page.get("shift")):
            advice[shift_key] = _with(page, page["shift"])
    return advice


def _with(page: dict, span, unit: str = "") -> str:
    return f"With the {page['name']} LoRA, its page recommends {_span(span)}{unit}."


def _outside(value, span) -> bool:
    if value is None or not span:
        return False
    low, high = span
    return not low <= float(value) <= high


def _span(span) -> str:
    low, high = span
    return f"{low:g}" if low == high else f"{low:g}–{high:g}"


def _either(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
