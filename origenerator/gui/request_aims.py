from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from PySide6.QtCore import QObject, Signal


@dataclass
class RequestAim:
    prompt_id: str
    shown: tuple[str, str]
    earlier: list = field(default_factory=list)
    asked_into: list = field(default_factory=list)
    started_on: str | None = None
    turns: list = field(default_factory=list)
    values: list = field(default_factory=list)
    asking: str | None = None
    awaited: object | None = None

    def every_turn(self) -> list:
        return self.earlier + self.turns

    def last_made(self, before: int) -> int:
        made = [index for index, turn in enumerate(self.every_turn()[:before]) if turn.made]
        return made[-1] if made else -1

    def is_nearest_the_end_of_the_made(self, index: int) -> bool:
        return not any(turn.made for turn in self.every_turn()[index + 1:])

    def made_before(self, index: int) -> str | None:
        last = self.last_made(index)
        return self.every_turn()[last].made if last >= 0 else self.started_on

    def note_made(self, index: int, prompt_id: str) -> None:
        if index < len(self.earlier):
            self.earlier[index] = self.earlier[index]._replace(made=prompt_id)
        else:
            at = index - len(self.earlier)
            self.turns[at] = self.turns[at]._replace(made=prompt_id)

    def forget_what_never_came(self, still_there) -> list[int]:
        forgotten = [index for index, turn in enumerate(self.every_turn())
                     if turn.made and not still_there(turn.made)]
        for index in forgotten:
            self.note_made(index, "")
        return forgotten

    def turns_up_to(self, prompt_id: str) -> int | None:
        made = [turn.made for turn in self.turns]
        return made.index(prompt_id) + 1 if prompt_id in made else None

    def answered(self, turn, values: dict) -> None:
        self.turns.append(turn)
        self.values.append(values)

    def carried_onto(self, prompt_id: str, shown: tuple[str, str], recorded: int) -> None:
        self.turns = self.turns[recorded:]
        self.values = self.values[recorded:]
        self.prompt_id = prompt_id
        self.shown = shown


class RequestAims(QObject):
    answered = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._by_item: dict[str, RequestAim] = {}

    def of(self, prompt_id: str) -> RequestAim | None:
        return self._by_item.get(prompt_id)

    def keep(self, aim: RequestAim) -> None:
        self._by_item[aim.prompt_id] = aim

    def forget(self, prompt_id: str) -> None:
        self._by_item.pop(prompt_id, None)

    def awaiting(self, aim: RequestAim, words: str, values: dict):
        aim.asking, aim.awaited = words, object()
        return partial(self._take_answer, aim, values, aim.awaited)

    def cancel(self, aim: RequestAim) -> None:
        aim.asking = aim.awaited = None

    def _take_answer(self, aim: RequestAim, values: dict, awaited: object, revision) -> None:
        if aim.awaited is not awaited:
            return
        said, aim.asking, aim.awaited = aim.asking, None, None
        if revision is not None:
            aim.answered(revision.turn(said), {**values, **dict(revision.settings)})
        self.answered.emit(aim, revision)
