from __future__ import annotations

from funestra.video_families import normalized_text

from origenerator.content import load_content
from origenerator.generation_config import filled_params, randomize_seeds
from origenerator.workflows.derived_size import without_an_explicit_size
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS

_CONTENT = load_content()

# ComfyUI's model cannot close a shorter loop: the last frame lands further from the first (13 frames
# -2.02%, 29 frames +0.23%, measured at a fixed seed), and the lighting pops on every repeat.
CYCLE_FRAMES = 29

_CYCLE_WORDS: dict = {normalized_text(name): words for name, words
                      in (_CONTENT.get("genau_flick_prompts") or {}).items()
                      if isinstance(words, dict)}


def combined_params(video_row: dict, input_image: str | None, workflow) -> dict | None:
    params = _run_on(input_image, filled_params(video_row, workflow), workflow)
    return None if params is None else without_an_explicit_size(params, workflow)


_PROMPT_KEYS = ("positive_prompt", "negative_prompt", "scene_lines",
                "audio_prompt", "audio_negative_prompt")


def prompts_differ_from(params: dict, video_row: dict, workflow) -> bool:
    run = {**workflow.default_params(), **params}
    followed = filled_params(video_row, workflow)
    return any(_words(run.get(key)) != _words(followed.get(key)) for key in _PROMPT_KEYS)


def _words(prompt):
    if isinstance(prompt, (list, tuple)):
        return [_words(line) for line in prompt]
    return " ".join(str(prompt or "").split())


def written_params(settings: dict, input_image: str | None, workflow) -> dict | None:
    params = {**workflow.default_params(), **(settings.get("params") or {})}
    return _run_on(input_image, params, workflow)


def _run_on(input_image: str | None, params: dict, workflow) -> dict | None:
    if not input_image:
        return None
    return {**randomize_seeds(params, workflow.seed_keys()), "input_image": input_image}


def cycle_words(*names: str) -> tuple[str, str]:
    found = [words for name in dict.fromkeys(map(normalized_text, names))
             if (words := _CYCLE_WORDS.get(name)) and name]
    if not found:
        found = [_CYCLE_WORDS.get("") or {}]
    return _joined(found, "positive"), _joined(found, "negative")


def _joined(found: list[dict], key: str) -> str:
    return " ".join(said for said in ((words.get(key) or "").strip() for words in found) if said)


def cycle_names(own: tuple[str, ...], image: tuple[str, ...]) -> tuple[str, ...]:
    has_words = any(normalized_text(name) in _CYCLE_WORDS for name in own if name)
    return own if has_words else (*own, *image)


def cycle_shaped(params: dict, workflow, *names: str) -> dict:
    defaults = workflow.default_params()
    if "frame_count" not in defaults or "frame_rate" not in defaults:
        return params
    positive, negative = cycle_words(*names)
    shaped = {**params, "frame_count": CYCLE_FRAMES, "frame_rate": MAX_PLAYBACK_FPS}
    for key, extra in (("positive_prompt", positive),
                       ("negative_prompt", negative)):
        if extra:
            shaped[key] = f"{params.get(key) or ''} {extra}".strip()
    return shaped
