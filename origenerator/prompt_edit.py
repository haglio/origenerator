from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from functools import partial
from urllib.error import HTTPError

from origenerator import local_llm, request_settings
from origenerator.box_breaks import unboxed
from origenerator.collection_notes import CollectionNotes
from origenerator.config import (
    LOCAL_LLM_BASE_URL,
    REQUEST_LLM_MODEL,
    REQUEST_MODEL_STAYS_LOADED_S,
)
from origenerator.db_requests import Turn
from origenerator.his_edits import the_way_he_adds
from origenerator.prompt_checks import things_of
from origenerator.prompt_terms import without_nothing_weighted
from origenerator.prompts import REQUEST_SYSTEM_PROMPT
from origenerator.request_changes import Prompts, apply_changes, words_of_his
from origenerator.workflows.base import scene_prompts, scene_text, story_of

logger = logging.getLogger(__name__)

ADD = "add"
REMOVE = "remove"

REWRITTEN = "rewritten"
UNANSWERED = "unanswered"
NO_ANSWER = "The model couldn't answer, so nothing changed."
NO_GRAPHICS_CARD = "The model couldn't get the graphics card, so nothing changed."

_WINDOWS_TOKENS = (8192, 16384, 32768)
_ANSWER_TOKENS = 512
_CHARACTERS_A_TOKEN = 3.5
_NOTES_CHARS = 3000
_ASK_TIMEOUT_S = 180.0


def _both_spellings(words: set) -> frozenset:
    # Whisper punctuates contractions either way (don't, dont)
    return frozenset(words | {word.replace("'", "") for word in words})


_REMOVE_PHRASES = (("get", "rid", "of"), ("get", "rid"), ("take", "off"),
                   ("take", "away"), ("do", "away", "with"))
_REMOVE_WORDS = _both_spellings({
    "no", "not", "none", "never", "without", "remove", "removing", "drop",
    "lose", "hide", "avoid", "stop", "skip", "ditch", "cut", "minus",
    "don't", "doesn't", "won't", "less", "fewer",
})
_ADD_WORDS = _both_spellings({
    "more", "add", "adding", "give", "want", "with", "include", "including",
    "put", "increase", "boost", "extra",
})
_FILLER = frozenset({
    "please", "ok", "okay", "so", "um", "uh", "and", "also", "then", "just",
    "maybe", "can", "could", "would", "you", "i", "we", "let", "lets", "us",
    "really", "much", "many", "of", "on", "her", "his", "their", "its", "my",
    "our", "your", "the", "a", "an", "this", "that", "these", "those", "some",
    "any", "it", "them", "there", "have", "has", "make", "makes", "be",
})
_TRAILING = frozenset({"please", "thanks", "thank", "you", "now", "instead"})

_WORD = re.compile(r"[A-Za-z0-9'\-]+")


def _tokens(text: str) -> list:
    return [(m.group(0).lower(), m.start(), m.end()) for m in _WORD.finditer(text or "")]


def _phrase_at(tokens: list, index: int) -> int:
    for phrase in _REMOVE_PHRASES:
        end = index + len(phrase)
        if end <= len(tokens) and tuple(t[0] for t in tokens[index:end]) == phrase:
            return len(phrase)
    return 0


def parse_request(request: str) -> tuple | None:
    tokens = _tokens(request)
    polarity = None
    index = 0
    while index < len(tokens):
        word = tokens[index][0]
        span = _phrase_at(tokens, index)
        if span:
            polarity = polarity or REMOVE
            index += span
        elif word in _REMOVE_WORDS:
            polarity = polarity or REMOVE
            index += 1
        elif word in _ADD_WORDS:
            polarity = polarity or ADD
            index += 1
        elif word in _FILLER:
            index += 1
        else:
            break
    end = len(tokens)
    while end > index and tokens[end - 1][0] in _TRAILING:
        end -= 1
    if index >= end:
        return None
    term = request[tokens[index][1]:tokens[end - 1][2]].strip()
    return (polarity or ADD), term



@dataclass(frozen=True)
class PromptRevision:
    old_positive: str
    old_negative: str
    positive: str
    negative: str
    term: str
    polarity: str
    action: str
    answer: str = ""
    settings: tuple = ()
    setting_changes: tuple = ()

    @property
    def changed(self) -> bool:
        return (self.positive != self.old_positive
                or self.negative != self.old_negative
                or bool(self.settings))

    def turn(self, said: str) -> Turn:
        return Turn(said, self.answer, self.old_positive, self.old_negative, self.positive,
                    self.negative, request_settings.recorded(self.setting_changes))


def _scenes_of(positive: str, negative: str) -> tuple[list[str], list[str]]:
    scenes = scene_prompts(positive)
    negatives = scene_prompts(negative)
    return scenes, [scene_text(negatives, index) for index in range(len(scenes))]


def _joined(positive: str, negative: str, each_negative: list[str], parsed: tuple,
            revisions: list[PromptRevision]) -> PromptRevision:
    polarity, term = parsed
    if len(revisions) == 1:
        return revisions[0]
    return PromptRevision(
        positive, negative, story_of([revision.positive for revision in revisions]),
        _negative_story(negative, each_negative, [revision.negative for revision in revisions]),
        term, polarity, ", ".join(dict.fromkeys(revision.action for revision in revisions)),
        " ".join(dict.fromkeys(revision.answer for revision in revisions if revision.answer)),
        revisions[0].settings, revisions[0].setting_changes)


def unanswered(positive: str, negative: str, request: str,
               why: str = NO_ANSWER) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = unboxed(positive or ""), unboxed(negative or "")
    return PromptRevision(positive, negative, positive, negative, parsed[1], parsed[0], UNANSWERED, why)


def _negative_story(negative: str, before: list[str], after: list[str]) -> str:
    if after == before:
        return negative
    if len(set(after)) == 1:
        return after[0]
    return story_of(after)


@dataclass(frozen=True)
class WhatIsKnown:
    exchange: tuple = ()
    notes: CollectionNotes | None = None
    examples: tuple = ()
    settings: tuple = ()
    weights: bool = True
    his_prompts: tuple = ()


def work_out(positive: str, negative: str, request: str, *, in_scenes: bool = False, ask=None,
             **known) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = unboxed(positive or ""), unboxed(negative or "")
    scenes, each_negative = (_scenes_of(positive, negative) if in_scenes
                             else ([positive], [negative]))
    told = WhatIsKnown(**known)
    asked = [request, *(turn[0] for turn in told.exchange)]
    revisions = []
    for scene, scene_negative in zip(scenes, each_negative, strict=True):
        revision = _answered((scene, scene_negative), parsed,
                             partial(ask or answer_to, scene, scene_negative, request, told),
                             told, asked)
        if revision is None:
            return unanswered(positive, negative, request)
        revisions.append(revision)
    return _joined(positive, negative, each_negative, parsed, revisions)


def _answered(pair: tuple[str, str], parsed: tuple, asking, told: WhatIsKnown,
              asked: list[str]) -> PromptRevision | None:
    positive, negative = pair
    polarity, term = parsed
    try:
        answer = asking()
    except Exception as exc:  # noqa: BLE001 -- model down or unreadable: the rules' own edit stands
        logger.warning("prompt_edit: the model could not answer the request (%s)",
                       type(exc).__name__)
        return None
    if not isinstance(answer, dict):
        return None
    settings = told.settings
    outcome = apply_changes(answer, pair, asked=asked, settings=settings,
                            prompts=Prompts(take_weights=told.weights, his_words=_his_words(told)))
    return PromptRevision(positive, negative, without_nothing_weighted(outcome.positive),
                          without_nothing_weighted(outcome.negative), term, polarity, REWRITTEN,
                          outcome.line, tuple(outcome.settings.items()),
                          tuple(request_settings.described(outcome.settings, settings)))


def _his_words(told: WhatIsKnown) -> frozenset:
    notes = told.notes.as_told() if told.notes is not None and told.notes.complete else ""
    return words_of_his([positive for positive, _negative in told.examples] + [notes])


_SHORTEST_ROOT = 3
_NAMING_NOTHING = _FILLER | _ADD_WORDS | _REMOVE_WORDS | _TRAILING | _both_spellings({
    "she", "he", "him", "they", "in", "into", "at", "for", "from", "by", "to", "is", "are",
    "was", "isn't", "wasn't", "aren't", "did", "didn't", "does", "do", "doing", "get", "gets",
    "getting", "gives", "giving", "gave", "appear", "appears", "appeared", "show", "shows",
    "showed", "showing", "up", "still", "see", "missing", "again", "one", "same", "other",
})


def _roots(word: str) -> set[str]:
    roots = {word}
    for ending in ("s", "es", "ing", "ed"):
        if word.endswith(ending) and len(word) - len(ending) >= _SHORTEST_ROOT:
            root = word[:-len(ending)]
            roots |= {root, root + "e"}
    return roots


def _forms(word: str) -> set[str]:
    forms = set()
    for root in _roots(word):
        stem = root.removesuffix("e")
        forms |= {root, root + "s", root + "es", root + "d", stem + "ing", stem + "ed",
                  stem + stem[-1] + "ing", stem + stem[-1] + "ed"}
    return forms


def _asked_about(request: str) -> list[set[str]]:
    words = dict.fromkeys(word for word, *_ in _tokens(request))
    return [_forms(word) for word in words
            if len(word) >= _SHORTEST_ROOT and word not in _NAMING_NOTHING]


def _touches(asked: list[set[str]], prompt: str) -> int:
    words = {word for word, *_ in _tokens(prompt)}
    return sum(1 for forms in asked if forms & words)


def prompts_touching(request: str, prompts, *, limit: int = 8,
                     limit_chars: int = 6000) -> list[tuple[str, str]]:
    asked = _asked_about(request)
    scored = sorted((-_touches(asked, positive), position, (positive, negative))
                    for position, (positive, negative) in enumerate(prompts))
    chosen, used = [], 0
    for score, _position, pair in scored:
        if score == 0 or len(chosen) == limit:
            break
        if used + len(pair[0]) + len(pair[1]) <= limit_chars:
            chosen.append(pair)
            used += len(pair[0]) + len(pair[1])
    return chosen


_BETWEEN_THINGS_ASKED_FOR = re.compile(r",|&|(?<!\w)and(?!\w)", re.IGNORECASE)


def _each_thing_asked_for(request: str) -> list[list[set[str]]]:
    return [asked for thing in _BETWEEN_THINGS_ASKED_FOR.split(request)
            if (asked := _asked_about(thing))]


def known_from(his_prompts, request: str) -> dict:
    return {"examples": prompts_touching(request, reversed(his_prompts)),
            "his_prompts": tuple(his_prompts)}


def _notes_touching(request: str, notes: CollectionNotes) -> str:
    asked = _asked_about(request)
    touching = sorted((-_touches(asked, note), position, note)
                      for position, note in enumerate(notes.batch_notes))
    return replace(notes, batch_notes=[note for score, _position, note in touching
                                       if score]).as_told(_NOTES_CHARS)


def _window_tokens(messages: list[dict]) -> int:
    needed = sum(len(message["content"]) for message in messages) / _CHARACTERS_A_TOKEN
    return next((window for window in _WINDOWS_TOKENS if needed + _ANSWER_TOKENS <= window),
                _WINDOWS_TOKENS[-1])


def _numbered(examples) -> str:
    return "\n".join(f"{number}. {positive}" + (f"\n   negative: {negative}" if negative else "")
                     for number, (positive, negative) in enumerate(examples, 1))




_ANSWER_SHAPE = (
    'Reply with only a JSON object: {"changes": [...]}. Each change is one of: '
    '{"setting": "<key>", "to": <value>, "for": "<his words>"} to set a setting, by its [key] and '
    'within its range or choices; {"prompt": "positive" or "negative", "replace": "<words now in '
    'that prompt>", "with": "<new words>", "for": "<his words>"}; {"prompt": ..., "add": "<new '
    'words>", "after": "<words now in that prompt they belong beside>", "for": "<his words>"}; '
    '{"prompt": ..., "remove": "<words now in that prompt>", "for": "<his words>"}; '
    '{"more": "<the part of the positive prompt that says the thing he wants more of, exactly as '
    'written, or empty>", "stronger": "<that part in his own stronger words>", "opposite": '
    '"<what the image shows in its place>", "for": "<his words>"} for more of something; '
    '{"gone": "<the thing he wants gone, bare>", "in_positive": "<every part of the positive '
    'prompt that says it or a kind of it, exactly as written, comma-separated, or empty>", '
    '"instead": "<what the image shows in its place, or empty>", "for": "<his words>"} for '
    'something gone. "for" quotes the words of his, from this request or an earlier one, that '
    'the change answers; a change answering none of his words is thrown away. When nothing '
    'should change, "changes" is an empty list and "why" says to him, in one sentence, why '
    'nothing should change.')


_NO_WEIGHTS = (
    "THESE PROMPTS TAKE NO WEIGHTS: the image model ignores (term:weight), so never write one. "
    "For less of something, say it more mildly or remove it.")


def build_request_messages(positive: str, negative: str, request: str, known: WhatIsKnown,
                           system_prompt: str) -> list[dict]:
    parts = []
    if known.notes is not None and known.notes.complete:
        parts.append(_notes_touching(request, known.notes))
    if known.examples:
        parts.append("PROMPTS OF HIS THAT TOUCH WHAT HE ASKS FOR (how he writes such things; "
                     "carry over the details that go with them, and what his negative prompts keep "
                     f"out):\n{_numbered(known.examples)}")
    if known.settings:
        parts.append("SETTINGS HE MAY ALSO CHANGE (current values):\n"
                     + request_settings.as_told(known.settings))
    if not known.weights:
        parts.append(_NO_WEIGHTS)
    parts.append(f"CURRENT POSITIVE PROMPT:\n{positive}\n\nCURRENT NEGATIVE PROMPT:\n{negative}")
    parts.append(f"HE NOW ASKS:\n{request}")
    parts.append(_ANSWER_SHAPE)
    exchange = [message for turn in known.exchange
                for message in ({"role": "user", "content": turn[0]},
                                {"role": "assistant", "content": turn[1]})]
    return [{"role": "system", "content": system_prompt}, *exchange,
            {"role": "user", "content": "\n\n".join(parts)}]


_STAYS_LOADED = f"{REQUEST_MODEL_STAYS_LOADED_S + 60}s"

_LEFT_OPEN_CHECK = (
    'He asked: "{asked}". Your change writes "{new}" where the prompt said "{old}". '
    "List the words of yours in it that he did not say and that settle something he left open: "
    "which way a body lies or faces, a pose, a place, a person, a garment, a camera or a time that "
    "neither his words nor the prompt had. Words that only say more about the thing he asked for "
    "(its size, color, material, look) are not such words. "
    'Reply with only a JSON object: {{"left_open": ["<each such word or phrase, exactly as you '
    'wrote it>"]}}, an empty list when there are none.')
_PUT_INTO_A_PROMPT = ("with", "add")
_FAILED_TO_LOAD = 500


def _asked_again_if_the_model_failed_to_load(asking):
    try:
        return asking()
    except HTTPError as refused:
        if refused.code != _FAILED_TO_LOAD:
            raise
        logger.warning("prompt_edit: the model failed to load; asking once more")
        return asking()


def _without(words: str, phrase: str) -> str:
    gone = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", "", words, flags=re.IGNORECASE)
    parts = [" ".join(part.split()) for part in gone.split(",")]
    return ", ".join(part for part in parts if part)


def _he_said(phrase: str, request: str) -> bool:
    said = {word for word, *_ in _tokens(request)}
    return all(word in said for word, *_ in _tokens(phrase))


_ASKING_TO_ADD = frozenset({"add", "adding", "give", "include", "including", "put"})


def _thing_he_asks_to_add(request: str) -> str | None:
    asking = next((word for word, *_ in _tokens(request) if word not in _FILLER), None)
    parsed = parse_request(request) if asking in _ASKING_TO_ADD else None
    return parsed[1] if parsed is not None else None


def _part_he_names(request: str, positive: str) -> str | None:
    parsed, each = parse_request(request), _each_thing_asked_for(request)
    if parsed is None or parsed[0] != ADD or len(each) != 1:
        return None
    return next((part for part in things_of(positive).values()
                 if _touches(each[0], part) == len(each[0])), None)


def _adding_what_he_asked_for(answer: dict, request: str) -> dict:
    thing, changes = _thing_he_asks_to_add(request), answer.get("changes")
    only_the_negative_prompt = isinstance(changes, list) and bool(changes) and all(
        isinstance(change, dict) and change.get("prompt") == "negative" for change in changes)
    if thing is None or not only_the_negative_prompt:
        return answer
    return {**answer, "changes": [*changes, {"prompt": "positive", "add": thing, "for": request}]}


def _leaving_open_what_he_did(answer: dict, request: str, ask_again) -> dict:
    for change in answer.get("changes") or ():
        key = next((key for key in _PUT_INTO_A_PROMPT if change.get(key)), None)
        if key is None or change.get("prompt") != "positive":
            continue
        try:
            left_open = local_llm.answer_of(ask_again(_LEFT_OPEN_CHECK.format(
                asked=request, new=change[key], old=change.get("replace") or ""))).get("left_open")
        except Exception as exc:  # noqa: BLE001 -- the check is extra: the model's change stands
            logger.warning("prompt_edit: the model could not check its change (%s)",
                           type(exc).__name__)
            continue
        kept = str(change[key])
        for phrase in left_open if isinstance(left_open, list) else ():
            if isinstance(phrase, str) and phrase.strip() and not _he_said(phrase, request):
                kept = _without(kept, phrase.strip())
        if kept:
            change[key] = kept
    return answer


_ASKING_FOR_NONE_OF_IT = frozenset({"no", "without", "remove", "removing", "drop", "lose", "ditch"})


def _keeping_out_what_he_names(request: str, positive: str) -> dict | None:
    asking = next((word for word, *_ in _tokens(request) if word not in _FILLER), None)
    parsed, each = parse_request(request), _each_thing_asked_for(request)
    if asking not in _ASKING_FOR_NONE_OF_IT or parsed is None or len(each) != 1:
        return None
    naming_it = [part for part in things_of(positive).values()
                 if _touches(each[0], part) == len(each[0])]
    return {"changes": [*({"prompt": "positive", "remove": part, "for": request} for part in naming_it),
                        {"prompt": "negative", "add": parsed[1], "for": request}]}


def _the_way_he_adds_it(request: str, pair: tuple[str, str], his_prompts) -> dict | None:
    parsed, each = parse_request(request), _each_thing_asked_for(request)
    if parsed is None or parsed[0] != ADD or len(each) != 1:
        return None
    his = the_way_he_adds(lambda thing: _touches(each[0], thing) == len(each[0]), his_prompts, pair)
    if his is None:
        return None
    changes = [{"prompt": "positive", "add": ", ".join(his.positive), "after": his.beside,
                "for": request}]
    if his.negative:
        changes.append({"prompt": "negative", "add": ", ".join(his.negative), "for": request})
    return {"changes": changes}


def answer_to(positive: str, negative: str, request: str, known: WhatIsKnown, *,
              llm=None) -> dict:
    part = _part_he_names(request, positive)
    if part is not None:
        return {"changes": [{"more": part, "stronger": part, "opposite": "", "for": request}]}
    the_model = ask_the_model if llm is None else partial(ask_the_model, llm=llm)
    return (_keeping_out_what_he_names(request, positive)
            or _the_way_he_adds_it(request, (positive, negative), known.his_prompts)
            or the_model(positive, negative, request, known))


def ask_the_model(positive: str, negative: str, request: str, known: WhatIsKnown, *,
                  llm=None) -> dict:
    messages = build_request_messages(positive, negative, request, known, REQUEST_SYSTEM_PROMPT)
    asking = partial(llm or local_llm.ask, base_url=LOCAL_LLM_BASE_URL, model=REQUEST_LLM_MODEL,
                     timeout=_ASK_TIMEOUT_S, json_answer=True,
                     reads_tokens=_window_tokens(messages), stays_loaded=_STAYS_LOADED)
    said = _asked_again_if_the_model_failed_to_load(partial(asking, messages, temperature=0.4))

    def ask_again(question: str) -> dict:
        return asking([*messages, {"role": "assistant", "content": local_llm.text_of(said)},
                       {"role": "user", "content": question}], temperature=0)

    return _leaving_open_what_he_did(
        _adding_what_he_asked_for(local_llm.answer_of(said), request), request, ask_again)
