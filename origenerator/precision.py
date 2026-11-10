from __future__ import annotations

import re
from dataclasses import dataclass

FULL_SIZE_TRADEOFF = ("The model as its makers released it, and the best quality. The biggest file: one bigger "
                      "than the graphics card's memory runs slower, since ComfyUI keeps part of it in the "
                      "computer's memory.")


@dataclass(frozen=True)
class Precision:
    tag: str
    words: str
    stands_for: str
    tradeoff: str

    def explained(self) -> str:
        return f"{self.tag}: {self.stands_for}. {self.tradeoff}"


_PRECISIONS = {p.tag.casefold(): p for p in (
    Precision("fp16", "full size", "floating point, 16 bits", FULL_SIZE_TRADEOFF),
    Precision("bf16", "full size", "brain floating point, 16 bits", FULL_SIZE_TRADEOFF),
    Precision("fp8", "half size", "floating point, 8 bits",
              "Half the file of full size, and the fastest on the graphics card, with slightly less fine "
              "detail than full size."),
    Precision("int8", "half size, int8", "integer, 8 bits",
              "Half the file of full size, rounded a different way from fp8: about the same quality as fp8, "
              "or a little closer to full size."),
    Precision("Q8", "half size, packed", "quantized, 8 bits",
              "Half the file of full size, with detail closer to full size than fp8, but slower than fp8, "
              "since it is unpacked while it runs."),
)}

_TAG = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_PRECISIONS) + r")(?![A-Za-z0-9])", re.IGNORECASE)


def tagged(tag: str | None) -> Precision | None:
    return _PRECISIONS.get((tag or "").casefold())


def named_in(title: str) -> Precision | None:
    found = _TAG.search(title)
    return None if found is None else _PRECISIONS[found[1].casefold()]


def in_plain_words(title: str, precision: Precision) -> str:
    return _TAG.sub(precision.words, title, count=1)


def file_size_sentence(size_bytes: int) -> str:
    return f"This file is {size_bytes / 2**30:.1f} GB."
