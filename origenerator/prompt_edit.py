"""Turning a spoken request into an edit of a prompt pair.

A request is a wish about the image on screen — "no silver earrings", "more
freckles" — and what it means for the prompt pair follows a fixed policy:

* A request AGAINST something. In the positive prompt? Take it out. Otherwise
  put it in the negative prompt — unless it is already there, in which case
  lean on it harder: weight up by :data:`WEIGHT_STEP`.
* A request FOR something. The mirror of that: in the negative prompt? Take it
  out. Otherwise raise its weight in the positive — or add it, if it is in
  neither.

Each is the smallest change that answers the request, which is why the mirror is
"take it out of the negative prompt" rather than "take it out and also add it":
ask twice and the second pass, finding it in neither prompt, adds it.

The policy is deterministic for every term a prompt already holds. A term in
neither prompt is the one thing it can only append, and the prompt may say the
opposite ("two women" over a prompt describing one), so that is handed to the
local LLM to work into the whole pair (``rewrite``). The other thing a model is
needed for is finding the term at all: "no earrings" is about a
prompt that says "silver ear studs", and no amount of string matching gets from
one to the other. So the two are split. :func:`literal_match` reads a prompt for
the words themselves and is what runs by default; :func:`smart_match` asks the
local LLM which of the prompt's own terms the request means, and is handed in by
a caller that wants synonyms caught. Either way the rules above then apply
unchanged, and a request whose wording can't be read at all comes back as
``None`` for the caller to say so rather than being guessed at.

Everything but :func:`smart_match` and :func:`rewrite_prompt` is pure and Qt-free,
so the whole policy unit-tests without a model or a server.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import partial

from origenerator import local_llm
from origenerator.config import LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
from origenerator.prompts import REQUEST_REWRITE_SYSTEM_PROMPT, VOICE_REQUEST_MATCH_SYSTEM_PROMPT
from origenerator.workflows.base import scene_prompts, scene_text, story_of

logger = logging.getLogger(__name__)

# What a bump moves a term's weight by, up or out. The prompts use ComfyUI's
# ``(term:weight)`` form; an unweighted term counts as 1.0 and each wrapping
# paren as the usual 1.1x.
WEIGHT_STEP = 0.1
_PAREN_WEIGHT = 1.1

ADD = "add"        # the speaker wants more of this
REMOVE = "remove"  # the speaker wants less of it, or none

# How the edit was made, for the line the app says back and the record it keeps.
DROPPED = "dropped"      # taken out of the positive prompt
PUSHED = "pushed"        # already excluded, now excluded harder
EXCLUDED = "excluded"    # added to the negative prompt
RAISED = "raised"        # already wanted, now wanted harder
ADDED = "added"          # added to the positive prompt
ALLOWED = "allowed"      # taken out of the negative prompt
REWRITTEN = "rewritten"  # in neither prompt, so worked into the whole of it

def _both_spellings(words: set) -> frozenset:
    """``words`` plus the same words with their apostrophes dropped.

    Whisper punctuates contractions as it pleases, writing "don't" one utterance
    and the bare letters the next, and a wish word that only matches one
    spelling silently reverses the polarity of the request that used the other.
    """
    return frozenset(words | {word.replace("'", "") for word in words})


# Words that flip a request against its term. Phrases lead so "get rid of" is
# read whole rather than as the filler "get" and a term starting "rid".
_REMOVE_PHRASES = (("get", "rid", "of"), ("get", "rid"), ("take", "off"),
                   ("take", "away"), ("do", "away", "with"))
_REMOVE_WORDS = _both_spellings({
    "no", "not", "none", "never", "without", "remove", "removing", "drop",
    "lose", "hide", "avoid", "stop", "skip", "ditch", "cut", "minus",
    "don't", "doesn't", "won't", "less", "fewer",
})
# Words that mark it as a wish FOR the term. A request with none of either is
# read as one of these: naming a thing is asking for it.
_ADD_WORDS = _both_spellings({
    "more", "add", "adding", "give", "want", "with", "include", "including",
    "put", "increase", "boost", "extra",
})
# Words carrying no wish at all, skipped wherever they appear before the term.
_FILLER = frozenset({
    "please", "ok", "okay", "so", "um", "uh", "and", "also", "then", "just",
    "maybe", "can", "could", "would", "you", "i", "we", "let", "lets", "us",
    "really", "much", "many", "of", "on", "her", "his", "their", "its", "my",
    "our", "your", "the", "a", "an", "this", "that", "these", "those", "some",
    "any", "it", "them", "there", "have", "has", "make", "makes", "be",
})
# Words that trail a request without belonging to it.
_TRAILING = frozenset({"please", "thanks", "thank", "you", "now", "instead"})

_WORD = re.compile(r"[A-Za-z0-9'\-]+")


def _tokens(text: str) -> list:
    """``(lowercase word, start, end)`` for each word of ``text``, so a term can
    be cut back out of the original with its own casing and punctuation."""
    return [(m.group(0).lower(), m.start(), m.end()) for m in _WORD.finditer(text or "")]


def _phrase_at(tokens: list, index: int) -> int:
    """How many tokens a multi-word negation at ``index`` spans (0 for none)."""
    for phrase in _REMOVE_PHRASES:
        end = index + len(phrase)
        if end <= len(tokens) and tuple(t[0] for t in tokens[index:end]) == phrase:
            return len(phrase)
    return 0


def parse_request(request: str) -> tuple | None:
    """``(polarity, term)`` for a spoken request, or ``None`` when there's no
    term in it to act on.

    The polarity is the FIRST wish word found, so "no more silver earrings" is a
    request against them rather than for more of them; with no wish word at all
    it is :data:`ADD`, since naming a thing is asking for it. Everything from the
    first word that isn't a wish word, an article, or filler is the term, cut
    from the original text so its own casing and punctuation survive.
    """
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
        return None  # all wish words and filler — nothing named to act on
    term = request[tokens[index][1]:tokens[end - 1][2]].strip()
    return (polarity or ADD), term


# --- reading and rewriting one prompt ---------------------------------------


def _segments(prompt: str) -> list[str]:
    """A prompt's comma-separated segments, kept raw (their own spacing intact).

    Depth-aware, because a comma inside ``(a, b:1.2)`` groups those terms rather
    than separating two of them.
    """
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
    """A segment's bare term and its weight: ``(term, weight)``.

    ``(term:1.2)`` states its own; wrapping parens each multiply by 1.1, the
    convention the prompts are written in; anything else is a plain 1.0.
    """
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
    """Whether the opening paren of ``text`` is closed by its very last char —
    i.e. the parens wrap the whole segment rather than part of it."""
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
    """Whether ``term`` appears in ``text`` as whole words (any spacing, any case)."""
    words = term.split()
    if not words:
        return False
    pattern = r"\s+".join(re.escape(word) for word in words)
    return re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE) is not None


def bare_terms(prompt: str) -> list[str]:
    """A prompt's own terms, one per segment, stripped of weights — what a
    request has to be matched against, and the list a matcher is shown."""
    return [_unwrap(segment)[0] for segment in _segments(prompt)]


def literal_match(terms: list[str], term: str) -> int | None:
    """Which of ``terms`` says ``term`` in so many words, or ``None``.

    A segment is the unit: "small silver earrings" is one thing the image has,
    so a request about silver earrings acts on the whole of it rather than
    editing the words inside it.
    """
    for i, text in enumerate(terms):
        if _mentions(text, term):
            return i
    return None


def _index_of(prompt: str, term: str, match) -> int | None:
    """Which segment of ``prompt`` the request is about, or ``None``.

    Literal first, always: when the prompt says the words the speaker said,
    nothing else needs deciding, and a model asked anyway could talk itself out
    of the obvious answer. ``match`` — the caller's smarter matcher, when it
    supplied one — is asked only about a prompt that doesn't.
    """
    terms = bare_terms(prompt)
    found = literal_match(terms, term)
    if found is not None or match is None:
        return found
    found = match(terms, term)
    return found if found is not None and 0 <= found < len(terms) else None


def _tidy(prompt: str) -> str:
    """A rebuilt prompt without the empty edges a removal leaves."""
    return re.sub(r"^[\s,]+|[\s,]+$", "", prompt)


def _without(prompt: str, index: int) -> str:
    segments = _segments(prompt)
    del segments[index]
    return _tidy(",".join(segments))


def _format_weight(weight: float) -> str:
    """A weight as a prompt writes it: 1.1, not 1.1000000000000001."""
    return f"{round(weight, 2):g}"


def _reweighted(prompt: str, index: int, delta: float) -> str:
    """``prompt`` with segment ``index`` re-weighted by ``delta``. The segment
    is rewritten in the explicit ``(term:weight)`` form whatever it was in
    before, so the number it ends on is readable."""
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
    """``prompt`` with ``term`` appended as a new segment."""
    kept = _tidy(prompt)
    return f"{kept}, {term}" if kept else term


@dataclass(frozen=True)
class PromptRevision:
    """One request applied to a prompt pair: what it was, what it became, and
    which of the rules did it."""

    old_positive: str
    old_negative: str
    positive: str
    negative: str
    term: str
    polarity: str
    action: str

    @property
    def changed(self) -> bool:
        """Whether this actually moved either prompt — a request that changes
        nothing is one there is no point generating."""
        return (self.positive != self.old_positive
                or self.negative != self.old_negative)


def apply_request(positive: str, negative: str, request: str,
                  match=None, rewrite=None) -> PromptRevision | None:
    """Apply a ``request`` to a prompt pair, by the policy up top.

    ``match(terms, term)`` is how a positive prompt that doesn't say the words
    a request against something said is still searched — see
    :func:`smart_match`. Every other lookup reads the words themselves only: a
    model asked which of "blurry" meant "two women" answered blurry.

    ``rewrite(positive, negative, request)`` answers what the policy can only
    do bluntly: something in neither prompt, which the prompt may contradict
    ("two women" over a prompt describing one), and something to take out of a
    phrase that says more than it ("a woman wearing a straw hat"), so the local
    model reworks the whole pair. A rewrite that fails leaves the policy's own
    edit standing.

    ``None`` when the request names nothing to act on ("request … over" with
    only filler between the markers), so the caller can say it didn't catch a
    term rather than generate a copy of what's already there.
    """
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = positive or "", negative or ""
    scenes, negatives = scene_prompts(positive), scene_prompts(negative)
    if len(scenes) == 1:
        return _revised(positive, negative, request, parsed, match, rewrite)
    each_negative = [scene_text(negatives, index) for index in range(len(scenes))]
    revisions = [_revised(scene, scene_negative, request, parsed, match, rewrite)
                 for scene, scene_negative in zip(scenes, each_negative)]
    polarity, term = parsed
    return PromptRevision(positive, negative,
                          story_of([revision.positive for revision in revisions]),
                          _negative_story(negative, each_negative,
                                          [revision.negative for revision in revisions]),
                          term, polarity,
                          ", ".join(dict.fromkeys(revision.action for revision in revisions)))


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
                for old, new in zip((positive, negative), rewrite(positive, negative, request)))
        except Exception as exc:  # model down / unreadable: the rules' own edit stands
            logger.warning("prompt_edit: could not rewrite the prompts for a request (%s)",
                           type(exc).__name__)
            return None
        if (new_positive, new_negative) == (positive, negative):
            return None  # it did nothing, which is no answer to a request
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


def work_out(positive: str, negative: str, request: str) -> PromptRevision | None:
    """``request`` applied as every request is, spoken or typed: the local LLM
    finding a term the prompt names in its own words, and rewriting the pair for
    one in neither prompt."""
    return apply_request(
        positive, negative, request,
        match=partial(smart_match, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                      system_prompt=VOICE_REQUEST_MATCH_SYSTEM_PROMPT),
        rewrite=partial(rewrite_prompt, base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                        system_prompt=REQUEST_REWRITE_SYSTEM_PROMPT))


# --- the I/O boundary: which of a prompt's terms the request means ----------


def build_match_messages(terms: list[str], term: str, system_prompt: str) -> list[dict]:
    """The chat messages for one match: the rules, then the prompt's own terms
    numbered, and the term the speaker used."""
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
    """The chosen index from a completion, or ``None`` for "none of them".

    Anything out of range is read as no answer rather than clamped: a number the
    model invented is not a term the speaker meant, and acting on it would edit
    a part of the prompt nobody mentioned.
    """
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
    """Which of a prompt's own terms the speaker meant, or ``None`` for none.

    What the literal search cannot do: "no earrings" is about a prompt that says
    "silver ear studs", and no matching of the words themselves gets from one to
    the other. So the prompt's terms are offered to the local LLM and it says
    which one — a lookup, not a rewrite; the policy still decides what happens
    to whatever comes back.

    ``None`` on an unreachable model or an unusable answer, so the caller falls
    back to what the words themselves said — which for a request against
    something absent is to add it to the negative prompt, exactly as before.
    """
    if not terms:
        return None
    try:
        chosen = parse_match(local_llm.ask(
            build_match_messages(terms, term, system_prompt),
            base_url=base_url, model=model, temperature=0.1, timeout=timeout), len(terms))
    except Exception as exc:  # model down / unparseable: the words stand alone
        logger.warning("prompt_edit: could not match the request against the "
                       "prompt's %d terms (%s)", len(terms), exc)
        return None
    if chosen is not None:
        logger.info("prompt_edit: the request matched index %d of the prompt's %d terms",
                    chosen, len(terms))
    return chosen


# --- and the pair rewritten for a term in neither prompt ---------------------


def build_rewrite_messages(positive: str, negative: str, instruction: str,
                           system_prompt: str) -> list[dict]:
    """The chat messages for one rewrite: the editing rules, then the current
    prompt pair and the spoken change as the user turn."""
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
    """Apply ``instruction`` to the (positive, negative) prompt pair via the local
    LLM and return the revised pair. A field the model omits is left unchanged.
    Raises on transport/decode errors so the caller can surface them."""
    obj = local_llm.answer_of(local_llm.ask(
        build_rewrite_messages(positive, negative, instruction, system_prompt),
        base_url=base_url, model=model, temperature=0.4, timeout=timeout))
    new_positive = str(obj["positive"]).strip() if "positive" in obj else positive
    new_negative = str(obj["negative"]).strip() if "negative" in obj else negative
    return new_positive, new_negative
