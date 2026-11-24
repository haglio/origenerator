from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from origenerator.prompt_checks import things_of

_MOST_THINGS_AN_EDIT_ADDS = 4
_FEWEST_THINGS_BEFORE_AN_EDIT = 3
_NEAREST_EDITS_ASKED = 8
_SHARE_OF_THEM_THAT_BROUGHT_IT = 0.9
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
    kept_out: dict
    stands_after: dict
    made_from: int
    position: int


@dataclass(frozen=True)
class Addition:
    positive: tuple
    negative: tuple
    beside: str = ""


def _alike(one: frozenset, other: frozenset) -> float:
    shared = len(one & other)
    return shared / (len(one) + len(other) - shared) if shared else 0.0


def _counted(alike: float) -> float:
    return alike ** _HOW_MUCH_MORE_A_NEARER_ONE_COUNTS + _EVEN_THE_FARTHEST_COUNTS


def _the_prompt_it_was_made_from(things: frozenset, held_by: dict, earlier: list) -> int | None:
    shared = Counter(index for thing in things for index in held_by[thing])
    fits = [index for index, count in shared.items()
            if count == len(earlier[index][0]) >= _FEWEST_THINGS_BEFORE_AN_EDIT
            and 0 < len(things) - count <= _MOST_THINGS_AN_EDIT_ADDS]
    return max(fits, key=lambda index: (len(earlier[index][0]), index), default=None)


def edits_in(prompts) -> list[Edit]:
    read: list[tuple[dict, dict]] = []
    held_by: dict[str, list[int]] = defaultdict(list)
    edits = []
    for positive, negative in prompts:
        things, kept_out = things_of(positive), things_of(negative)
        source = _the_prompt_it_was_made_from(frozenset(things), held_by, read)
        if source is not None:
            before, before_kept_out = read[source]
            order = list(things)
            edits.append(Edit(
                frozenset(before),
                {thing: written for thing, written in things.items() if thing not in before},
                {thing: written for thing, written in kept_out.items() if thing not in before_kept_out},
                dict(zip(order[1:], order, strict=False)), source, len(read)))
        for thing in things:
            held_by[thing].append(len(read))
        read.append((things, kept_out))
    return edits


def _as_his_nearest_prompt_writes_it(names_it, prompts, there: dict) -> Addition | None:
    written: Counter = Counter()
    for positive, _negative in prompts:
        things = things_of(positive)
        counted = _counted(_alike(frozenset(there), frozenset(things)))
        for thing, as_written in things.items():
            if thing not in there and names_it(as_written):
                written[as_written] += counted
    return Addition((written.most_common(1)[0][0],), ()) if written else None


def _usually_brought(sides: list[tuple[dict, float]], there: dict, always=frozenset()) -> tuple:
    counted: Counter = Counter()
    as_written: dict[str, str] = {}
    for brought, weight in sides:
        for thing, written in brought.items():
            counted[thing] += weight
            as_written.setdefault(thing, written)
    whole = sum(weight for _brought, weight in sides)
    return tuple(as_written[thing] for thing, count in counted.most_common()
                 if thing not in there
                 and (thing in always or count / whole >= _SHARE_OF_THEM_THAT_BROUGHT_IT))


def _words(thing: str) -> set[str]:
    return {word for word in _WORD.findall(thing.casefold())
            if len(word) >= _SHORTEST_WORD and word not in _SAYING_NOTHING}


def _what_is_tied_to_it(names_it, prompts, there: dict, adding: tuple) -> tuple:
    with_it, without_it = [], Counter()
    others = 0
    for positive, _negative in prompts:
        things = things_of(positive)
        beside_it = {thing: written for thing, written in things.items() if not names_it(written)}
        said = set().union(*map(_words, beside_it)) if beside_it else set()
        if len(beside_it) < len(things):
            with_it.append((things, beside_it, said))
        else:
            others += 1
            without_it.update(said)
    if len(with_it) < _FEWEST_PROMPTS_WITH_IT:
        return ()
    beside = Counter(word for _things, _beside_it, said in with_it for word in said)
    said_already = set().union(*map(_words, [*there, *adding])) if there or adding else set()
    here = frozenset(there)
    brought = []
    for word, count in beside.most_common():
        share = count / len(with_it)
        if share < _SHARE_OF_ITS_PROMPTS_A_TIED_WORD_IS_IN:
            break
        elsewhere = without_it[word] / others if others else 0.0
        if word in said_already or elsewhere > _AT_MOST_THIS_MUCH_AS_COMMON_WITHOUT_IT * share:
            continue
        written: Counter = Counter()
        for things, beside_it, _said in with_it:
            counted = _counted(_alike(here, frozenset(things)))
            for thing, as_written in beside_it.items():
                if thing not in there and word in _words(thing):
                    written[as_written] += counted
        if written:
            part = written.most_common(1)[0][0]
            brought.append(part)
            said_already |= _words(part)
    return tuple(brought)


def the_way_he_adds(names_it, prompts, pair: tuple[str, str]) -> Addition | None:
    his = _the_way_his_edits_add(names_it, prompts, pair)
    if his is None:
        return None
    there = things_of(pair[0])
    tied_to_it = _what_is_tied_to_it(names_it, prompts, there, his.positive)
    return Addition((*tied_to_it, *his.positive), his.negative, his.beside)


def _the_way_his_edits_add(names_it, prompts, pair: tuple[str, str]) -> Addition | None:
    there, kept_out = things_of(pair[0]), things_of(pair[1])
    here = frozenset(there)
    adding_it = sorted(
        ((_alike(here, edit.before), position, edit)
         for position, edit in enumerate(edits_in(prompts))
         if any(names_it(written) for thing, written in edit.added.items() if thing not in there)
         and not any(names_it(thing) for thing in edit.before)),
        key=lambda found: (-found[0], -found[1]))[:_NEAREST_EDITS_ASKED]
    if not adding_it:
        return _as_his_nearest_prompt_writes_it(names_it, prompts, there)
    nearest = [(edit, _counted(alike)) for alike, _position, edit in adding_it]
    naming: Counter = Counter()
    for edit, weight in nearest:
        for thing, written in edit.added.items():
            if thing not in there and names_it(written):
                naming[thing] += weight
    the_thing = naming.most_common(1)[0][0]
    stands_after = next((edit.stands_after.get(the_thing) for edit, _weight in nearest
                         if edit.stands_after.get(the_thing) in there), None)
    return Addition(
        _usually_brought([(edit.added, weight) for edit, weight in nearest], there, {the_thing}),
        _usually_brought([(edit.kept_out, weight) for edit, weight in nearest], kept_out),
        beside=there[stands_after] if stands_after else "")
