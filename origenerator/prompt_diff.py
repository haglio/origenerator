"""Showing what a prompt edit changed: the old text and the new, in one line.

A request's whole value is that you can see what it did — "no silver earrings"
is only trustworthy if the prompt it produced shows the earrings struck out and
nothing else disturbed. So rather than describing the change, this renders it:
one run of text with what went struck through and what arrived highlighted.

Derived from the two prompts alone, never from the edit that made them, so it
tells the truth about a revision however it was produced. Word-level, because
that is the grain a prompt reads at — a changed term should show as a term
replaced, not as a scatter of altered letters.

Pure and Qt-free: :func:`diff_spans` is the model, and the two surfaces that
show a diff paint it themselves with ``QTextCharFormat``.
"""

import re
from difflib import SequenceMatcher

SAME = "same"
REMOVED = "removed"
ADDED = "added"

# Words, numbers (decimal point included, so a weight is one piece), whitespace
# runs, and every other character on its own — so a rebuilt run is
# character-for-character the original, and punctuation moves independently of
# the word beside it. That last part is what keeps adding a term to the end of a
# prompt from marking the word before it as changed too, just because a comma
# arrived after it.
_PIECES = re.compile(r"\s+|[A-Za-z0-9'\-]+(?:\.[0-9]+)?|.")


def _tokens(text: str) -> list[str]:
    return _PIECES.findall(text or "")


def _merge(spans: list) -> list:
    """Neighboring spans of one kind joined, so a run of changed words renders
    as one mark rather than a mark per word."""
    merged: list = []
    for kind, text in spans:
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return [(kind, text) for kind, text in merged if text]


def diff_spans(before: str, after: str) -> list:
    """``(kind, text)`` pieces covering both versions in reading order.

    ``kind`` is :data:`SAME`, :data:`REMOVED` (in ``before`` only) or
    :data:`ADDED` (in ``after`` only). Concatenating the same-and-removed pieces
    gives back ``before``; the same-and-added pieces give back ``after``.
    """
    old, new = _tokens(before), _tokens(after)
    spans = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            spans += [(SAME, token) for token in old[i1:i2]]
        else:  # replace / delete / insert — what left, then what arrived
            spans += [(REMOVED, token) for token in old[i1:i2]]
            spans += [(ADDED, token) for token in new[j1:j2]]
    return _merge(spans)
