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


def with_trigger_words_swapped(prompt: str, old, new, *, in_scenes: bool = False) -> str:
    for word in old:
        if word not in new:
            prompt = _pattern(word).sub(lambda _found: new[0], prompt)
    return with_trigger_word(prompt, new, in_scenes=in_scenes)


def without_trigger_word(prompt: str, words, *, in_scenes: bool = False) -> str:
    return story_of([without_phrases(scene, words) for scene in _parts(prompt, in_scenes)])


def without_phrases(text: str, words) -> str:
    if not _holds_one(text, words):
        return text
    for word in words:
        whole = _pattern(word).pattern
        text = re.sub(rf"\(\s*{whole}\s*(?::\s*[0-9.]+)?\s*\)|{whole}", "", text,
                      flags=re.IGNORECASE)
    text = re.sub(r"(?:\s*,\s*){2,}", ", ", text)
    text = re.sub(r"^[\s,]+|[\s,]+$", "", text)
    return re.sub(r"[^\S\n]{2,}", " ", text)


def _parts(prompt: str, in_scenes: bool) -> list[str]:
    return scene_prompts(prompt) if in_scenes else [prompt]


def _holds_one(text: str, words) -> bool:
    return any(_holds(text, word) for word in words)


def _holds(text: str, word: str) -> bool:
    return _pattern(word).search(text) is not None


def _pattern(word: str) -> re.Pattern:
    spaced = r"\s+".join(re.escape(part) for part in word.split())
    return re.compile(rf"(?<!\w){spaced}(?!\w)", re.IGNORECASE)
