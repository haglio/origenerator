from __future__ import annotations

import re
from difflib import SequenceMatcher

SAME = "same"
REMOVED = "removed"
ADDED = "added"

_PIECES = re.compile(r"\s+|[A-Za-z0-9'\-]+(?:\.[0-9]+)?|.")


def _tokens(text: str) -> list[str]:
    return _PIECES.findall(text or "")


def _merge(spans: list) -> list:
    merged: list = []
    for kind, text in spans:
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return [(kind, text) for kind, text in merged if text]


def diff_spans(before: str, after: str) -> list:
    old, new = _tokens(before), _tokens(after)
    spans = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            spans += [(SAME, token) for token in old[i1:i2]]
        else:
            spans += [(REMOVED, token) for token in old[i1:i2]]
            spans += [(ADDED, token) for token in new[j1:j2]]
    return _merge(spans)
