"""Search the gallery by what a generation is of, not by the letters you typed.

A folder is named by a code and a prompt is a paragraph, so a substring filter
over the tree finds nothing at all and one over the prompts finds a fraction of
what is actually there: search ``two women`` and the run you had in mind —
prompted "a pair of dolls on a couch" — never surfaces, and nothing on screen
tells you it exists. This module is the matching layer that closes that gap, in
two tiers:

* A **deterministic** pass that runs on every keystroke, off a prebuilt index,
  with no network anywhere near it. It stems words, folds number words into
  digits, and widens each term through a synonym table — so ``women`` reaches
  "woman", ``two`` reaches "2" and "pair", and ``woman`` reaches "doll".
* An **LLM** pass that widens those same terms further once typing stops, over
  the local endpoint the voice rewrite already uses. It only ever *adds* words
  to the first tier's vocabulary, so a model that is down, slow, or talking
  nonsense leaves the results exactly as the deterministic tier ranked them.

Matching is AND across the query's terms: every term must be reached by
something in the row. That is what lets ``two women`` find "two tall ladies"
— a superset of what was asked for — without also dragging in every row that
merely says "lady". A term that reaches nothing anywhere is reported back in
:attr:`SearchOutcome.unmatched`, so an empty result can name the word that
emptied it instead of leaving the user to guess which one to drop.

Precision is the hard half, and every guard here was put in by a measurement
rather than a hunch — the comments name what each one cost on a real library.
Only the positive prompt, the recipe's names and the names the user gave the
folders a row sits in are searched, decimals stay whole, and bare numbers are
dropped from the recipe: a search is for what a generation is OF, and everything
else in a row is either markup or bookkeeping that happens to be spelled like a
word.

The table below is plain, publishable English, and it is deliberately
incomplete: the words describing the library itself — its own vocabulary for
people, acts and bodies — ride the content overlay's ``search_synonyms``, the
git-ignored file the act keywords and the detail-fix parts already live in. A
group named there that shares one word with a group here merges into it, so the
overlay extends this table rather than standing apart from it.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass, replace

from origenerator import gallery
from origenerator.content import load_content

logger = logging.getLogger(__name__)

# The two orders the results pane offers. Recency is the default because the
# thing you are looking for is usually something you made recently; the recipe
# order answers the other question — "which model/LoRA combination was that?" —
# by putting the rows under headings instead of interleaving them.
SORT_RECENT = "recent"
SORT_RECIPE = "recipe"

# A word is a run of letters and digits — but a decimal number is ONE word, not
# two. Without that, every emphasis weight a prompt carries — ``(term:1.2)`` —
# contributes a bare "2", and since a query's "two" folds to "2" (below),
# searching for two of something matched every prompt that had ever weighted a
# term. Measured against a real library that was 52% of it, which is what made
# the first cut of this search unusable rather than merely imprecise.
_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)+|[a-z0-9]+")

# Written numbers fold onto their digits, in both directions: prompts write
# "two women" as often as "2 women", and the query may say either.
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

# Plurals no suffix rule reaches. Short by design — these are the ones that come
# up describing people, which is most of what a prompt is about, and each one
# left out is a synonym group its singular is in that the plural cannot reach:
# without this, searching "2 women" misses every "two dolls" in the gallery.
_IRREGULAR_PLURALS = {
    "women": "woman", "men": "man", "people": "person", "persons": "person",
    "children": "child", "feet": "foot", "teeth": "tooth", "wives": "wife",
    "lives": "life", "knives": "knife", "leaves": "leaf", "selves": "self",
}

# Words that carry no search intent. Dropped from a query, never from a row —
# a row's stop words cost nothing to index, and dropping a query's keeps
# "a lamp on the table" from demanding that a row also say "on" and "the".
_STOP_WORDS = frozenset(
    ["a", "an", "the", "of", "in", "on", "at", "by", "with", "and", "or", "to", "for", "from", "is", "are", "was", "were", "be", "it", "its", "her", "his", "their", "this", "that", "there", "here", "as", "into", "over", "under"]
)

# Interchangeable words, as groups: any member of a group satisfies a query for
# any other. Deliberately tight — a loose group ("blonde" ~ "golden") fires on
# unrelated rows and the user cannot tell why — with the risky widening left to
# the LLM tier, where it is at least query-specific. Inflections that stemming
# cannot fold ("-ing", "-y") are listed as members rather than guessed at.
#
# The people groups are the ones the overlay is expected to extend: the words
# this library actually prompts with are not words that belong in a public
# repository, and each is one ``search_synonyms`` entry naming a word below.
_SYNONYM_GROUPS = (
    ("woman", "lady", "female", "doll", "babe", "chick", "gal"),
    ("man", "guy", "male", "dude", "boy", "gentleman"),
    # No "both": it is a function word ("both hands", "both of them"), not a
    # count of subjects, and it put a sixteenth of a real library into every
    # search for two of something.
    ("two", "pair", "duo", "couple"),
    ("three", "trio"),
    ("four", "quartet"),
    ("blonde", "blond"),
    ("redhead", "ginger"),
    ("photo", "photograph", "photography", "photographic", "photorealistic"),
    ("video", "clip", "footage", "animation", "animated"),
    ("picture", "image", "render"),
    ("smile", "smiling", "grin", "grinning"),
    ("outdoor", "outdoors", "outside"),
    ("indoor", "indoors", "inside"),
    ("night", "nighttime", "evening"),
    ("dusk", "sunset", "twilight"),
    ("dawn", "sunrise"),
    ("rain", "rainy", "raining"),
    ("snow", "snowy", "snowing"),
    ("beach", "seaside", "shore", "coast"),
    ("sofa", "couch"),
    ("car", "automobile", "vehicle"),
    ("bike", "bicycle"),
)

# How strongly a term is satisfied, by how it was reached. An exact word beats
# a table synonym beats a word the model volunteered — the ordering that keeps
# a literal hit ranked above a widened one when both are present.
_EXACT = 1.0
_SYNONYM = 0.7
_RELATED = 0.6

# Where in a row the hit landed. The positive prompt is what a generation is
# *of*; the model and LoRA names are what made it, so they answer a different
# kind of question and rank below. A name the user typed onto a folder holding
# the row ranks with the prompt: it is the most deliberate word in the index,
# chosen for no reason but to find that folder again.
#
# The negative prompt is searched by neither, and that is a deliberate reversal:
# it was, at a low weight, on the grounds that a word appearing nowhere else
# should still be findable. But a negative prompt is the list of things a run was
# told to keep OUT, so every hit it produces is the opposite of what was asked
# for — three quarters of the results for one real query were rows that had
# explicitly excluded the searched-for thing.
_POSITIVE_WEIGHT = 1.0
_FOLDER_WEIGHT = 1.0
_RECIPE_WEIGHT = 0.7


def _words(text) -> list[str]:
    """The lowercase alphanumeric runs in ``text`` — its searchable words."""
    return _WORD_RE.findall(str(text or "").lower())


def _stem(word: str) -> str:
    """A word reduced to what it shares with its other forms.

    Number words become digits, and plurals lose their ending — the regular ones
    by rule, the handful that have none by name — so "dolls"/"doll",
    "women"/"woman" and "two"/"2" are one key each. Crude on purpose: a real
    stemmer would need a dependency, and the cases that matter in a prompt are
    plurals and counts. Anything it does not recognize is left exactly as
    typed, which costs a widening rather than a wrong match.
    """
    word = _IRREGULAR_PLURALS.get(word, word)
    word = _NUMBER_WORDS.get(word, word)
    if len(word) > 3:
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith(("sses", "shes", "ches", "xes")):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
    return word


def _stems(text) -> set[str]:
    return {_stem(word) for word in _words(text)}


def _synonym_index(groups=()) -> dict[str, frozenset[str]]:
    """Stem → every stem interchangeable with it, from ``groups`` and the built-in
    table.

    Groups that share a member merge, so the overlay can extend a built-in group
    by naming one of its words alongside the new ones. Multi-word members are
    dropped: matching is word by word, so a two-word synonym could never be
    reached, and shredding it into its words would make each of them a synonym
    for the others ("alpha form" teaching that "form" means "alpha").
    """
    merged: list[set[str]] = []
    for group in (*_SYNONYM_GROUPS, *groups):
        stems = set()
        for member in group:
            words = _words(member)
            if len(words) == 1:
                stems.add(_stem(words[0]))
        if len(stems) < 2:
            continue  # a group of one widens nothing
        overlapping = [g for g in merged if g & stems]
        for existing in overlapping:
            stems |= existing
            merged.remove(existing)
        merged.append(stems)
    index: dict[str, frozenset[str]] = {}
    for group in merged:
        frozen = frozenset(group)
        for stem in group:
            index[stem] = frozen
    return index


def _overlay_groups() -> tuple:
    """The library's own interchangeable words, from the content overlay.

    Absent from a public checkout's ``content.example.json``, which is the
    point: the built-in table above is general English, and anything that
    describes the library itself stays in the git-ignored local overlay.
    """
    groups = load_content().get("search_synonyms") or ()
    return tuple(tuple(group) for group in groups if isinstance(group, (list, tuple)))


_SYNONYMS = _synonym_index(_overlay_groups())


@dataclass(frozen=True)
class QueryTerm:
    """One word of a query, with everything that satisfies it.

    ``synonyms`` come from the table, ``related`` from the LLM; they are kept
    apart rather than merged so a table hit can outrank a volunteered one.
    """

    text: str                    # the word as typed, for the "nothing matched X" note
    stem: str
    synonyms: frozenset[str]
    related: frozenset[str]


@dataclass(frozen=True)
class SearchResult:
    """One matching generation and how well it answered the query."""

    row: dict
    score: float


@dataclass(frozen=True)
class SearchOutcome:
    """A finished search: its matches, and the query words nothing could reach."""

    results: tuple[SearchResult, ...]
    unmatched: tuple[str, ...]


@dataclass(frozen=True)
class _Entry:
    """One indexed generation: its stems, split by where they were found.

    Built once per row and reused across keystrokes — re-tokenizing every
    prompt in the gallery on each character typed is the one thing that would
    make this too slow to run while the user types.
    """

    row: dict
    positive: frozenset[str]
    recipe: frozenset[str]
    seeds: frozenset[str]
    # The names the user gave the folders this row sits in. Unlike the other
    # fields this one isn't a property of the row, so it is taken fresh on every
    # re-index rather than carried over with the cached stems — a folder renamed
    # a moment ago has to be findable by its new name now.
    folders: frozenset[str] = frozenset()


def query_words(query: str) -> tuple[str, ...]:
    """The words a query actually searches on: its non-stop words, in order,
    each counted once. A query of nothing but stop words keeps them — better to
    search for "the" than to answer a typed query with everything."""
    words = _words(query)
    kept = [word for word in words if word not in _STOP_WORDS] or words
    seen: set[str] = set()
    ordered = []
    for word in kept:
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    return tuple(ordered)


def parse_query(query: str, *, expansions=None, synonyms=None) -> list[QueryTerm]:
    """``query`` as terms, each carrying the words that satisfy it.

    ``expansions`` is the LLM tier's ``{typed word: [related words]}``; without
    it the terms carry the table's widening alone, which is exactly the
    deterministic search that runs while the user types.
    """
    synonyms = _SYNONYMS if synonyms is None else synonyms
    terms = []
    for word in query_words(query):
        stem = _stem(word)
        table = set(synonyms.get(stem, ())) - {stem}
        volunteered = {_stem(w) for w in (expansions or {}).get(word, ())}
        terms.append(QueryTerm(
            text=word,
            stem=stem,
            synonyms=frozenset(table),
            related=frozenset(volunteered - table - {stem}),
        ))
    return terms


def _field_score(term: QueryTerm, stems: frozenset[str]) -> float:
    """How well ``stems`` satisfies ``term`` — 0.0 if not at all."""
    if term.stem in stems:
        return _EXACT
    if term.synonyms & stems:
        return _SYNONYM
    if term.related & stems:
        return _RELATED
    return 0.0


def _term_score(term: QueryTerm, entry: _Entry) -> float:
    """The best any part of ``entry`` satisfies ``term``, field weighting applied.

    A seed is an identity, not a word: it matches exactly or not at all, and a
    hit is worth as much as a prompt word, so typing a seed lands on that one
    generation rather than ranking it among rows that merely share a digit.
    """
    if term.stem in entry.seeds:
        return _EXACT
    return max(
        _field_score(term, entry.positive) * _POSITIVE_WEIGHT,
        _field_score(term, entry.folders) * _FOLDER_WEIGHT,
        _field_score(term, entry.recipe) * _RECIPE_WEIGHT,
    )


def _recipe_text(row: dict, params: dict) -> str:
    """The words naming what made a row: its workflow, model and LoRA files."""
    workflow = row.get("workflow_name") or ""
    return " ".join((
        workflow,
        gallery.model_label(workflow, params),
        gallery.lora_label(workflow, params),
    ))


def _prompt_text(row: dict, params: dict, key: str) -> str:
    """A row's prompt, from its own column or the params it ran with: the two are
    written together for a generation this app made, but an imported file recovers
    its prompt from the graph in the file's metadata and may carry it in only one
    of them."""
    return str(row.get(key) or params.get(key) or "")


def _recipe_stems(row: dict, params: dict) -> set[str]:
    """The searchable words of what made a row, bare numbers thrown away.

    A model filename is full of them — version parts, dates, step counts,
    ``000002500`` — and none of them is something anyone searches for, while all
    of them collide with the digits a query's number words fold to. Names
    survive whole ("wan22", "sdxl", a LoRA's title); only the pure numbers go.
    """
    return {stem for stem in _stems(_recipe_text(row, params))
            if not stem.replace(".", "").isdigit()}


def _folder_stems(names, memo: dict) -> frozenset[str]:
    """The searchable words of the folder names holding one row.

    ``memo`` caches per name rather than per row: one name usually covers a whole
    folder's worth of rows, so the tokenizing happens once however many rows sit
    under it.
    """
    stems: set[str] = set()
    for name in names:
        cached = memo.get(name)
        if cached is None:
            cached = memo[name] = frozenset(_stems(name))
        stems |= cached
    return frozenset(stems)


def _build_entry(row: dict) -> _Entry:
    params = gallery.parse_params(row.get("params_json"))
    seeds = {str(params.get(key)) for key in ("seed", "noise_seed")
             if params.get(key) is not None}
    if row.get("seed") is not None:
        seeds.add(str(row["seed"]))
    return _Entry(
        row=row,
        positive=frozenset(_stems(_prompt_text(row, params, "positive_prompt"))),
        recipe=frozenset(_recipe_stems(row, params)),
        seeds=frozenset(seeds),
    )


class GallerySearch:
    """The searchable index over the gallery's generations.

    Rebuilt from the row list on each gallery rebuild (:meth:`update`) and
    queried on each keystroke (:meth:`search`). The split is the whole point:
    tokenizing every prompt is linear in the library and belongs to the rebuild,
    while a query is set lookups against what that produced.
    """

    def __init__(self, *, synonyms=None):
        self._entries: dict[str, _Entry] = {}
        self._order: list[str] = []       # prompt_ids, newest first, as given
        self._synonyms = _SYNONYMS if synonyms is None else synonyms

    def update(self, rows, folder_names=None) -> None:
        """Re-index ``rows`` (newest first), keeping the stems already computed
        for a generation that was here last time and only swapping in its fresh
        row dict — a poll rewrites every row object, but not the words in it.

        Only rows that produced an output take part: search is a way of finding
        something to look at, and a failed or still-running run has nothing. A
        prompt_id given twice is indexed once, so the caller can hand over
        several row lists (the gallery's own, and the trash's held rows) without
        first working out whether they overlap.

        ``folder_names`` is ``{prompt_id: [names]}`` — the names the user gave the
        folders each row sits in (see
        :func:`~origenerator.gallery.tree.named_folders_by_row`). It is the one
        part of an entry that isn't a property of the row, so it is taken fresh
        every time rather than carried over with the cached stems.
        """
        entries: dict[str, _Entry] = {}
        order: list[str] = []
        folder_names = folder_names or {}
        memo: dict[str, frozenset[str]] = {}
        for row in rows:
            prompt_id = row.get("prompt_id")
            if not prompt_id or prompt_id in entries \
                    or not gallery.produced_output(row):
                continue
            folders = _folder_stems(folder_names.get(prompt_id, ()), memo)
            known = self._entries.get(prompt_id)
            entries[prompt_id] = replace(
                known if known is not None else _build_entry(row),
                row=row, folders=folders,
            )
            order.append(prompt_id)
        self._entries = entries
        self._order = order

    def search(self, query: str, *, expansions=None, within=None) -> SearchOutcome:
        """Every generation satisfying every word of ``query``, newest first.

        ``within`` narrows the search to a set of prompt_ids — the folder the
        gallery's tree has selected. ``None`` searches the whole index. The
        narrowing happens here rather than by filtering afterwards so that
        :attr:`SearchOutcome.unmatched` is about the folder being searched: a
        word that exists elsewhere in the library but not here is still a word
        that reached nothing, and saying so is the useful answer.

        Scored, but not *sorted* by score: the pane offers recency and recipe,
        and a relevance order the user did not ask for would shuffle the results
        under them each time the LLM tier landed. The score decides membership,
        not position.
        """
        terms = parse_query(query, expansions=expansions, synonyms=self._synonyms)
        if not terms:
            return SearchOutcome((), ())
        results = []
        reached: set[str] = set()
        for prompt_id in self._order:
            if within is not None and prompt_id not in within:
                continue
            entry = self._entries[prompt_id]
            scores = [_term_score(term, entry) for term in terms]
            for term, score in zip(terms, scores):
                if score:
                    reached.add(term.text)
            if all(scores):
                results.append(SearchResult(entry.row, sum(scores) / len(scores)))
        return SearchOutcome(
            tuple(results),
            tuple(term.text for term in terms if term.text not in reached),
        )


def recipe_heading(row: dict) -> str:
    """The model + LoRA combination a row ran on, as a section heading."""
    params = gallery.parse_params(row.get("params_json"))
    workflow = row.get("workflow_name")
    return (f"{gallery.model_label(workflow, params)}"
            f"  ·  {gallery.lora_label(workflow, params)}")


def group_by_recipe(results) -> list[tuple[str, list]]:
    """``results`` split into one section per model + LoRA combination, biggest
    section first (ties alphabetical) and each section still newest-first.

    Biggest first because the combination you use most is the one you are most
    likely to be looking through, and because it makes a one-off run read as the
    outlier it is rather than hiding at the bottom of a long alphabet.
    """
    sections: dict[str, list] = {}
    for result in results:
        sections.setdefault(recipe_heading(result.row), []).append(result)
    return sorted(sections.items(), key=lambda item: (-len(item[1]), item[0]))


# --- the LLM tier: widen the query's words once typing stops ----------------


def build_expansion_messages(words, system_prompt: str) -> list[dict]:
    """The chat messages for one widening: the rules, then the words to widen."""
    listing = "\n".join(f"- {word}" for word in words)
    user = (
        "Search words:\n"
        f"{listing}\n\n"
        'Reply with only JSON: {"<search word>": ["<other word>", ...], …}, '
        "one key per search word above."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _extract_json(content: str) -> dict:
    """Parse a JSON object out of an LLM reply, tolerating fences/preamble."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def parse_expansion(completion: dict, words) -> dict[str, tuple[str, ...]]:
    """The widened vocabulary from a chat completion: ``{search word: related}``.

    Only the words that were asked about are kept, and only single words out of
    each list — a model that answers with a phrase, a key of its own invention,
    or a stray sentence contributes nothing rather than poisoning the match.
    """
    obj = _extract_json(completion["choices"][0]["message"]["content"])
    wanted = {word.lower(): word for word in words}
    expansions: dict[str, tuple[str, ...]] = {}
    for key, value in (obj or {}).items():
        word = wanted.get(str(key).strip().lower())
        if word is None or not isinstance(value, (list, tuple)):
            continue
        related = []
        for item in value:
            item_words = _words(item)
            if len(item_words) == 1 and item_words[0] != word:
                related.append(item_words[0])
        if related:
            expansions[word] = tuple(dict.fromkeys(related))
    return expansions


def expand_query(query: str, *, base_url: str, model: str, system_prompt: str,
                 timeout: float = 15.0) -> dict[str, tuple[str, ...]]:
    """Ask the local LLM which other words a prompt might use for ``query``'s.

    Returns ``{}`` for anything short of a usable answer — no words to widen,
    the endpoint down, a reply that will not parse. The caller's results are
    already on screen by then, so an empty answer is a widening that did not
    happen rather than a search that failed. Mirrors the transport the voice
    rewrite and the recipe matcher use: stdlib ``urllib``, one POST, no deps.
    """
    words = query_words(query)
    if not words:
        return {}
    payload = {
        "model": model,
        "messages": build_expansion_messages(words, system_prompt),
        "temperature": 0.2,  # a vocabulary lookup, not brainstorming
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            expansions = parse_expansion(json.loads(response.read()), words)
    except Exception as exc:  # endpoint down / unparseable: the table tier stands
        logger.warning("search: widening %r failed (%s)", query, exc)
        return {}
    logger.info("search: widened %d of %d words of %r",
                len(expansions), len(words), query)
    return expansions
