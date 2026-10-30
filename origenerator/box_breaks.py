from __future__ import annotations

BOX_BREAK = "\x1e"


def prompt_boxes(text: str) -> list[str]:
    return text.split(BOX_BREAK)


def unboxed(text: str) -> str:
    return text.replace(BOX_BREAK, " ")
