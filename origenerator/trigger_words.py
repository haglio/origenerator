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


def lacks_trigger_word(prompt: str, words, *, in_scenes: bool = False) -> bool:
    return not all(_holds_one(scene, words) for scene in _parts(prompt, in_scenes))


def with_trigger_word(prompt: str, words, *, in_scenes: bool = False) -> str:
    return story_of([scene if _holds_one(scene, words) else ahead_of(words[0], scene)
                     for scene in _parts(prompt, in_scenes)])


def _parts(prompt: str, in_scenes: bool) -> list[str]:
    return scene_prompts(prompt) if in_scenes else [prompt]


def _holds_one(text: str, words) -> bool:
    return any(_holds(text, word) for word in words)


def _holds(text: str, word: str) -> bool:
    spaced = r"\s+".join(re.escape(part) for part in word.split())
    return re.search(rf"(?<!\w){spaced}(?!\w)", text, re.IGNORECASE) is not None
