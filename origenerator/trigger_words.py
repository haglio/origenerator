from __future__ import annotations

import json

from origenerator import config
from origenerator.model_titles import kept_by_stem


def trigger_words_by_lora() -> dict[str, list[str]]:
    return kept_by_stem(config.TRIGGER_WORDS_PATH)


def write_trigger_words(found: dict[str, list[str]]) -> None:
    every = {**trigger_words_by_lora(), **found}
    config.TRIGGER_WORDS_PATH.write_text(json.dumps(every, sort_keys=True, indent=1),
                                         encoding="utf-8")
