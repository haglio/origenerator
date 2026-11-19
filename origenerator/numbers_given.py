from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path

from origenerator.file_numbers import highest_numbers

logger = logging.getLogger(__name__)


class NumbersGiven:
    def __init__(self, path: Path | None, names_in_use: Callable[[], Iterable[str]]) -> None:
        self._path = path
        self._highest = self._kept() if path is not None else None
        if self._highest is None:
            self._highest = highest_numbers(names_in_use())
            self._keep()

    def highest(self, stem: str) -> int:
        return self._highest.get(stem, 0)

    def gave(self, names: Iterable[str]) -> None:
        given = highest_numbers(names)
        moved = {stem: number for stem, number in given.items() if number > self.highest(stem)}
        if moved:
            self._highest.update(moved)
            self._keep()

    def _kept(self) -> dict[str, int] | None:
        try:
            held = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning("The numbers given could not be read (%s); reading the lanes again", e)
            return None
        if not isinstance(held, dict):
            return None
        return {stem: number for stem, number in held.items()
                if isinstance(stem, str) and type(number) is int}

    def _keep(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        partial = self._path.with_name(self._path.name + ".partial")
        partial.write_bytes((json.dumps(self._highest, indent=1, sort_keys=True) + "\n").encode())
        os.replace(partial, self._path)
