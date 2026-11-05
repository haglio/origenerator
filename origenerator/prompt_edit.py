from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import partial

from origenerator import local_llm, request_settings
from origenerator.box_breaks import unboxed
from origenerator.collection_notes import CollectionNotes
from origenerator.config import LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
from origenerator.db_requests import Turn
from origenerator.prompts import REQUEST_SYSTEM_PROMPT
from origenerator.workflows.base import scene_prompts, scene_text, story_of

logger = logging.getLogger(__name__)

# ComfyUI (term:weight) form; unweighted is 1.0, each wrapping paren 1.1x
WEIGHT_STEP = 0.1
_PAREN_WEIGHT = 1.1

ADD = "add"
REMOVE = "remove"

DROPPED = "dropped"
PUSHED = "pushed"
EXCLUDED = "excluded"
RAISED = "raised"
ADDED = "added"
ALLOWED = "allowed"
REWRITTEN = "rewritten"

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



def _segments(prompt: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, char in enumerate(prompt or ""):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append((prompt or "")[start:i])
            start = i + 1
    parts.append((prompt or "")[start:])
    return parts


def _unwrap(segment: str) -> tuple:
    # ComfyUI: (term:1.2) states its weight; each wrapping paren multiplies by 1.1
    text = (segment or "").strip()
    weight = 1.0
    while len(text) > 1 and text[0] == "(" and _closes_at_end(text):
        text = text[1:-1].strip()
        weight *= _PAREN_WEIGHT
    match = re.fullmatch(r"(.*?):\s*([0-9]*\.?[0-9]+)", text, re.DOTALL)
    if match:
        return match.group(1).strip(), float(match.group(2))
    return text, round(weight, 3)


def _closes_at_end(text: str) -> bool:
    depth = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i == len(text) - 1
    return False


def _mentions(text: str, term: str) -> bool:
    words = term.split()
    if not words:
        return False
    pattern = r"\s+".join(re.escape(word) for word in words)
    return re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE) is not None


def bare_terms(prompt: str) -> list[str]:
    return [_unwrap(segment)[0] for segment in _segments(prompt)]


def terms_with_places(prompt: str) -> list[tuple[str, int, int]]:
    places, at = [], 0
    for segment in _segments(prompt):
        start = at + len(segment) - len(segment.lstrip())
        places.append((_unwrap(segment)[0], start, start + len(segment.strip())))
        at += len(segment) + 1
    return places


def literal_match(terms: list[str], term: str) -> int | None:
    for i, text in enumerate(terms):
        if _mentions(text, term):
            return i
    return None


def _index_of(prompt: str, term: str) -> int | None:
    return literal_match(bare_terms(prompt), term)


def _tidy(prompt: str) -> str:
    return re.sub(r"^[\s,]+|[\s,]+$", "", prompt)


def _without(prompt: str, index: int) -> str:
    segments = _segments(prompt)
    del segments[index]
    return _tidy(",".join(segments))


def _format_weight(weight: float) -> str:
    return f"{round(weight, 2):g}"


def _reweighted(prompt: str, index: int, delta: float) -> str:
    segments = _segments(prompt)
    segment = segments[index]
    term, weight = _unwrap(segment)
    weight = round(weight + delta, 2)
    lead = segment[:len(segment) - len(segment.lstrip())]
    segments[index] = f"{lead}({term}:{_format_weight(weight)})"
    return _tidy(",".join(segments))


def _without_nothing_weighted(prompt: str) -> str:
    segments = _segments(prompt)
    kept = [segment for segment in segments if _unwrap(segment)[1] > 0]
    return prompt if len(kept) == len(segments) else _tidy(",".join(kept))


_ELLIPSIS = re.compile(r"\.\.\.|…")


def _said(old: str, new: str) -> str:
    return new if re.search(r"\w", new) else old


def _leaves_out(old: str, new: str) -> bool:
    return bool(_ELLIPSIS.search(new)) and not _ELLIPSIS.search(old)


def _plus(prompt: str, term: str) -> str:
    kept = _tidy(prompt)
    return f"{kept}, {term}" if kept else term


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


def apply_request(positive: str, negative: str, request: str) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    return _revised(unboxed(positive or ""), unboxed(negative or ""), parsed)


def apply_request_to_each_scene(positive: str, negative: str, request: str) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = unboxed(positive or ""), unboxed(negative or "")
    scenes, each_negative = _scenes_of(positive, negative)
    revisions = [_revised(scene, scene_negative, parsed)
                 for scene, scene_negative in zip(scenes, each_negative, strict=True)]
    return _joined(positive, negative, each_negative, parsed, revisions)


def request_applier(in_scenes: bool):
    return apply_request_to_each_scene if in_scenes else apply_request


def _negative_story(negative: str, before: list[str], after: list[str]) -> str:
    if after == before:
        return negative
    if len(set(after)) == 1:
        return after[0]
    return story_of(after)


def _revised(positive: str, negative: str, parsed: tuple) -> PromptRevision:
    polarity, term = parsed

    def made(new_positive, new_negative, action) -> PromptRevision:
        return PromptRevision(positive, negative, new_positive, new_negative,
                              term, polarity, action)

    if polarity == REMOVE:
        index = _index_of(positive, term)
        if index is not None:
            return made(_without(positive, index), negative, DROPPED)
        index = _index_of(negative, term)
        if index is not None:
            return made(positive, _reweighted(negative, index, WEIGHT_STEP), PUSHED)
        return made(positive, _plus(negative, term), EXCLUDED)
    index = _index_of(negative, term)
    if index is not None:
        return made(positive, _without(negative, index), ALLOWED)
    index = _index_of(positive, term)
    if index is not None:
        return made(_reweighted(positive, index, WEIGHT_STEP), negative, RAISED)
    return made(_plus(positive, term), negative, ADDED)


@dataclass(frozen=True)
class WhatIsKnown:
    exchange: tuple = ()
    notes: CollectionNotes | None = None
    examples: tuple = ()
    settings: tuple = ()


def work_out(positive: str, negative: str, request: str, *, in_scenes: bool = False, ask=None,
             **known) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = unboxed(positive or ""), unboxed(negative or "")
    scenes, each_negative = (_scenes_of(positive, negative) if in_scenes
                             else ([positive], [negative]))
    told = WhatIsKnown(**known)
    revisions = []
    for scene, scene_negative in zip(scenes, each_negative, strict=True):
        revision = _answered(scene, scene_negative, parsed,
                             partial(ask or ask_the_model, scene, scene_negative, request, told),
                             told.settings)
        if revision is None:
            return request_applier(in_scenes)(positive, negative, request)
        revisions.append(revision)
    return _joined(positive, negative, each_negative, parsed, revisions)


def _answered(positive: str, negative: str, parsed: tuple, asking,
              settings) -> PromptRevision | None:
    polarity, term = parsed
    try:
        new_positive, new_negative, answer, *more = asking()
    except Exception as exc:  # noqa: BLE001 -- model down or unreadable: the rules' own edit stands
        logger.warning("prompt_edit: the model could not answer the request (%s)",
                       type(exc).__name__)
        return None
    new_positive = _said(positive, _without_nothing_weighted(new_positive))
    new_negative = _said(negative, _without_nothing_weighted(new_negative))
    if _leaves_out(positive, new_positive) or _leaves_out(negative, new_negative):
        return None
    changes = request_settings.changes_asked(more[0] if more else None, settings)
    if (new_positive, new_negative) == (positive, negative) and not answer and not changes:
        return None
    return PromptRevision(positive, negative, new_positive, new_negative, term, polarity,
                          REWRITTEN, answer, tuple(changes.items()),
                          tuple(request_settings.described(changes, settings)))


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
                     limit_chars: int = 6000) -> list[str]:
    asked = _asked_about(request)
    scored = sorted((-_touches(asked, prompt), position, prompt)
                    for position, prompt in enumerate(prompts))
    chosen, used = [], 0
    for score, _position, prompt in scored:
        if score == 0 or len(chosen) == limit:
            break
        if used + len(prompt) <= limit_chars:
            chosen.append(prompt)
            used += len(prompt)
    return chosen




def build_request_messages(positive: str, negative: str, request: str, known: WhatIsKnown,
                           system_prompt: str) -> list[dict]:
    parts = []
    if known.notes is not None and known.notes.complete:
        parts.append(known.notes.as_told())
    if known.exchange:
        turns = "\n".join(f"Artist: {turn[0]}\nYou: {turn[1]}" for turn in known.exchange)
        parts.append(f"THE EXCHANGE SO FAR about this image, oldest first:\n{turns}")
    if known.examples:
        numbered = "\n".join(f"{number}. {prompt}" for number, prompt in enumerate(known.examples, 1))
        parts.append("PROMPTS OF HIS THAT TOUCH WHAT HE ASKS FOR (how he writes such things; "
                     f"carry over the details that go with them):\n{numbered}")
    if known.settings:
        parts.append("SETTINGS HE MAY ALSO CHANGE (current values):\n"
                     + request_settings.as_told(known.settings))
    parts.append(f"CURRENT POSITIVE PROMPT:\n{positive}\n\nCURRENT NEGATIVE PROMPT:\n{negative}")
    parts.append(f"THE ARTIST NOW ASKS:\n{request}")
    parts.append(
        'Reply with only a JSON object with four keys: "positive", holding the whole '
        'rewritten positive prompt; "negative", holding the whole rewritten negative '
        'prompt; "answer", one or two plain sentences to the artist on what you '
        'changed and what in his collection you drew on; and "settings", the settings '
        "to change by their [key], {} when none.")
    return [{"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(parts)}]


def ask_the_model(positive: str, negative: str, request: str, known: WhatIsKnown, *,
                  llm=None) -> tuple:
    obj = local_llm.answer_of((llm or local_llm.ask)(
        build_request_messages(positive, negative, request, known, REQUEST_SYSTEM_PROMPT),
        base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL, temperature=0.4,
        timeout=_ASK_TIMEOUT_S, json_answer=True, reads_tokens=REQUEST_WINDOW_TOKENS,
        stays_loaded="0"))
    return (str(obj["positive"]).strip() if "positive" in obj else positive,
            str(obj["negative"]).strip() if "negative" in obj else negative,
            str(obj.get("answer") or "").strip(), obj.get("settings"))
