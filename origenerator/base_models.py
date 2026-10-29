from __future__ import annotations

import re

from origenerator import config
from origenerator.model_titles import kept_by_stem, model_stem

_TEXT_TO_VIDEO = re.compile(r"\bt2v\b", re.IGNORECASE)


def base_model_of(value) -> str:
    return str(kept_by_stem(config.BASE_MODELS_PATH).get(model_stem(value)) or "")


def made_for_text_to_video(value) -> bool:
    return _TEXT_TO_VIDEO.search(base_model_of(value)) is not None
