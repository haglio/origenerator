from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import partial

from origenerator import local_llm, request_settings
from origenerator.box_breaks import unboxed
from origenerator.collection_notes import CollectionNotes
from origenerator.config import (
    LOCAL_LLM_BASE_URL,
    REQUEST_LLM_MODEL,
    REQUEST_MODEL_STAYS_LOADED_S,
)
from origenerator.db_requests import Turn
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

REQUEST_WINDOW_TOKENS = 32768
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
                             partial(ask or ask_the_model, scene, scene_negative, request, told),
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
    'should change, "changes" is an empty list.')


_NO_WEIGHTS = (
    "THESE PROMPTS TAKE NO WEIGHTS: the image model ignores (term:weight), so never write one. "
    "For less of something, say it more mildly or remove it.")


def build_request_messages(positive: str, negative: str, request: str, known: WhatIsKnown,
                           system_prompt: str) -> list[dict]:
    parts = []
    if known.notes is not None and known.notes.complete:
        parts.append(known.notes.as_told())
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


def ask_the_model(positive: str, negative: str, request: str, known: WhatIsKnown, *,
                  llm=None) -> dict:
    return local_llm.answer_of((llm or local_llm.ask)(
        build_request_messages(positive, negative, request, known, REQUEST_SYSTEM_PROMPT),
        base_url=LOCAL_LLM_BASE_URL, model=REQUEST_LLM_MODEL, temperature=0.4,
        timeout=_ASK_TIMEOUT_S, json_answer=True, reads_tokens=REQUEST_WINDOW_TOKENS,
        stays_loaded=_STAYS_LOADED))
