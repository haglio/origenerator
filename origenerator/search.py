from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache

from origenerator import gallery, local_llm
from origenerator.content import load_content
from origenerator.gallery.item_numbers import name_starts_in, without_name_starts
from origenerator.gallery.signatures import READINGS_KEPT
from origenerator.generation_state import in_sight

logger = logging.getLogger(__name__)

SORT_RECENT = "recent"
SORT_MODEL_LORA = "model_lora"
_SORTS_SAVED_BEFORE = {"recipe": SORT_MODEL_LORA}


def saved_sort(mode: str | None) -> str | None:
    return _SORTS_SAVED_BEFORE.get(mode or "", mode)

_WORD_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)+|[a-z0-9]+")
_QUOTED = re.compile(r'["\u201c\u201d]([^"\u201c\u201d]*)(?:["\u201c\u201d]|$)')
_TAG_BREAK = re.compile(r"[,;:!?|()\[\]{}<>\n]|\.(?!\d)")

_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

_IRREGULAR_PLURALS = {
    "women": "woman", "men": "man", "people": "person", "persons": "person",
    "children": "child", "feet": "foot", "teeth": "tooth", "wives": "wife",
    "lives": "life", "knives": "knife", "leaves": "leaf", "selves": "self",
}

_STOP_WORDS = frozenset(
    ["a", "an", "the", "of", "in", "on", "at", "by", "with", "and", "or", "to", "for", "from", "is", "are", "was", "were", "be", "it", "its", "her", "his", "their", "this", "that", "there", "here", "as", "into", "over", "under"]
)

_SYNONYM_GROUPS = (
    ("woman", "lady", "female", "doll", "babe", "chick", "gal"),
    ("man", "guy", "male", "dude", "boy", "gentleman"),
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

_EXACT = 1.0
_SYNONYM = 0.7
_RELATED = 0.6

_POSITIVE_WEIGHT = 1.0
_FOLDER_WEIGHT = 1.0
_MADE_WITH_WEIGHT = 0.7
_SHORTEST_NAME_START = 4
_LONGEST_UNSTEMMED = 3


def _words(text) -> list[str]:
    return _WORD_RE.findall(str(text or "").lower())


@lru_cache(maxsize=READINGS_KEPT)
def _stem(word: str) -> str:
    word = _IRREGULAR_PLURALS.get(word, word)
    word = _NUMBER_WORDS.get(word, word)
    if len(word) > _LONGEST_UNSTEMMED:
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith(("sses", "shes", "ches", "xes")):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
    return word


@lru_cache(maxsize=READINGS_KEPT)
def _tags(text: str) -> tuple[tuple[str, ...], ...]:
    return tuple(words for words in (tuple(_words(part)) for part in _TAG_BREAK.split(text))
                 if words)


@lru_cache(maxsize=READINGS_KEPT)
def _stems(text: str) -> frozenset[str]:
    return frozenset(_stem(word) for tag in _tags(text) for word in tag)


def _unquoted(query: str) -> str:
    return _QUOTED.sub(" ", query)


def _quoted(query: str) -> tuple[tuple[str, ...], ...]:
    return tuple(dict.fromkeys(words for words in (tuple(_words(part))
                                                   for part in _QUOTED.findall(query)) if words))


def _synonym_index(groups=()) -> dict[str, frozenset[str]]:
    merged: list[set[str]] = []
    for group in (*_SYNONYM_GROUPS, *groups):
        stems = set()
        for entry in group:
            words = _words(entry)
            if len(words) == 1:
                stems.add(_stem(words[0]))
        if len(stems) <= 1:
            continue
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
    groups = load_content().get("search_synonyms") or ()
    return tuple(tuple(group) for group in groups if isinstance(group, (list, tuple)))


_SYNONYMS = _synonym_index(_overlay_groups())


@dataclass(frozen=True)
class QueryTerm:
    text: str
    stem: str
    synonyms: frozenset[str] = frozenset()
    related: frozenset[str] = frozenset()
    side_by_side: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchResult:
    row: dict
    score: float


@dataclass(frozen=True)
class SearchOutcome:
    results: tuple[SearchResult, ...]
    unmatched: tuple[str, ...]


@dataclass(frozen=True)
class _Entry:
    row: dict
    positive: frozenset[str]
    made_with: frozenset[str]
    seeds: frozenset[str]
    folders: frozenset[str] = frozenset()
    name: str = ""
    tags: tuple[tuple[str, ...], ...] = ()
    folder_tags: tuple[tuple[str, ...], ...] = ()


def query_words(query: str) -> tuple[str, ...]:
    words = _words(without_name_starts(_unquoted(query)))
    kept = [word for word in words if word not in _STOP_WORDS] or words
    seen: set[str] = set()
    ordered = []
    for word in kept:
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    return tuple(ordered)


def parse_query(query: str, *, expansions=None, synonyms=None) -> list[QueryTerm]:
    synonyms = _SYNONYMS if synonyms is None else synonyms
    terms = [QueryTerm(text=start, stem=start.lower())
             for start in dict.fromkeys(name_starts_in(_unquoted(query)))]
    terms += [QueryTerm(text=" ".join(words), stem="", side_by_side=words)
              for words in _quoted(query)]
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
    if term.stem in stems:
        return _EXACT
    if term.synonyms & stems:
        return _SYNONYM
    if term.related & stems:
        return _RELATED
    return 0.0


def _term_score(term: QueryTerm, entry: _Entry) -> float:
    if term.side_by_side:
        return _EXACT if _says(entry, term.side_by_side) else 0.0
    if term.stem in entry.seeds or _starts_the_name(term.stem, entry.name):
        return _EXACT
    return max(
        _field_score(term, entry.positive) * _POSITIVE_WEIGHT,
        _field_score(term, entry.folders) * _FOLDER_WEIGHT,
        _field_score(term, entry.made_with) * _MADE_WITH_WEIGHT,
    )


def _made_with_text(row: dict, params: dict) -> str:
    workflow = row.get("workflow_name") or ""
    return " ".join((
        workflow,
        gallery.model_label(workflow, params),
        gallery.lora_label(workflow, params),
    ))


def _prompt_text(row: dict, params: dict, key: str) -> str:
    return str(row.get(key) or params.get(key) or "")


def _made_with_stems(row: dict, params: dict) -> set[str]:
    return {stem for stem in _stems(_made_with_text(row, params))
            if not stem.replace(".", "").isdigit()}


def _folder_stems(names) -> frozenset[str]:
    return frozenset().union(*(_stems(name) for name in names))


def _says(entry: _Entry, words: tuple[str, ...]) -> bool:
    count = len(words)
    return any(tag[at:at + count] == words
               for tag in (*entry.tags, *entry.folder_tags)
               for at in range(len(tag) - count + 1))


def _starts_the_name(typed: str, name: str) -> bool:
    return len(typed) >= _SHORTEST_NAME_START and name.startswith(typed)


def content_stems(row: dict) -> frozenset[str]:
    params = gallery.parse_params(row.get("params_json"))
    return _stems(_prompt_text(row, params, "positive_prompt")) - _STOP_WORDS


def _build_entry(row: dict) -> _Entry:
    params = gallery.parse_params(row.get("params_json"))
    seeds = {str(params.get(key)) for key in gallery.GENERATION_SEED_KEYS
             if params.get(key) is not None}
    if row.get("seed") is not None:
        seeds.add(str(row["seed"]))
    prompt = _prompt_text(row, params, "positive_prompt")
    return _Entry(
        row=row,
        positive=_stems(prompt),
        tags=_tags(prompt),
        made_with=frozenset(_made_with_stems(row, params)),
        seeds=frozenset(seeds),
    )


class GallerySearch:
    def __init__(self, *, synonyms=None):
        self._entries: dict[str, _Entry] = {}
        self._order: list[str] = []
        self._synonyms = _SYNONYMS if synonyms is None else synonyms

    def update(self, rows, folder_names=None, item_name=None) -> None:
        entries: dict[str, _Entry] = {}
        order: list[str] = []
        folder_names = folder_names or {}
        for row in rows:
            prompt_id = row.get("prompt_id")
            if not prompt_id or prompt_id in entries \
                    or not gallery.produced_output(row) or not in_sight(row):
                continue
            named = folder_names.get(prompt_id, ())
            folders = _folder_stems(named)
            name = (item_name(prompt_id) if item_name else "").lower()
            known = self._entries.get(prompt_id)
            entries[prompt_id] = replace(
                known if known is not None else _build_entry(row),
                row=row, folders=folders, name=name,
                folder_tags=tuple(tag for folder in named for tag in _tags(folder)),
            )
            order.append(prompt_id)
        self._entries = entries
        self._order = order

    def widens(self, query: str) -> bool:
        return any(not self._starts_a_name(word) for word in query_words(query))

    def _starts_a_name(self, word: str) -> bool:
        return any(_starts_the_name(word, entry.name) for entry in self._entries.values())

    def search(self, query: str, *, expansions=None, within=None) -> SearchOutcome:
        expansions = {word: related for word, related in (expansions or {}).items()
                      if not self._starts_a_name(word)}
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
            for term, score in zip(terms, scores, strict=True):
                if score:
                    reached.add(term.text)
            if all(scores):
                results.append(SearchResult(entry.row, sum(scores) / len(scores)))
        return SearchOutcome(
            tuple(results),
            tuple(term.text for term in terms if term.text not in reached),
        )


def model_lora_heading(row: dict) -> str:
    params = gallery.parse_params(row.get("params_json"))
    workflow = row.get("workflow_name")
    return (f"{gallery.model_label(workflow, params)}"
            f"  ·  {gallery.lora_label(workflow, params)}")


@dataclass(frozen=True)
class SearchTerms:
    sort_mode: str
    query: str
    outcome: object
    scope: str = ""
    collapsed: object = ()
    on_section_toggled: object = None
    still_searching: bool = False


@dataclass(frozen=True)
class SearchTile:
    row: dict
    group: object | None = None
    rows: list = field(default_factory=list)


def group_by_model_lora(results) -> list[tuple[str, list]]:
    sections: dict[str, list] = {}
    for result in results:
        sections.setdefault(model_lora_heading(result.row), []).append(result)
    return sorted(sections.items(), key=lambda item: (-len(item[1]), item[0]))



def build_expansion_messages(words, system_prompt: str) -> list[dict]:
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


def parse_expansion(completion: dict, words) -> dict[str, tuple[str, ...]]:
    obj = local_llm.answer_of(completion)
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
    words = query_words(query)
    if not words:
        return {}
    try:
        expansions = parse_expansion(local_llm.ask(
            build_expansion_messages(words, system_prompt),
            base_url=base_url, model=model, temperature=0.2, timeout=timeout), words)
    except Exception as exc:
        logger.warning("search: widening %r failed (%s)", query, exc)
        return {}
    logger.info("search: widened %d of %d words of %r",
                len(expansions), len(words), query)
    return expansions
