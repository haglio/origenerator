from __future__ import annotations

import re

from origenerator import config
from origenerator.model_titles import kept_by_stem, model_stem

_TEXT_TO_VIDEO = re.compile(r"\bt2v\b", re.IGNORECASE)


def base_model_of(value) -> str:
    return _filed_under(kept_by_stem(config.BASE_MODELS_PATH), value)


def made_for_text_to_video(value) -> bool:
    return _TEXT_TO_VIDEO.search(base_model_of(value)) is not None


def loras_offered_beside(model, loras) -> list:
    filed = kept_by_stem(config.BASE_MODELS_PATH)
    picked = _filed_under(filed, model)
    return [lora for lora in loras if not picked or _filed_under(filed, lora) in ("", picked)]


def _filed_under(filed: dict, value) -> str:
    return str(filed.get(model_stem(value)) or "")
