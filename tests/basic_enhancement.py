from __future__ import annotations

from origenerator import gallery
from origenerator.gallery.enhance_settings import basic_enhance_settings, version_settings


def at_the_basic_settings(enhance: dict) -> bool:
    made = gallery.parse_params(enhance["params_json"])
    return version_settings(made) == version_settings(basic_enhance_settings().params)
