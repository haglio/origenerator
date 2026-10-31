"""Turning a request into an edit of a prompt pair.

A request is a wish about the image on screen — "no silver earrings", "change to
a tropical beach" — and the local model answers it first, knowing the collection,
the exchange so far about this image and his own prompts that touch the request.
When the model cannot answer, a fixed policy makes the smallest edit the words allow:

* A request AGAINST something. In the positive prompt? Take it out. Otherwise
  put it in the negative prompt — unless it is already there, in which case
  lean on it harder: weight up by :data:`WEIGHT_STEP`.
* A request FOR something. The mirror of that: in the negative prompt? Take it
  out. Otherwise raise its weight in the positive — or add it, if it is in
  neither.

Everything but :func:`ask_the_model` is pure and Qt-free, so the whole policy
unit-tests without a model or a server.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from origenerator import local_llm, request_settings
from origenerator.collection_notes import CollectionNotes
from origenerator.config import LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL
from origenerator.prompts import REQUEST_SYSTEM_PROMPT
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
REWRITTEN = "rewritten"  # the model reworked the whole pair

# What the model reads for one request: the notes on the collection, the
# exchange, both prompts and the request, with room over.
REQUEST_WINDOW_TOKENS = 32768
_ASK_TIMEOUT_S = 180.0


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
        return None
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
    """A prompt's own terms, one per segment, stripped of weights."""
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


def _index_of(prompt: str, term: str) -> int | None:
    return literal_match(bare_terms(prompt), term)


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


_ELLIPSIS = re.compile(r"\.\.\.|…")


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
    """One request applied to a prompt pair: what it was, what it became, which
    of the rules did it, and what the model said back ("" from the rules)."""

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
        """Whether this actually moved either prompt or a setting — a request that
        changes nothing is one there is no point generating."""
        return (self.positive != self.old_positive
                or self.negative != self.old_negative
                or bool(self.settings))


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
    """Apply a ``request`` to a prompt pair by the policy up top, reading the
    words themselves alone, each scene of a story by its own prompts.

    ``None`` when the request names nothing to act on ("request … over" with
    only filler between the markers), so the caller can say it didn't catch a
    term rather than generate a copy of what's already there.
    """
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = positive or "", negative or ""
    scenes, each_negative = _scenes_of(positive, negative)
    revisions = [_revised(scene, scene_negative, parsed)
                 for scene, scene_negative in zip(scenes, each_negative)]
    return _joined(positive, negative, each_negative, parsed, revisions)


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


def work_out(positive: str, negative: str, request: str, *, exchange=(),
             notes: CollectionNotes | None = None, examples=(), settings=(),
             ask=None) -> PromptRevision | None:
    """``request`` applied as every request is, spoken or typed: the local model
    first, knowing the collection, the exchange and his own prompts that touch
    the request, and the rules when the model cannot answer."""
    parsed = parse_request(request)
    if parsed is None:
        return None
    positive, negative = positive or "", negative or ""
    scenes, each_negative = _scenes_of(positive, negative)
    revisions = []
    for scene, scene_negative in zip(scenes, each_negative):
        revision = _answered(scene, scene_negative, request, parsed, exchange, notes, examples,
                             settings, ask or ask_the_model)
        if revision is None:
            return apply_request(positive, negative, request)
        revisions.append(revision)
    return _joined(positive, negative, each_negative, parsed, revisions)


def _answered(positive: str, negative: str, request: str, parsed: tuple, exchange, notes,
              examples, settings, ask) -> PromptRevision | None:
    polarity, term = parsed
    try:
        new_positive, new_negative, answer, *more = ask(positive, negative, request, exchange,
                                                        notes, examples, settings=settings)
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


# --- his own prompts that touch the request, shown to the model as examples --


_NAMING_NOTHING = _FILLER | _ADD_WORDS | _REMOVE_WORDS | _TRAILING | _both_spellings({
    "she", "he", "him", "they", "in", "into", "at", "for", "from", "by", "to", "is", "are",
    "was", "isn't", "wasn't", "aren't", "did", "didn't", "does", "do", "doing", "get", "gets",
    "getting", "gives", "giving", "gave", "appear", "appears", "appeared", "show", "shows",
    "showed", "showing", "up", "still", "see", "missing", "again", "one", "same", "other",
})


def _roots(word: str) -> set[str]:
    roots = {word}
    for ending in ("s", "es", "ing", "ed"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
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
            if len(word) >= 3 and word not in _NAMING_NOTHING]


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


# --- the I/O boundary: the model, with the notes and the exchange ------------


def build_request_messages(positive: str, negative: str, request: str, exchange,
                           notes: CollectionNotes | None, system_prompt: str,
                           examples=(), settings=()) -> list[dict]:
    parts = []
    if notes is not None and notes.complete:
        parts.append(notes.as_told())
    if exchange:
        turns = "\n".join(f"Artist: {turn[0]}\nYou: {turn[1]}" for turn in exchange)
        parts.append(f"THE EXCHANGE SO FAR about this image, oldest first:\n{turns}")
    if examples:
        numbered = "\n".join(f"{number}. {prompt}" for number, prompt in enumerate(examples, 1))
        parts.append("PROMPTS OF HIS THAT TOUCH WHAT HE ASKS FOR (how he writes such things; "
                     f"carry over the details that go with them):\n{numbered}")
    if settings:
        parts.append("SETTINGS HE MAY ALSO CHANGE (current values):\n"
                     + request_settings.as_told(settings))
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


def ask_the_model(positive: str, negative: str, request: str, exchange,
                  notes: CollectionNotes | None, examples=(), settings=()) -> tuple:
    """The revised pair and the model's sentence; raises when the model cannot be
    reached or read, which the caller answers with the rules' own edit."""
    obj = local_llm.answer_of(local_llm.ask(
        build_request_messages(positive, negative, request, exchange, notes,
                               REQUEST_SYSTEM_PROMPT, examples, settings),
        base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL, temperature=0.4,
        timeout=_ASK_TIMEOUT_S, json_answer=True, reads_tokens=REQUEST_WINDOW_TOKENS,
        stays_loaded="0"))
    return (str(obj["positive"]).strip() if "positive" in obj else positive,
            str(obj["negative"]).strip() if "negative" in obj else negative,
            str(obj.get("answer") or "").strip(), obj.get("settings"))
