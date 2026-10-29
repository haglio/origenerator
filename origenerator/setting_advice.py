from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator.content import load_content
from origenerator.model_titles import model_title
from origenerator.trigger_words import lacks_trigger_word, trigger_words, with_trigger_word
from origenerator.workflows.base import SAMPLER_OPTIONS, SCHEDULER_OPTIONS, ParamDef
from origenerator.workflows.duration import seconds_for_frames
from origenerator.workflows.lora_rows import LORA_KEYS, strength_key_of
from origenerator.workflows.model_files import is_no_lora
from origenerator.workflows.wan_experts import FIRST_PASS_LORA_KEYS, SECOND_PASS_LORA_KEYS

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
_STRENGTHS = ("cfg", "cfg_high", "cfg_low")
_SHARED_GOOD_RANGE = (0.6, 0.8)
_LORA_GROUPS = {
    LORA_KEYS: "Good range while another LoRA is picked",
    FIRST_PASS_LORA_KEYS: "Good range while another LoRA is picked for this pass",
    SECOND_PASS_LORA_KEYS: "Good range while another LoRA is picked for this pass",
}
STRENGTH_BELOW_ONE = ("Below 1 the Negative Prompt works backwards: what you get is pulled toward "
                      "what it names, and at 0 the Positive Prompt is ignored altogether.")
_LONGEST_TRIGGER_WORD_IN_WORDS = 5


def _shown(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


class Advice(NamedTuple):
    text: str
    value: object
    fix: object
    shown: Callable[[object], str] = _shown

    writes = ""

    @property
    def value_shown(self) -> str:
        return self.shown(self.value)

    @property
    def fix_shown(self) -> str:
        return self.shown(self.fix)

    @property
    def said(self) -> str:
        return f"{self.text} Click to use {self.fix_shown}."

    def fixed(self, _held) -> object:
        return self.fix


class MissingTriggerWords(NamedTuple):
    lora: str
    words: tuple[str, ...]

    writes = "positive_prompt"

    @property
    def value_shown(self) -> str:
        return model_title(self.lora)

    @property
    def said(self) -> str:
        if len(self.words) == 1:
            return (f"{self.value_shown}'s trigger word, {self.words[0]}, isn't in the "
                    "Positive Prompt. Click to add it.")
        return (f"{self.value_shown}'s trigger words, {spoken_list(self.words, 'and')}, aren't in "
                f"the Positive Prompt. Click to add {self.words[0]}.")

    def fixed(self, prompt: str) -> str:
        return with_trigger_word(prompt, self.words)


def trigger_word_advice(params: dict, lora_keys) -> dict[str, MissingTriggerWords]:
    words = {key: _warned_trigger_words(params[key]) for key in lora_keys
             if not is_no_lora(params.get(key))}
    return {key: MissingTriggerWords(params[key], found) for key, found in words.items()
            if found and lacks_trigger_word(params["positive_prompt"], found)}


def _warned_trigger_words(lora: str) -> tuple[str, ...]:
    return tuple(word for word in trigger_words(lora)
                 if len(word.split()) <= _LONGEST_TRIGGER_WORD_IN_WORDS)


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
    shown: Callable[[object], str] = _shown

    def advice(self, value) -> Advice | None:
        if not _outside(value, self.span):
            return None
        return Advice(self.said, value, _nearest(value, self.span), self.shown)


class _Choices(NamedTuple):
    said: str
    good: tuple[str, ...]
    order: list[str]

    def advice(self, value) -> Advice | None:
        if value in self.good:
            return None
        return Advice(self.said, value, _nearest_choice(value, self.good, self.order))


def setting_advice(params: dict, definitions=()) -> dict[str, Advice]:
    rules = {**_good_ranges(params, definitions), **_shared_strength_ranges(params),
             **_recommended(params)}
    found = {key: rule.advice(params.get(key)) for key, rule in rules.items()}
    for key in _STRENGTHS:
        if params.get(key) is not None and float(params[key]) < 1.0:
            found[key] = _backwards(params[key], found.get(key))
    return {key: advice for key, advice in found.items() if advice is not None}


def _backwards(strength, usual: Advice | None) -> Advice:
    if usual is None:
        return Advice(STRENGTH_BELOW_ONE, strength, 1.0)
    return usual._replace(text=f"{STRENGTH_BELOW_ONE} {usual.text}")


def recommendations(params: dict) -> dict[str, str]:
    rules = {**_shared_strength_ranges(params), **_recommended(params)}
    return {key: rule.said for key, rule in rules.items()}


def not_installed(params: dict, definitions, keys) -> dict[str, str]:
    return {pd.key: params[pd.key] for pd in definitions
            if pd.key in keys and pd.options and params.get(pd.key)
            and not is_no_lora(params[pd.key]) and params[pd.key] not in pd.options}


def not_installed_advice(missing: dict[str, str], definitions, defaults: dict) -> dict[str, Advice]:
    offered = {pd.key: pd.options for pd in definitions}
    return {key: _installed_in_place_of(chosen, offered[key], defaults.get(key))
            for key, chosen in missing.items()}


def _installed_in_place_of(chosen: str, options: list, default) -> Advice:
    fix = default if default in options else options[0]
    return Advice("Not installed anymore, so nothing can be made with it.", chosen, fix,
                  model_title)


def _good_ranges(params: dict, definitions) -> dict[str, _Range]:
    return {pd.key: _Range(good_range_text(pd), pd.good, _shown_for(pd))
            for pd in definitions if pd.good and pd.key in params}


def _shared_strength_ranges(params: dict) -> dict[str, _Range]:
    rules: dict[str, _Range] = {}
    for keys, said in _LORA_GROUPS.items():
        picked = [key for key in keys if not is_no_lora(params.get(key))]
        if len(picked) > 1:
            shared = _Range(f"{said}: {_span(_SHARED_GOOD_RANGE)}.", _SHARED_GOOD_RANGE)
            rules.update(dict.fromkeys(map(strength_key_of, picked), shared))
    return rules


def _shown_for(pd: ParamDef) -> Callable[[object], str]:
    if not pd.rate:
        return _shown
    return lambda frames: f"{_shown(seconds_for_frames(frames, pd.rate, pd))} {pd.unit}"


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
            f"{name}'s page recommends {spoken_list(choices['sampler_name'], 'or')}.",
            choices["sampler_name"], SAMPLER_OPTIONS)
    if choices["scheduler"]:
        paired_by_page = bool((page.get("samplers") or {}).get(sampler))
        pairs = f"{name}'s page pairs {sampler}" if paired_by_page else f"{sampler} works best"
        rules["scheduler"] = _Choices(f"{pairs} with {spoken_list(choices['scheduler'], 'or')}.",
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
    for keys in _LORA_GROUPS:
        for key in keys:
            page = loras.get(params.get(key) or "")
            if page is not None and page.get("strength"):
                rules[strength_key_of(key)] = _Range(
                    f"{page['name']}'s page recommends a strength of {_span(page['strength'])}.",
                    page["strength"])
    for side, page in pages.items():
        if page is None:
            continue
        if page.get("cfg"):
            rules.setdefault(f"cfg_{side}" if f"cfg_{side}" in params else "cfg",
                             _Range(_with(page, "cfg"), page["cfg"]))
    shared = list(pages.values())
    if shared and all(page is not None for page in shared):
        page = shared[0]
        if page.get("steps"):
            rules["steps"] = _Range(_with(page, "steps", " steps"), page["steps"])
        if page.get("shift"):
            rules["shift_high"] = _Range(_with(page, "shift"), page["shift"])
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


def spoken_list(names, conjunction: str) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {conjunction} {names[-1]}"
