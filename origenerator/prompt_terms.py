from __future__ import annotations

import re

# ComfyUI (term:weight) form; unweighted is 1.0, each wrapping paren 1.1x
WEIGHT_STEP = 0.1
_PAREN_WEIGHT = 1.1


def end_of_the_term(prompt: str, start: int) -> int:
    depth = 0
    for at in range(start, len(prompt)):
        char = prompt[at]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            return at
    return len(prompt)


def segments_of(prompt: str) -> list[str]:
    prompt = prompt or ""
    parts, start = [], 0
    while start <= len(prompt):
        end = end_of_the_term(prompt, start)
        parts.append(prompt[start:end])
        start = end + 1
    return parts


def unwrapped(segment: str) -> tuple:
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
    words = term.split()
    if not words:
        return False
    pattern = r"\s+".join(re.escape(word) for word in words)
    return re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE) is not None


def bare_terms(prompt: str) -> list[str]:
    return [unwrapped(segment)[0] for segment in segments_of(prompt)]


def terms_with_places(prompt: str) -> list[tuple[str, int, int]]:
    places, at = [], 0
    for segment in segments_of(prompt):
        start = at + len(segment) - len(segment.lstrip())
        places.append((unwrapped(segment)[0], start, start + len(segment.strip())))
        at += len(segment) + 1
    return places


def literal_match(terms: list[str], term: str) -> int | None:
    for i, text in enumerate(terms):
        if _mentions(text, term):
            return i
    return None


def index_of(prompt: str, term: str) -> int | None:
    return literal_match(bare_terms(prompt), term)


def tidy(prompt: str) -> str:
    return re.sub(r"^[\s,]+|[\s,]+$", "", prompt)


def _format_weight(weight: float) -> str:
    return f"{round(weight, 2):g}"


def reweighted(prompt: str, index: int, delta: float) -> str:
    segments = segments_of(prompt)
    segment = segments[index]
    term, weight = unwrapped(segment)
    weight = round(weight + delta, 2)
    lead = segment[:len(segment) - len(segment.lstrip())]
    segments[index] = f"{lead}({term}:{_format_weight(weight)})"
    return tidy(",".join(segments))


def without_nothing_weighted(prompt: str) -> str:
    segments = segments_of(prompt)
    kept = [segment for segment in segments if unwrapped(segment)[1] > 0]
    return prompt if len(kept) == len(segments) else tidy(",".join(kept))


_WEIGHTED = re.compile(r"\(([^()]*?)\s*:\s*[0-9]*\.?[0-9]+\s*\)")


def without_weights(prompt: str) -> str:
    bare = None
    while bare != prompt:
        bare, prompt = prompt, _WEIGHTED.sub(r"\1", prompt)
    return ", ".join(unwrapped(segment)[0] for segment in segments_of(prompt))
