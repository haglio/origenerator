from __future__ import annotations

import re

from origenerator import config
from origenerator.model_titles import kept_by_stem, model_stem, write_kept
from origenerator.workflows.base import ahead_of, scene_prompts, story_of


def trigger_words_by_lora() -> dict[str, list[str]]:
    return kept_by_stem(config.TRIGGER_WORDS_PATH)


def write_trigger_words(found: dict[str, list[str]]) -> None:
    write_kept(config.TRIGGER_WORDS_PATH, found)


def trigger_words(lora) -> tuple[str, ...]:
    entries = trigger_words_by_lora().get(model_stem(lora)) or ()
    return tuple(word for word in (str(entry).strip() for entry in entries) if word)


def missing_words(prompt: str, words) -> list[str]:
    scenes = scene_prompts(prompt)
    return [word for word in words if not all(_holds(scene, word) for scene in scenes)]


def with_words(prompt: str, words) -> str:
    return story_of([ahead_of(", ".join(missing_words(scene, words)), scene)
                     for scene in scene_prompts(prompt)])


def _holds(text: str, word: str) -> bool:
    spaced = r"\s+".join(re.escape(part) for part in word.split())
    return re.search(rf"(?<!\w){spaced}(?!\w)", text, re.IGNORECASE) is not None
