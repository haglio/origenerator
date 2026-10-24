"""What each item is called: its folder's code and its number in that folder."""
from __future__ import annotations

import re
import string
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple

from origenerator.gallery.keys import FOLDER_ID_CHARS, folder_id

_DIGITS_SHOWN = 3
_HIGHEST_SHOWN = 10 ** _DIGITS_SHOWN - 1
_WRITTEN_NAME_START = re.compile(
    rf"\b([0-9a-f]{{{FOLDER_ID_CHARS}}})\s+([0-9]{{1,{_DIGITS_SHOWN}}})\b", re.IGNORECASE)


class ItemNumber(NamedTuple):
    folder_key: str
    number: int


def item_name(item: ItemNumber) -> str:
    return _named(folder_id(item.folder_key), item.number)


def widest_item_name(width_of: Callable[[str], int]) -> str:
    def widest(characters: str) -> str:
        return max(characters, key=width_of)

    return _named(widest(string.hexdigits.upper()) * FOLDER_ID_CHARS,
                  int(widest(string.digits) * _DIGITS_SHOWN))


def name_starts_in(text: str) -> list[str]:
    return [f"{code.upper()} {digits}" for code, digits in _WRITTEN_NAME_START.findall(text)]


def without_name_starts(text: str) -> str:
    return _WRITTEN_NAME_START.sub(" ", text)


def _named(code: str, number: int) -> str:
    return f"{code} {min(number, _HIGHEST_SHOWN):0{_DIGITS_SHOWN}d}"


def number_items(folders: Mapping[str, Sequence[str]],
                 recorded: Mapping[str, tuple[str, int]]) -> dict[str, ItemNumber]:
    highest = _highest_recorded(recorded)
    numbering: dict[str, ItemNumber] = {}
    for key, prompt_ids in folders.items():
        numbering.update(_numbered(key, prompt_ids, recorded, highest.get(key, -1)))
    return numbering


def _highest_recorded(recorded: Mapping[str, tuple[str, int]]) -> dict[str, int]:
    highest: dict[str, int] = {}
    for key, number in recorded.values():
        highest[key] = max(highest.get(key, -1), number)
    return highest


def _numbered(key: str, prompt_ids: Sequence[str],
              recorded: Mapping[str, tuple[str, int]], last: int) -> dict[str, ItemNumber]:
    kept = [recorded[p][1] if p in recorded else None for p in prompt_ids]
    last = max([last, *(number for number in kept if number is not None)])
    taken: set[int] = set()
    numbering = {}
    for prompt_id, number in zip(prompt_ids, kept, strict=True):
        if number is None or number in taken:
            last = number = last + 1
        taken.add(number)
        numbering[prompt_id] = ItemNumber(key, number)
    return numbering
