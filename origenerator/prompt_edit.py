"""Turning a spoken request into an edit of a prompt pair.

A request is a wish about the picture on screen — "no silver earrings", "more
freckles" — and what it means for the prompt pair follows a fixed policy:

* A request AGAINST something. In the positive prompt? Take it out. Otherwise
  put it in the negative prompt — unless it is already there, in which case
  lean on it harder: weight up by :data:`WEIGHT_STEP`.
* A request FOR something. The mirror of that: in the negative prompt? Take it
  out. Otherwise raise its weight in the positive — or add it, if it is in
  neither.

Each is the smallest change that answers the request, which is why the mirror is
"stop excluding it" rather than "stop excluding it and also add it": ask twice
and the second pass, finding it in neither prompt, adds it.

The policy is deterministic — no model decides what happens to a term. What a
model *is* needed for is finding the term at all: "no earrings" is about a
prompt that says "silver ear studs", and no amount of string matching gets from
one to the other. So the two are split. :func:`literal_match` reads a prompt for
the words themselves and is what runs by default; :func:`smart_match` asks the
local LLM which of the prompt's own terms the request means, and is handed in by
a caller that wants synonyms caught. Either way the rules above then apply
unchanged, and a request whose wording can't be read at all comes back as
``None`` for the caller to say so rather than being guessed at.

Everything but that one function is pure and Qt-free, so the whole policy
unit-tests without a model or a server.
"""

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

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

    A segment is the unit: "small silver earrings" is one thing the picture has,
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
    """A rebuilt prompt without the empty edges a removal leaves behind."""
    return re.sub(r"^[\s,]+|[\s,]+$", "", prompt)


def _without(prompt: str, index: int) -> str:
    segments = _segments(prompt)
    del segments[index]
    return _tidy(",".join(segments))


def _format_weight(weight: float) -> str:
    """A weight as a prompt writes it: 1.1, not 1.1000000000000001."""
    return f"{round(weight, 2):g}"


def _reweighted(prompt: str, index: int, delta: float) -> tuple:
    """``prompt`` with segment ``index`` re-weighted by ``delta``, and the weight
    it now carries. The segment is rewritten in the explicit ``(term:weight)``
    form whatever it was in before, so the number it ends on is readable."""
    segments = _segments(prompt)
    segment = segments[index]
    term, weight = _unwrap(segment)
    weight = round(weight + delta, 2)
    lead = segment[:len(segment) - len(segment.lstrip())]
    segments[index] = f"{lead}({term}:{_format_weight(weight)})"
    return _tidy(",".join(segments)), weight


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
    weight: float | None = None  # what a re-weighting landed on, else None

    @property
    def changed(self) -> bool:
        """Whether this actually moved either prompt — a request that changes
        nothing is one there is no point generating."""
        return (self.positive != self.old_positive
                or self.negative != self.old_negative)

    def describe(self) -> str:
        """What was done, as a line to say back to the speaker."""
        quoted = f"“{self.term}”"
        if self.action == DROPPED:
            return f"dropped {quoted}"
        if self.action == PUSHED:
            return f"{quoted} pushed further out ({_format_weight(self.weight)})"
        if self.action == EXCLUDED:
            return f"{quoted} added to the negative prompt"
        if self.action == RAISED:
            return f"{quoted} raised to {_format_weight(self.weight)}"
        if self.action == ALLOWED:
            return f"stopped excluding {quoted}"
        return f"{quoted} added to the prompt"


def apply_request(positive: str, negative: str, request: str,
                  match=None) -> PromptRevision | None:
    """Apply a spoken ``request`` to a prompt pair, by the policy up top.

    ``match(terms, term)`` is how a prompt that doesn't say the words the
    speaker said is still searched — see :func:`smart_match`. Without one, only
    the words themselves are looked for.

    ``None`` when the request names nothing to act on ("request … over" with
    only filler between the markers), so the caller can say it didn't catch a
    term rather than generate a copy of what's already there.
    """
    parsed = parse_request(request)
    if parsed is None:
        return None
    polarity, term = parsed
    positive, negative = positive or "", negative or ""

    def made(new_positive, new_negative, action, weight=None) -> PromptRevision:
        return PromptRevision(positive, negative, new_positive, new_negative,
                              term, polarity, action, weight)

    if polarity == REMOVE:
        index = _index_of(positive, term, match)
        if index is not None:
            return made(_without(positive, index), negative, DROPPED)
        index = _index_of(negative, term, match)
        if index is not None:
            revised, weight = _reweighted(negative, index, WEIGHT_STEP)
            return made(positive, revised, PUSHED, weight)
        return made(positive, _plus(negative, term), EXCLUDED)
    index = _index_of(negative, term, match)
    if index is not None:
        return made(positive, _without(negative, index), ALLOWED)
    index = _index_of(positive, term, match)
    if index is not None:
        revised, weight = _reweighted(positive, index, WEIGHT_STEP)
        return made(revised, negative, RAISED, weight)
    return made(_plus(positive, term), negative, ADDED)


# --- the one I/O boundary: which of a prompt's terms the request means -------


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
    content = data["choices"][0]["message"]["content"]
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")  # tolerate fences/preamble
        if start == -1 or end <= start:
            return None
        obj = json.loads(content[start:end + 1])
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
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": build_match_messages(terms, term, system_prompt),
        "temperature": 0.1,  # a lookup, not brainstorming
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chosen = parse_match(json.loads(response.read()), len(terms))
    except Exception as exc:  # model down / unparseable: the words stand alone
        logger.warning("prompt_edit: could not match %r against the prompt (%s)",
                       term, exc)
        return None
    if chosen is not None:
        logger.info("prompt_edit: %r matched the prompt's %r", term, terms[chosen])
    return chosen
