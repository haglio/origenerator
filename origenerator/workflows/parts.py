from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Segment(NamedTuple):
    index: int
    scene: int
    start: object
    length: int
    last: bool
    previous: object = None


@dataclass(frozen=True)
class NodeRefs:
    image: list
    model: list
    positive: list
    negative: list
    vae: list
    clip_ref: list | None = None
