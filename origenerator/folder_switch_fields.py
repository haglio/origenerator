from __future__ import annotations

SWITCH_KEYS = ("favorite_after_id", "enhance_after_id", "enhance_settings")


def switches_of(meta: dict) -> dict:
    return {key: meta.get(key) for key in SWITCH_KEYS}
