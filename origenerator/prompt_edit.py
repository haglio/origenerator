from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import partial

from origenerator import local_llm
from origenerator.box_breaks import unboxed
from origenerator.config import LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
from origenerator.prompts import REQUEST_REWRITE_SYSTEM_PROMPT, VOICE_REQUEST_MATCH_SYSTEM_PROMPT
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


def literal_match(terms: list[str], term: str) -> int | None:
    for i, text in enumerate(terms):
        if _mentions(text, term):
            return i
    return None


def _index_of(prompt: str, term: str, match) -> int | None:
    terms = bare_terms(prompt)
    found = literal_match(terms, term)
    if found is not None or match is None:
        return found
    found = match(terms, term)
    return found if found is not None and 0 <= found < len(terms) else None


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


_ELLIPSIS = re.compile(r"\.\.\.|\u2026")


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

    @property
    def changed(self) -> bool:
        return (self.positive != self.old_positive
                or self.negative != self.old_negative)


def apply_request(positive: str, negative: str, request: str,
                  match=None, rewrite=None) -> PromptRevision | None:
    parsed = parse_request(request)
    if parsed is None:
        return None
    return _revised(unboxed(positive or ""), unboxed(negative or ""), request, parsed,
                    match, rewrite)


def apply_request_to_each_scene(positive: str, negative: str, request: str,
                                match=None, rewrite=None) -> PromptRevision | None:
    positive, negative = unboxed(positive or ""), unboxed(negative or "")
    scenes, negatives = scene_prompts(positive), scene_prompts(negative)
    if len(scenes) == 1:
        return apply_request(positive, negative, request, match, rewrite)
    each_negative = [scene_text(negatives, index) for index in range(len(scenes))]
    revisions = [apply_request(scene, scene_negative, request, match, rewrite)
                 for scene, scene_negative in zip(scenes, each_negative, strict=True)]
    if revisions[0] is None:
        return None
    return PromptRevision(positive, negative,
                          story_of([revision.positive for revision in revisions]),
                          _negative_story(negative, each_negative,
                                          [revision.negative for revision in revisions]),
                          revisions[0].term, revisions[0].polarity,
                          ", ".join(dict.fromkeys(revision.action for revision in revisions)))


def request_applier(in_scenes: bool):
    return apply_request_to_each_scene if in_scenes else apply_request


def _negative_story(negative: str, before: list[str], after: list[str]) -> str:
    if after == before:
        return negative
    if len(set(after)) == 1:
        return after[0]
    return story_of(after)


def _revised(positive: str, negative: str, request: str, parsed: tuple,
             match, rewrite) -> PromptRevision:
    polarity, term = parsed

    def made(new_positive, new_negative, action) -> PromptRevision:
        return PromptRevision(positive, negative, new_positive, new_negative,
                              term, polarity, action)

    def rewritten() -> PromptRevision | None:
        if rewrite is None:
            return None
        try:
            new_positive, new_negative = (
                _said(old, _without_nothing_weighted(new))
                for old, new in zip((positive, negative), rewrite(positive, negative, request), strict=True))
        except Exception as exc:
            logger.warning("prompt_edit: could not rewrite the prompts for a request (%s)",
                           type(exc).__name__)
            return None
        if (new_positive, new_negative) == (positive, negative):
            return None
        if _leaves_out(positive, new_positive) or _leaves_out(negative, new_negative):
            return None
        return made(new_positive, new_negative, REWRITTEN)

    if polarity == REMOVE:
        index = _index_of(positive, term, match)
        if index is not None:
            within = bare_terms(positive)[index].lower() != term.lower()
            return ((within and rewritten())
                    or made(_without(positive, index), negative, DROPPED))
        index = _index_of(negative, term, None)
        if index is not None:
            return made(positive, _reweighted(negative, index, WEIGHT_STEP), PUSHED)
        return made(positive, _plus(negative, term), EXCLUDED)
    index = _index_of(negative, term, None)
    if index is not None:
        return made(positive, _without(negative, index), ALLOWED)
    index = _index_of(positive, term, None)
    if index is not None:
        return made(_reweighted(positive, index, WEIGHT_STEP), negative, RAISED)
    return rewritten() or made(_plus(positive, term), negative, ADDED)


def work_out(positive: str, negative: str, request: str, *,
             in_scenes: bool = False) -> PromptRevision | None:
    return request_applier(in_scenes)(
        positive, negative, request,
        match=partial(smart_match, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                      system_prompt=VOICE_REQUEST_MATCH_SYSTEM_PROMPT),
        rewrite=partial(rewrite_prompt, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                        system_prompt=REQUEST_REWRITE_SYSTEM_PROMPT))



def build_match_messages(terms: list[str], term: str, system_prompt: str) -> list[dict]:
    listing = "\n".join(f"{i}. {text}" for i, text in enumerate(terms))
    user = (
        f"Terms already in the prompt:\n{listing}\n\n"
        f"The speaker asked about: {term}\n\n"
        'Reply with only JSON: {"choice": n}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def parse_match(data: dict, count: int) -> int | None:
    try:
        obj = local_llm.answer_of(data)
    except json.JSONDecodeError:
        return None
    choice = obj.get("choice")
    if not isinstance(choice, int) or not 0 <= choice < count:
        return None
    return choice


def smart_match(terms: list[str], term: str, *, base_url: str, model: str,
                system_prompt: str, timeout: float = 20.0) -> int | None:
    if not terms:
        return None
    try:
        chosen = parse_match(local_llm.ask_json(
            build_match_messages(terms, term, system_prompt),
            base_url=base_url, model=model, temperature=0.1, timeout=timeout), len(terms))
    except Exception as exc:
        logger.warning("prompt_edit: could not match the request against the "
                       "prompt's %d terms (%s)", len(terms), exc)
        return None
    if chosen is not None:
        logger.info("prompt_edit: the request matched index %d of the prompt's %d terms",
                    chosen, len(terms))
    return chosen



def build_rewrite_messages(positive: str, negative: str, instruction: str,
                           system_prompt: str) -> list[dict]:
    user = (
        f"Positive prompt:\n{positive}\n\n"
        f"Negative prompt:\n{negative}\n\n"
        f"Spoken instruction:\n{instruction}\n\n"
        'Reply with only a JSON object with two keys: "positive", holding the whole '
        'rewritten positive prompt, and "negative", holding the whole rewritten negative prompt.'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def rewrite_prompt(positive: str, negative: str, instruction: str, *, base_url: str,
                   model: str, system_prompt: str, timeout: float = 30.0):
    obj = local_llm.answer_of(local_llm.ask_json(
        build_rewrite_messages(positive, negative, instruction, system_prompt),
        base_url=base_url, model=model, temperature=0.4, timeout=timeout))
    new_positive = str(obj["positive"]).strip() if "positive" in obj else positive
    new_negative = str(obj["negative"]).strip() if "negative" in obj else negative
    return new_positive, new_negative
