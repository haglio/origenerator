from __future__ import annotations

from collections.abc import Callable
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


class _Range(NamedTuple):
    said: str
    span: tuple
    shown: Callable[[object], str] = lambda fix: ""

    def advice(self, value) -> Advice | None:
        if not _outside(value, self.span):
            return None
        fix = _nearest(value, self.span)
        return Advice(self.said, fix, self.shown(fix))


class _Choices(NamedTuple):
    said: str
    good: tuple[str, ...]
    order: list[str]

    def advice(self, value) -> Advice | None:
        if value in self.good:
            return None
        return Advice(self.said, _nearest_choice(value, self.good, self.order))


def setting_advice(params: dict, definitions=()) -> dict[str, Advice]:
    rules = {**_good_ranges(params, definitions), **_recommended(params)}
    found = {key: rule.advice(params.get(key)) for key, rule in rules.items()}
    return {key: advice for key, advice in found.items() if advice is not None}


def recommendations(params: dict) -> dict[str, str]:
    return {key: rule.said for key, rule in _recommended(params).items()}


def _good_ranges(params: dict, definitions) -> dict[str, _Range]:
    return {pd.key: _Range(good_range_text(pd), pd.good, lambda fix, pd=pd: _in_seconds(fix, pd))
            for pd in definitions if pd.good and pd.key in params}


def _in_seconds(frames, pd: ParamDef) -> str:
    if not pd.rate:
        return ""
    return f"{_shown(seconds_for_frames(frames, pd.rate, pd))} {pd.unit}"


def _recommended(params: dict) -> dict:
    rules = _model_recommends(params)
    for key, rule in _loras_recommend(params).items():
        rules.setdefault(key, rule)
    return rules


def _model_recommends(params: dict) -> dict:
    sampler = params.get("sampler_name")
    page = _model_page(params)
    name, choices = page.get("name"), recommended_choices(params)
    rules: dict = {}
    if choices["sampler_name"]:
        rules["sampler_name"] = _Choices(
            f"{name}'s page recommends {_either(choices['sampler_name'])}.",
            choices["sampler_name"], SAMPLER_OPTIONS)
    if choices["scheduler"]:
        paired_by_page = bool((page.get("samplers") or {}).get(sampler))
        pairs = f"{name}'s page pairs {sampler}" if paired_by_page else f"{sampler} works best"
        rules["scheduler"] = _Choices(f"{pairs} with {_either(choices['scheduler'])}.",
                                     choices["scheduler"], SCHEDULER_OPTIONS)
    for key, unit in (("steps", " steps"), ("cfg", "")):
        if page.get(key):
            rules[key] = _Range(f"{name}'s page recommends {_span(page[key])}{unit}.", page[key])
    return rules


def _loras_recommend(params: dict) -> dict:
    loras = lora_recommendations()
    pages = {side: loras.get(params.get(f"lora_{side}") or "") for side in _PASSES
             if f"lora_{side}" in params}
    rules: dict = {}
    for side, page in pages.items():
        if page is None:
            continue
        if page.get("strength"):
            rules[f"lora_strength_{side}"] = _Range(
                f"{page['name']}'s page recommends a strength of {_span(page['strength'])}.",
                page["strength"])
        if page.get("cfg"):
            rules.setdefault(f"cfg_{side}" if f"cfg_{side}" in params else "cfg",
                             _Range(_with(page, "cfg"), page["cfg"]))
    shared = list(pages.values())
    if shared and all(page is not None for page in shared):
        page = shared[0]
        if page.get("steps"):
            rules["steps"] = _Range(_with(page, "steps", " steps"), page["steps"])
        if page.get("shift"):
            rules["shift_high" if "shift_high" in params else "shift"] = _Range(
                _with(page, "shift"), page["shift"])
    return rules


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
