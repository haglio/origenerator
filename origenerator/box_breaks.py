from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

from origenerator.prompt_diff import REMOVED, SAME, diff_spans

BOX_BREAK = "\x1e"
CARET = "\0"

_DEPTH = {"(": 1, ")": -1}


def prompt_boxes(text: str) -> list[str]:
    return text.split(BOX_BREAK)


def unboxed(text: str) -> str:
    return text.replace(BOX_BREAK, " ")


def parenthesis_at(text: str, index: int) -> int:
    return 0 if index and text[index - 1] == "\\" else _DEPTH.get(text[index], 0)


def flowed(boxes: list[str], tokens: Callable[[str], int], *, limit: int, start: int = 0,
           caret: tuple[int, int] | None = None) -> tuple[list[str], tuple[int, int] | None]:
    texts = list(boxes)
    if caret is not None:
        box, offset = caret
        texts[box] = texts[box][:offset] + CARET + texts[box][offset:]

    def fits(text: str) -> bool:
        return tokens(text.replace(CARET, "")) <= limit

    start = min(start - _drop_blank_boxes(texts, ahead_of=start), len(texts) - 1)
    if start > 0:
        _take_back_up(texts, start - 1, fits)
    index = max(start, 0)
    while index < len(texts):
        _push_on(texts, index, fits)
        _take_back_up(texts, index, fits)
        index += 1
    _drop_blank_boxes(texts)
    return _caret_taken_out(texts)


def cut_into_boxes(text: str, starts: list[int]) -> list[str]:
    bounds = [*starts[1:], len(text)]
    return [text[:bounds[0]].rstrip()] + [text[start:end].strip()
                                          for start, end in pairwise(bounds)]


def baselines_for(baseline: str, texts: list[str], whole: str | None = None) -> list[str]:
    whole = " ".join(texts) if whole is None else whole
    spans, position = [], 0
    for text in texts:
        start = whole.index(text, position)
        position = start + len(text)
        spans.append((start, position))
    owned = [""] * len(texts)
    position = 0
    for kind, piece in diff_spans(unboxed(baseline), whole):
        if kind == REMOVED:
            owned[_box_at(spans, position)] += piece
            continue
        for char in piece:
            box = next((index for index, (start, end) in enumerate(spans)
                        if start <= position < end), None)
            if kind == SAME and box is not None:
                owned[box] += char
            position += 1
    return owned


def _box_at(spans: list[tuple[int, int]], position: int) -> int:
    return next((index for index, (_start, end) in enumerate(spans) if position <= end),
                len(spans) - 1)


def _wordless(text: str) -> bool:
    return not text.replace(CARET, "").strip()


def _drop_blank_boxes(texts: list[str], *, ahead_of: int = 0) -> int:
    dropped_ahead = dropped = index = 0
    while index < len(texts) and len(texts) > 1:
        if not _wordless(texts[index]):
            index += 1
            continue
        if index + dropped < ahead_of:
            dropped_ahead += 1
        held = CARET in texts.pop(index)
        dropped += 1
        if held:
            if index > 0:
                texts[index - 1] += CARET
            else:
                texts[0] = CARET + texts[0]
    return dropped_ahead


def _spacing(text: str, index: int) -> bool:
    char = text[index]
    if char != CARET:
        return char.isspace()
    return not any(0 <= at < len(text) and not text[at].isspace() and text[at] != CARET
                   for at in (index - 1, index + 1))


def _units(text: str) -> list[str]:
    units, current, depth, spaced = [], "", 0, False
    for index, char in enumerate(text):
        if _spacing(text, index):
            spaced = spaced or depth == 0
        else:
            if spaced and not _wordless(current):
                units.append(current)
                current = ""
            spaced = False
        current += char
        depth = max(0, depth + parenthesis_at(text, index))
    if current:
        units.append(current)
    return units


def _most_that_fit(units: list[str], fits: Callable[[str], bool]) -> int:
    low, high = 1, len(units)
    while low < high:
        middle = (low + high + 1) // 2
        if fits("".join(units[:middle])):
            low = middle
        else:
            high = middle - 1
    return low


def _ends_a_thing(text: str) -> bool:
    return text.replace(CARET, "").rstrip().endswith(",")


def _things(text: str) -> list[str]:
    things, current = [], ""
    for unit in _units(text):
        current += unit
        if _ends_a_thing(unit):
            things.append(current)
            current = ""
    return [*things, current] if current else things


def _kept_and_pushed_on(text: str, its_last_goes_on: str,
                        fits: Callable[[str], bool]) -> tuple[str, str]:
    things = _things(text)
    whole = _most_that_fit(things, fits) if fits(things[0]) else 0
    kept, pushed_on = things[:whole], things[whole:]
    goes_on = its_last_goes_on if len(pushed_on) == 1 else ""
    if not pushed_on or fits(_joined(pushed_on[0].strip(), goes_on)):
        return "".join(kept), "".join(pushed_on)
    start = ["".join(kept)] if kept else []
    words = _units(pushed_on[0])
    of_its_words = _most_that_fit([*start, *words], fits) - len(start)
    return ("".join(kept + words[:of_its_words]),
            "".join(words[of_its_words:] + pushed_on[1:]))


def _where_its_last_goes_on(texts: list[str], index: int) -> str:
    goes_on = (index + 1 < len(texts) and not _ends_a_thing(texts[index])
               and not _wordless(texts[index + 1]))
    return _things(texts[index + 1])[0].strip() if goes_on else ""


def _cut_short(texts: list[str], index: int, fits: Callable[[str], bool]) -> str:
    things, goes_on = _things(texts[index]), _where_its_last_goes_on(texts, index)
    if len(things) < 2 or not goes_on:
        return ""
    whole_fits_a_box = fits(_joined(things[-1].strip(), goes_on))
    return things[-1] if whole_fits_a_box and not fits(_joined(texts[index], goes_on)) else ""


def _push_on(texts: list[str], index: int, fits: Callable[[str], bool]) -> None:
    if not texts[index]:
        return
    cut_short = _cut_short(texts, index, fits)
    kept, pushed_on = _kept_and_pushed_on(
        texts[index][:len(texts[index]) - len(cut_short)],
        "" if cut_short else _where_its_last_goes_on(texts, index), fits)
    words = (pushed_on + cut_short).strip()
    if not words:
        return
    texts[index] = kept.rstrip()
    if index + 1 == len(texts):
        texts.append(words)
    else:
        texts[index + 1] = _joined(words, texts[index + 1])


def _first_to_take_up(texts: list[str], index: int, fits: Callable[[str], bool]) -> str:
    text, following = texts[index], texts[index + 1]
    things = _things(following)
    thing = things[0]
    if fits(_joined(text, thing.strip())):
        return thing
    begun = "" if _ends_a_thing(text) or not text else _things(text)[-1]
    goes_on = _where_its_last_goes_on(texts, index + 1) if len(things) == 1 else ""
    too_long_for_a_box = not fits(_joined(_joined(begun.strip(), thing.strip()), goes_on))
    word = _units(following)[0]
    return word if too_long_for_a_box and fits(_joined(text, word.strip())) else ""


def _take_back_up(texts: list[str], index: int, fits: Callable[[str], bool]) -> None:
    while index + 1 < len(texts):
        if _wordless(texts[index + 1]):
            texts[index] += texts.pop(index + 1).strip()
            continue
        taken = _first_to_take_up(texts, index, fits)
        if not taken:
            return
        texts[index] = _joined(texts[index], taken.strip())
        texts[index + 1] = texts[index + 1][len(taken):].lstrip()


def _joined(before: str, after: str) -> str:
    if _wordless(before):
        return before.strip() + after.lstrip()
    if _wordless(after):
        return before + after.strip()
    return f"{before.rstrip()} {after.lstrip()}"


def _caret_taken_out(texts: list[str]) -> tuple[list[str], tuple[int, int] | None]:
    caret = next(((box, text.index(CARET)) for box, text in enumerate(texts) if CARET in text),
                 None)
    return [text.replace(CARET, "") for text in texts], caret
