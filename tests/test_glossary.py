"""The glossary names every thing on screen once, and the code says those names.

``glossary.json`` carries one row per thing a person can see in Origenerator: the
word on the screen, the word the user says, the words the code says today and the
one word it is to say. These tests hold the code to it, so a name is a row he
rules on rather than a word an agent invents.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "glossary.json"
SCANNED = (ROOT / "origenerator", ROOT / "tools")

STATUSES = {"ruled", "his_word", "agreed", "unruled", "kept"}
REQUIRED = {"id", "thing", "screen", "his_word", "code_today", "code_word", "status"}

# Nouns that name something drawn on a screen, as programmers reach for them.
# One of these in the code is a thing the glossary has to have a row for.
SCREEN_NOUNS = frozenset((
    "tile", "card", "badge", "chip", "scrim", "plate", "strip", "cell", "slot", "pane",
    "panel", "console", "band", "toast", "banner", "gutter", "shelf", "tray", "drawer",
    "dial", "pill", "ribbon", "dock", "sidebar", "swatch", "plaque", "placard", "sticker",
    "lozenge", "bubble", "veil", "backdrop", "halo", "glow", "sheet", "deck", "hud", "map",
    "bank", "toolbar", "collage", "breadcrumb", "splash", "notice", "recents", "bookmark",
))

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_IDENTIFIER_ONLY = re.compile(r"[A-Za-z0-9_]+")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def _words_of(identifier: str) -> list[str]:
    return [m.group(0) for piece in identifier.split("_") for m in _WORD.finditer(piece)]


def _source_lines():
    for folder in SCANNED:
        for path in sorted(folder.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                yield path.relative_to(ROOT).as_posix(), number, line


def _word_streams():
    """Each source line as the lowercase words its identifiers are made of."""
    for where, number, line in _source_lines():
        tokens = _IDENTIFIER.findall(line)
        words = [w for token in tokens for w in _words_of(token)]
        yield where, number, tokens, words, line


@pytest.fixture(scope="module")
def glossary():
    return json.loads(GLOSSARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def streams():
    return list(_word_streams())


def _said_somewhere(phrase: str, streams) -> bool:
    wanted = " " + " ".join(phrase.lower().split()) + " "
    return any(wanted in " " + " ".join(w.lower() for w in words) + " " for _, _, _, words, _ in streams)


def _kept(token: str, line: str, keep: list[str]) -> bool:
    """A keep that is one identifier spares the tokens holding it; one with a space
    or a stop in it is a phrase, and spares the lines that say it."""
    return any(k.lower() in (token if _IDENTIFIER_ONLY.fullmatch(k) else line).lower() for k in keep)


def _counted(word: str, token: str) -> bool:
    """An acronym (CLIP, TOC, HUD) is not the word; a constant spelled in capitals is."""
    return not word.isupper() or (token.isupper() and "_" in token)


def _forms(word: str) -> set[str]:
    return {word, word + "s", word + "es"}


def _says(wanted: list[str], words: list[str]) -> bool:
    return words[:-1] == wanted[:-1] and words[-1] in _forms(wanted[-1])


def _mentions(retired: str, keep: list[str], streams) -> list[str]:
    """Where the code still says ``retired``, outside ``keep``: a word as a word of
    its own, plural or not; a phrase as those words one after another, in one
    identifier or across a line."""
    wanted = retired.lower().split()
    hits = []
    for where, number, tokens, _, line in streams:
        said = [(w.lower(), token) for token in tokens if not _kept(token, line, keep)
                for w in _words_of(token) if _counted(w, token)]
        for at in range(len(said) - len(wanted) + 1):
            run = said[at:at + len(wanted)]
            if _says(wanted, [w for w, _ in run]):
                hits.append(f"{where}:{number} {' '.join(token for _, token in run)}")
                break
    return hits


def test_every_row_names_its_thing_and_stands_in_one_of_the_known_states(glossary):
    ids = [row["id"] for row in glossary["things"]]
    assert len(ids) == len(set(ids)), "two rows share an id"
    for row in glossary["things"]:
        missing = REQUIRED - set(row)
        assert not missing, f"{row.get('id')} lacks {sorted(missing)}"
        assert row["status"] in STATUSES, f"{row['id']}: unknown status {row['status']!r}"
        assert row["thing"].strip(), f"{row['id']} does not say what it is"
        assert row["code_today"], f"{row['id']} names no word the code says today"
        if row["status"] == "ruled":
            assert row.get("ruled"), f"{row['id']} is ruled but says not when or where"
            assert row["code_word"], f"{row['id']} is ruled but names no code word"


def test_every_word_the_glossary_says_the_code_says_is_still_in_the_code(glossary, streams):
    stale = [f"{row['id']}: {phrase!r}"
             for row in glossary["things"]
             for phrase in row["code_today"]
             if not _said_somewhere(phrase, streams)]
    assert not stale, "the glossary names code words the code no longer says:\n" + "\n".join(stale)


def test_a_word_the_glossary_retired_is_gone_from_the_code(glossary, streams):
    left = []
    for row in glossary["things"]:
        for word in row.get("retired", []):
            left += [f"{row['id']} retired {word!r}: {hit}"
                     for hit in _mentions(word, row.get("keep", []), streams)]
    assert not left, "retired words still in the code:\n" + "\n".join(left[:40])


def test_every_screen_noun_in_the_code_has_a_row_in_the_glossary(glossary, streams):
    named = {w.lower()
             for row in glossary["things"]
             for phrase in row["code_today"] + [row["code_word"] or ""] + row.get("retired", [])
             for w in phrase.split()}
    said = {w.lower() for _, _, _, words, _ in streams for w in words}
    outside = sorted((SCREEN_NOUNS & said) - named)
    assert not outside, f"the code says these nouns for things on screen and the glossary has no row for them: {outside}"
