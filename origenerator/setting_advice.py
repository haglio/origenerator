from __future__ import annotations

from origenerator.content import load_content


def model_recommendations() -> dict:
    return load_content().get("model_recommendations") or {}


def fresh_settings(defaults: dict, checkpoint: str | None) -> dict:
    start = model_recommendations().get(checkpoint or "", {}).get("start") or {}
    return {**defaults, **{key: value for key, value in start.items() if key in defaults}}
