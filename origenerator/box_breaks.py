from __future__ import annotations

from collections.abc import Callable

from origenerator.prompt_diff import REMOVED, SAME, diff_spans

BOX_BREAK = "\x1e"
CARET = "\0"

_DEPTH = {"(": 1, ")": -1}


def prompt_boxes(text: str) -> list[str]:
    return text.split(BOX_BREAK)


def unboxed(text: str) -> str:
    return text.replace(BOX_BREAK, " ")


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
                                          for start, end in zip(bounds, bounds[1:])]


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
        if not (index and text[index - 1] == "\\"):
            depth = max(0, depth + _DEPTH.get(char, 0))
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


def _push_on(texts: list[str], index: int, fits: Callable[[str], bool]) -> None:
    units = _units(texts[index])
    kept = _most_that_fit(units, fits) if len(units) > 1 else len(units)
    if kept == len(units):
        return
    texts[index] = "".join(units[:kept]).rstrip()
    words = "".join(units[kept:]).strip()
    if index + 1 == len(texts):
        texts.append(words)
    else:
        texts[index + 1] = _joined(words, texts[index + 1])


def _take_back_up(texts: list[str], index: int, fits: Callable[[str], bool]) -> None:
    while index + 1 < len(texts):
        if _wordless(texts[index + 1]):
            texts[index] += texts.pop(index + 1).strip()
            continue
        following = _units(texts[index + 1])
        merged = _joined(texts[index], following[0].strip())
        if not fits(merged):
            return
        texts[index] = merged
        texts[index + 1] = "".join(following[1:]).lstrip()


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
