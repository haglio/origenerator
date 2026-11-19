from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

NUMBERED = re.compile(r"^(?P<stem>.+)_(?P<counter>\d+)(?P<rest>\D*\.[^.]+)$")


def next_number(stem: str, folders: Iterable[Path], held: Iterable[str] = ()) -> int:
    names = [*held, *(name for folder in folders if folder.is_dir()
                      for name in os.listdir(folder))]
    numbers = [int(match["counter"]) for name in names
               if (match := NUMBERED.match(name)) and match["stem"] == stem]
    return max(numbers, default=0) + 1


def highest_numbers(names: Iterable[str]) -> dict[str, int]:
    highest: dict[str, int] = {}
    for name in names:
        match = NUMBERED.match(name)
        if match:
            highest[match["stem"]] = max(highest.get(match["stem"], 0), int(match["counter"]))
    return highest


def numbered(name: str, stem: str, number: int) -> str:
    return f"{stem}_{number:05}{NUMBERED.match(name)['rest']}"
