from __future__ import annotations

from origenerator import config
from origenerator.model_titles import kept_by_stem, write_kept


def trigger_words_by_lora() -> dict[str, list[str]]:
    return kept_by_stem(config.TRIGGER_WORDS_PATH)


def write_trigger_words(found: dict[str, list[str]]) -> None:
    write_kept(config.TRIGGER_WORDS_PATH, found)
