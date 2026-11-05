from __future__ import annotations

import re

from origenerator.box_breaks import BOX_BREAK, parenthesis_at
from origenerator.prompt_edit import terms_with_places

_NUMBER = re.compile(r"\d+(\.\d+)?|\.\d+")
_ENDS_A_GROUP = re.compile(r":([^:()]*)(?<!\\)\)")
_OUTSIDE_ITS_PARENTHESES = re.compile(r"\)[ \t]*:[ \t]*[\d.]+")
_NO_PARENTHESES = re.compile(r"(?<=[^\W\d_]):[\d.]+(?=[ \t]*(?:,|$))", re.MULTILINE)
_A_THING = re.compile(r"[^,]+")
_STACK = re.compile(r"(?<!\\)(\({2,})([^()]*)(\)+)")
_WEIGHT_CLOSING_A_GROUP = re.compile(r"[ \t]*:[ \t]*[\d.]+[ \t]*(?=\))")
_ONE_PARENTHESIS_ADDS = 1.1
_ENDS = " ,\n" + BOX_BREAK


def unpaired_parentheses(text: str) -> tuple[int, ...]:
    opened, closed_alone = [], []
    for index in range(len(text)):
        parenthesis = parenthesis_at(text, index)
        if parenthesis > 0:
            opened.append(index)
        elif parenthesis < 0:
            if opened:
                opened.pop()
            else:
                closed_alone.append(index)
    return tuple(sorted(opened + closed_alone))


def bad_weights(text: str) -> tuple[tuple[int, int], ...]:
    unpaired = unpaired_parentheses(text)
    spans = {match.span() for match in _ENDS_A_GROUP.finditer(text)
             if not _NUMBER.fullmatch(match[1].strip())
             or match.end() - 1 in unpaired
             or text[match.start() - 1:match.start()] == "("}
    spans.update(match.span() for match in _OUTSIDE_ITS_PARENTHESES.finditer(text))
    spans.update(match.span() for match in _NO_PARENTHESES.finditer(text))
    return tuple(sorted(spans))


def unread_emphasis(text: str) -> tuple[tuple[int, int], ...]:
    opened, outermost = [], []
    for index in range(len(text)):
        parenthesis = parenthesis_at(text, index)
        if parenthesis > 0:
            opened.append(index)
        elif parenthesis < 0 and opened:
            start = opened.pop()
            outermost = [span for span in outermost if span[0] < start]
            outermost.append((start, index + 1))
    return tuple(outermost)


def without_emphasis(text: str) -> str:
    pieces, last = [], 0
    for start, end in unread_emphasis(text):
        group = _WEIGHT_CLOSING_A_GROUP.sub("", text[start:end])
        words = "".join(character for index, character in enumerate(group)
                        if not parenthesis_at(group, index))
        pieces += [text[last:start], words.strip()]
        last = end
    return "".join(pieces) + text[last:]


def _the_thing_itself(text: str) -> str:
    return " ".join(text.split()).casefold()


def duplicate_things(text: str) -> tuple[tuple[int, int], ...]:
    places: dict[str, list[tuple[int, int]]] = {}
    for match in _A_THING.finditer(text):
        thing = _the_thing_itself(match[0])
        if thing:
            start = match.start() + len(match[0]) - len(match[0].lstrip())
            end = match.end() - len(match[0]) + len(match[0].rstrip())
            places.setdefault(thing, []).append((start, end))
    return tuple(sorted(span for spans in places.values() if len(spans) > 1 for span in spans))


def things_in_both(text: str, other: str) -> tuple[tuple[int, int], ...]:
    theirs = {_the_thing_itself(term) for term, _start, _end in terms_with_places(other)} - {""}
    return tuple((start, end) for term, start, end in terms_with_places(text)
                 if _the_thing_itself(term) in theirs)


def _as_a_number(match: re.Match) -> str:
    if len(match[1]) != len(match[3]):
        return match[0]
    words, colon, number = match[2].rpartition(":")
    if colon and _NUMBER.fullmatch(number.strip()):
        return f"({words.strip()}:{number.strip()})"
    weight = f"{_ONE_PARENTHESIS_ADDS ** len(match[1]):.3f}".rstrip("0")
    return f"({match[2].strip()}:{weight})"


def _one_comma(match: re.Match) -> str:
    return "," + (BOX_BREAK if BOX_BREAK in match[0] else "\n" if "\n" in match[0] else "")


def tidied(text: str, *, reads_numbers: bool = False) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(rf" *([\n{BOX_BREAK}]) *", r"\1", text)
    text = re.sub(r" +,", ",", text)
    text = re.sub(rf",(?:[ \n{BOX_BREAK}]*,)+", _one_comma, text)
    text = re.sub(r",(?=[^\W\d_]|\()", ", ", text)
    if reads_numbers:
        text = _STACK.sub(_as_a_number, text)
    return text.strip(_ENDS)
