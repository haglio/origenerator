from __future__ import annotations

from typing import NamedTuple

from origenerator.content import load_content
from origenerator.workflows.base import SAMPLER_OPTIONS, SCHEDULER_OPTIONS, ParamDef
from origenerator.workflows.duration import seconds_for_frames

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


class Advice(NamedTuple):
    text: str
    fix: object
    shown: str = ""

    @property
    def fix_shown(self) -> str:
        return self.shown or _shown(self.fix)


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


def setting_advice(params: dict, definitions=()) -> dict[str, Advice]:
    advice, judged = _model_advice(params)
    for key, found in _lora_advice(params, judged).items():
        advice.setdefault(key, found)
    for pd in definitions:
        if pd.key in judged or pd.key not in params:
            continue
        _hold(advice, judged, pd.key, params[pd.key], pd.good, good_range_text(pd),
              shown=lambda fix: _in_seconds(fix, pd))
    return advice


def _in_seconds(frames, pd: ParamDef) -> str:
    if not pd.rate:
        return ""
    return f"{_shown(seconds_for_frames(frames, pd.rate, pd))} {pd.unit}"


def _hold(advice: dict, judged: set, key: str, value, span, said: str,
          shown=lambda fix: "") -> None:
    if not span:
        return
    judged.add(key)
    if _outside(value, span):
        fix = _nearest(value, span)
        advice[key] = Advice(said, fix, shown(fix))


def _model_advice(params: dict) -> tuple[dict[str, Advice], set[str]]:
    advice: dict[str, Advice] = {}
    judged: set[str] = set()
    sampler, spacing = params.get("sampler_name"), params.get("scheduler")
    page = _model_page(params)
    name, choices = page.get("name"), recommended_choices(params)
    if choices["sampler_name"] and sampler not in choices["sampler_name"]:
        advice["sampler_name"] = Advice(
            f"{name}'s page recommends {_either(choices['sampler_name'])}.",
            _nearest_choice(sampler, choices["sampler_name"], SAMPLER_OPTIONS))
    if choices["scheduler"] and spacing not in choices["scheduler"]:
        paired_by_page = bool((page.get("samplers") or {}).get(sampler))
        pairs = f"{name}'s page pairs {sampler}" if paired_by_page else f"{sampler} works best"
        advice["scheduler"] = Advice(f"{pairs} with {_either(choices['scheduler'])}.",
                                     _nearest_choice(spacing, choices["scheduler"],
                                                     SCHEDULER_OPTIONS))
    for key, unit in (("steps", " steps"), ("cfg", "")):
        if page.get(key):
            _hold(advice, judged, key, params.get(key), page[key],
                  f"{name}'s page recommends {_span(page[key])}{unit}.")
    return advice, judged


def _lora_advice(params: dict, judged: set[str]) -> dict[str, Advice]:
    loras = lora_recommendations()
    pages = {side: loras.get(params.get(f"lora_{side}") or "") for side in _PASSES
             if f"lora_{side}" in params}
    advice: dict[str, Advice] = {}
    for side, page in pages.items():
        if page is None:
            continue
        strength_key = f"lora_strength_{side}"
        if page.get("strength"):
            _hold(advice, judged, strength_key, params.get(strength_key), page["strength"],
                  f"{page['name']}'s page recommends a strength of {_span(page['strength'])}.")
        cfg_key = f"cfg_{side}" if f"cfg_{side}" in params else "cfg"
        if page.get("cfg") and cfg_key not in advice:
            _hold(advice, judged, cfg_key, params.get(cfg_key), page["cfg"],
                  _with(page, "cfg"))
    shared = list(pages.values())
    if shared and all(page is not None for page in shared):
        page = shared[0]
        if page.get("steps"):
            _hold(advice, judged, "steps", params.get("steps"), page["steps"],
                  _with(page, "steps", " steps"))
        shift_key = "shift_high" if "shift_high" in params else "shift"
        if page.get("shift"):
            _hold(advice, judged, shift_key, params.get(shift_key), page["shift"],
                  _with(page, "shift"))
    return advice


def _with(page: dict, recommended: str, unit: str = "") -> str:
    return (f"With the {page['name']} LoRA, its page recommends "
            f"{_span(page[recommended])}{unit}.")


def good_range_text(pd: ParamDef) -> str:
    if pd.good is None:
        return ""
    low, high = pd.good
    if pd.rate:
        low, high = (seconds_for_frames(int(edge), pd.rate, pd) for edge in (low, high))
    unit = f" {pd.unit}" if pd.unit else ""
    return f"Good range: {_span((low, high))}{unit}."


def _outside(value, span) -> bool:
    if value is None or not span:
        return False
    low, high = span
    return not low <= float(value) <= high


def _nearest(value, span):
    low, high = span
    return low if float(value) < low else high


def _nearest_choice(current, choices, order: list[str]) -> str:
    def place(choice) -> int:
        return order.index(choice) if choice in order else len(order)
    return min(choices, key=lambda choice: (abs(place(choice) - place(current)), place(choice)))


def _span(span) -> str:
    low, high = span
    return _shown(low) if low == high else f"{_shown(low)}–{_shown(high)}"


def _shown(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def _either(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
