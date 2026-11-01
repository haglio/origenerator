from __future__ import annotations

import re

from origenerator import config
from origenerator.model_titles import kept_by_stem, model_stem

_TEXT_TO_VIDEO = re.compile(r"\bt2v\b", re.IGNORECASE)
_KIND_OF = {"Krea 2 Raw": "Krea 2", "Krea 2 Turbo": "Krea 2"}


def base_model_of(value) -> str:
    return _filed_under(kept_by_stem(config.BASE_MODELS_PATH), value)


def made_for_text_to_video(value) -> bool:
    return _TEXT_TO_VIDEO.search(base_model_of(value)) is not None


def loras_offered_beside(model, loras) -> list:
    filed = kept_by_stem(config.BASE_MODELS_PATH)
    return [lora for lora in loras if not _apart(filed, lora, model)]


def filed_apart(lora, model) -> bool:
    return _apart(kept_by_stem(config.BASE_MODELS_PATH), lora, model)


def _apart(filed: dict, lora, model) -> bool:
    made_for, picked = _filed_under(filed, lora), _filed_under(filed, model)
    return bool(made_for and picked) and not _go_together(made_for, picked)


def _go_together(made_for: str, picked: str) -> bool:
    return made_for in (picked, _KIND_OF.get(picked)) or picked == _KIND_OF.get(made_for)


def _filed_under(filed: dict, value) -> str:
    return str(filed.get(model_stem(value)) or "")
