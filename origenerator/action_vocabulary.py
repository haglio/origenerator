from __future__ import annotations

from typing import NamedTuple

from funestra.video_families import normalized_text

from origenerator.content import load_content
from origenerator.item_actions import ItemActions
from origenerator.media import MediaType

_BLOCKS = {MediaType.IMAGE: "image_actions", MediaType.VIDEO: "video_actions"}


class Tile(NamedTuple):
    name: str
    row: int
    column: int
    columns: int = 1
    rows: int = 1


def names_in(listed) -> tuple[str, ...]:
    if not isinstance(listed, list):
        return ()
    return tuple(dict.fromkeys(
        name.strip() for name in listed if isinstance(name, str) and name.strip()))


def _buttons(listed) -> dict[str, tuple[str, ...]]:
    return {name.strip(): names_in(actions) for name, actions in _table(listed).items()
            if isinstance(name, str) and name.strip() and isinstance(actions, list)}


def _table(listed) -> dict:
    return listed if isinstance(listed, dict) else {}


def _item_actions(said) -> ItemActions | None:
    if not isinstance(said, dict):
        return None
    return ItemActions(names_in(said.get("actions")), names_in(said.get("checked")))


def _reach(entry) -> tuple[str, int, int]:
    if isinstance(entry, str):
        return entry.strip(), 1, 1
    if isinstance(entry, list) and entry and isinstance(entry[0], str):
        spans = [n if isinstance(n, int) and n > 0 else 1 for n in entry[1:3]]
        return (entry[0].strip(), *spans, *(1,) * (2 - len(spans)))
    return "", 1, 1


def tiles(names: tuple[str, ...], arranged) -> tuple[Tile, ...]:
    placed: dict[str, Tile] = {}
    down = 0
    for row in arranged if isinstance(arranged, list) else ():
        if not isinstance(row, list):
            continue
        across = 0
        for entry in row:
            name, columns, rows = _reach(entry)
            if name in names and name not in placed:
                placed[name] = Tile(name, down, across, columns, rows)
            across += columns
        down += 1
    left_over = (name for name in names if name not in placed)
    return (*placed.values(), *(Tile(name, down, across) for across, name in enumerate(left_over)))


JOINER = " + "


def said_as(name: str) -> str:
    return name.replace(JOINER, " plus ").lower()


class Vocabulary(NamedTuple):
    buttons: dict[str, tuple[str, ...]]
    tiles: tuple[Tile, ...]
    checkboxes: tuple[str, ...]
    formerly: dict[str, ItemActions]
    drawn_as: dict[str, str]
    heard_as: dict[str, tuple[str, ...]]
    said_alone: dict[str, str]

    def read_as(self, said: str) -> ItemActions | None:
        heard = normalized_text(said)
        button = next((name for name in self.buttons if normalized_text(name) == heard), None)
        if button is not None:
            return ItemActions(self.buttons[button])
        return next((item_actions for name, item_actions in self.formerly.items()
                     if normalized_text(name) == heard), None)

    def button_made_of(self, actions) -> str:
        wanted = frozenset(actions)
        return next((button for button, made_of in self.buttons.items()
                     if wanted and frozenset(made_of) == wanted), "")

    def spoken_forms(self, said: str) -> tuple[str, ...]:
        forms = [said]
        for name, heard in self.heard_as.items():
            own = f" {said_as(name)} "
            forms.extend(f" {form} ".replace(own, f" {other.lower()} ").strip()
                         for form in list(forms) if own in f" {form} " for other in heard)
        return tuple(dict.fromkeys(forms))

    def drawing_name(self, button: str) -> str:
        return self.drawn_as.get(button, button)

    @property
    def plain_actions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(action for made_of in self.buttons.values() for action in made_of))


def vocabulary(side: str, content: dict | None = None) -> Vocabulary:
    if content is None:
        content = load_content()
    block = _table(content.get(_BLOCKS[side]))
    buttons = _buttons(block.get("buttons"))
    formerly = {name.strip(): item_actions for name, said in _table(block.get("formerly")).items()
                if isinstance(name, str) and (item_actions := _item_actions(said)) is not None}
    checkboxes = names_in(block.get("checkboxes"))
    return Vocabulary(buttons, tiles(tuple(buttons), block.get("grid")), checkboxes, formerly,
                      _named_strings(block.get("drawn_as")), _buttons(block.get("heard_as")),
                      {box: button for box, button in _named_strings(block.get("said_alone")).items()
                       if box in checkboxes and button in buttons})


def _named_strings(listed) -> dict[str, str]:
    return {name.strip(): said.strip() for name, said in _table(listed).items()
            if isinstance(name, str) and isinstance(said, str) and said.strip()}


def actions_heard_as(content: dict | None = None) -> dict[str, tuple[str, ...]]:
    heard: dict[str, tuple[str, ...]] = {}
    for side in (MediaType.IMAGE, MediaType.VIDEO):
        words = vocabulary(side, content)
        for name in (*words.plain_actions, *words.checkboxes):
            heard[name] = tuple(dict.fromkeys((*heard.get(name, (name,)), *words.heard_as.get(name, ()))))
    return heard
