from __future__ import annotations

import re
from dataclasses import dataclass

FULL_SIZE = ("Full size: the model as its makers released it, with the most fine detail and the "
             "biggest file.")
HALF_SIZE = ("Half size: the model's numbers are stored in 8 bits instead of 16, so the file is half "
             "as big and runs a little faster, with slightly less fine detail than full size.")
PACKED_HALF_SIZE = ("Half size: packed into 8 bits a way that keeps more fine detail than other "
                    "half-size files, but runs a little slower than they do.")


@dataclass(frozen=True)
class Precision:
    tag: str
    words: str
    explained: str


_PRECISIONS = {p.tag.casefold(): p for p in (
    Precision("fp16", "full size", FULL_SIZE),
    Precision("bf16", "full size", FULL_SIZE),
    Precision("fp8", "half size", HALF_SIZE),
    Precision("int8", "half size", HALF_SIZE),
    Precision("Q8", "half size", PACKED_HALF_SIZE),
)}

_TAG = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_PRECISIONS) + r")(?![A-Za-z0-9])", re.IGNORECASE)


def tagged(tag: str | None) -> Precision | None:
    return _PRECISIONS.get((tag or "").casefold())


def named_in(title: str) -> Precision | None:
    found = _TAG.search(title)
    return None if found is None else _PRECISIONS[found[1].casefold()]


def in_plain_words(title: str, precision: Precision) -> str:
    if named_in(title) is not None:
        return _TAG.sub(precision.words, title, count=1)
    if title.endswith(")"):
        return f"{title[:-1]}, {precision.words})"
    return f"{title} ({precision.words})"


def file_size_sentence(size_bytes: int) -> str:
    return f"This file is {size_bytes / 2**30:.1f} GB."
