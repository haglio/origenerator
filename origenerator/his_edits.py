from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from origenerator.prompt_checks import things_of

_MOST_THINGS_AN_EDIT_ADDS = 4
_FEWEST_THINGS_BEFORE_AN_EDIT = 3
_HIS_LATEST_PROMPTS_WITH_IT = 100
_NEAREST_OF_THEM = 8
_HOW_MUCH_MORE_A_NEARER_ONE_COUNTS = 3
_EVEN_THE_FARTHEST_COUNTS = 0.001
_FEWEST_PROMPTS_WITH_IT = 400
_SHARE_OF_ITS_PROMPTS_A_TIED_WORD_IS_IN = 0.7
_AT_MOST_THIS_MUCH_AS_COMMON_WITHOUT_IT = 0.1
_SHORTEST_WORD = 3
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_SAYING_NOTHING = frozenset({
    "the", "and", "with", "her", "his", "their", "its", "she", "they", "him", "them", "for", "from",
    "into", "onto", "that", "this", "are", "was", "very", "has", "have", "who", "whose", "while"})


@dataclass(frozen=True)
class Edit:
    before: frozenset
    added: dict
    made_from: int
    position: int


@dataclass(frozen=True)
class Addition:
    positive: tuple
    negative: tuple
    beside: str = ""


@dataclass(frozen=True)
class _PromptWithIt:
    things: dict
    naming_it: dict
    keeping_it_out: dict

    @property
    def beside_it(self) -> dict:
        return {thing: written for thing, written in self.things.items() if thing not in self.naming_it}

    def stands_after(self) -> str | None:
        order = list(self.things)
        first = min(order.index(thing) for thing in self.naming_it)
        return order[first - 1] if first else None


@dataclass(frozen=True)
class _HisPrompts:
    with_it: list
    said_without_it: Counter
    without_it: int


def _alike(one, other) -> float:
    shared = len(one & other)
    return shared / (len(one) + len(other) - shared) if shared else 0.0


def _counted(alike: float) -> float:
    return alike ** _HOW_MUCH_MORE_A_NEARER_ONE_COUNTS + _EVEN_THE_FARTHEST_COUNTS


def _the_prompt_it_was_made_from(things: frozenset, held_by: dict, earlier: list) -> int | None:
    shared = Counter(index for thing in things for index in held_by[thing])
    fits = [index for index, count in shared.items()
            if count == len(earlier[index]) >= _FEWEST_THINGS_BEFORE_AN_EDIT
            and 0 < len(things) - count <= _MOST_THINGS_AN_EDIT_ADDS]
    return max(fits, key=lambda index: (len(earlier[index]), index), default=None)


def edits_in(prompts) -> list[Edit]:
    read: list[dict] = []
    held_by: dict[str, list[int]] = defaultdict(list)
    edits = []
    for positive, _negative in prompts:
        things = things_of(positive)
        source = _the_prompt_it_was_made_from(frozenset(things), held_by, read)
        if source is not None:
            before = read[source]
            edits.append(Edit(
                frozenset(before),
                {thing: written for thing, written in things.items() if thing not in before},
                source, len(read)))
        for thing in things:
            held_by[thing].append(len(read))
        read.append(things)
    return edits


def words_in_order(text: str) -> list[str]:
    return [word for word in _WORD.findall(text.casefold()) if len(word) >= _SHORTEST_WORD]


def _words(thing: str) -> set[str]:
    return set(words_in_order(thing)) - _SAYING_NOTHING


def _said_in(things) -> set[str]:
    return set().union(*map(_words, things)) if things else set()


def _read_for(names_it, prompts) -> _HisPrompts:
    with_it, said_without_it = [], Counter()
    without_it = 0
    for positive, negative in prompts:
        things = things_of(positive)
        naming_it = {thing: written for thing, written in things.items() if names_it(written)}
        if naming_it:
            with_it.append(_PromptWithIt(things, naming_it, {
                thing: written for thing, written in things_of(negative).items() if names_it(written)}))
        else:
            without_it += 1
            said_without_it.update(_said_in(things))
    return _HisPrompts(with_it, said_without_it, without_it)


def _most_like_this_one(with_it: list, here: frozenset) -> _PromptWithIt:
    nearest = sorted(enumerate(with_it[-_HIS_LATEST_PROMPTS_WITH_IT:]),
                     key=lambda found: (-_alike(here, frozenset(found[1].beside_it)), -found[0]))
    nearest = [his for _position, his in nearest[:_NEAREST_OF_THEM]]
    said = [_said_in([*his.naming_it, *his.keeping_it_out]) for his in nearest]

    def as_the_others_word_it(place: int) -> float:
        return sum(_alike(said[place], other) for at, other in enumerate(said) if at != place)

    return nearest[max(range(len(nearest)), key=lambda place: (as_the_others_word_it(place), -place))]


def _what_is_tied_to_it(his: _HisPrompts, there: dict, adding: tuple) -> tuple:
    if len(his.with_it) < _FEWEST_PROMPTS_WITH_IT:
        return ()
    said_beside_it = [_said_in(prompt.beside_it) for prompt in his.with_it]
    beside = Counter(word for said in said_beside_it for word in said)
    said_already = _said_in([*there, *adding])
    here = frozenset(there)
    brought = []
    for word, count in beside.most_common():
        share = count / len(his.with_it)
        if share < _SHARE_OF_ITS_PROMPTS_A_TIED_WORD_IS_IN:
            break
        elsewhere = his.said_without_it[word] / his.without_it if his.without_it else 0.0
        if word in said_already or elsewhere > _AT_MOST_THIS_MUCH_AS_COMMON_WITHOUT_IT * share:
            continue
        written: Counter = Counter()
        for prompt in his.with_it:
            counted = _counted(_alike(here, frozenset(prompt.things)))
            for thing, as_written in prompt.beside_it.items():
                if thing not in there and word in _words(thing):
                    written[as_written] += counted
        if written:
            part = written.most_common(1)[0][0]
            brought.append(part)
            said_already |= _words(part)
    return tuple(brought)


def the_way_he_adds(names_it, prompts, pair: tuple[str, str]) -> Addition | None:
    there, kept_out = things_of(pair[0]), things_of(pair[1])
    his = _read_for(names_it, prompts)
    if not his.with_it:
        return None
    like_this = _most_like_this_one(his.with_it, frozenset(there))
    naming_it = tuple(written for thing, written in like_this.naming_it.items() if thing not in there)
    if not naming_it:
        return None
    return Addition(
        (*_what_is_tied_to_it(his, there, naming_it), *naming_it),
        tuple(written for thing, written in like_this.keeping_it_out.items() if thing not in kept_out),
        beside=there.get(like_this.stands_after(), ""))
