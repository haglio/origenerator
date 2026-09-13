from __future__ import annotations

from typing import NamedTuple


class Combination(NamedTuple):
    picture: str | None = None
    recipe: str | None = None
    recipe_prompt_edited: bool = False
