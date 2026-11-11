from __future__ import annotations

from origenerator.content import load_content


def shown_name(name: str) -> str:
    return (load_content().get("display_names") or {}).get(name, name)
