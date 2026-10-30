"""Notes the local model writes on the whole prompt collection, a tenth of it at a
time, which a Request is then answered with in place of the prompts themselves."""
from __future__ import annotations

import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from origenerator import local_llm
from origenerator.prompts import COLLECTION_NOTES_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

WINDOW_TOKENS = 40960
BATCH_CHARS = 90_000  # about 22,000 tokens of prompts, read inside the window above
GROWTH = 0.1  # this much more of the collection than the notes describe, and they are retaken
_NOTE_TOKENS = 600
_PATTERNS_TOKENS = 1200
_WINDOW_MARGIN = 256
_ASK_TIMEOUT_S = 1800.0


@dataclass
class CollectionNotes:
    prompt_count: int
    batches: int
    batch_notes: list[str] = field(default_factory=list)
    patterns: str = ""
    batch_chars: int = BATCH_CHARS

    @property
    def complete(self) -> bool:
        return bool(self.patterns)


def batches(prompts: list[str], limit: int) -> Iterator[list[str]]:
    batch: list[str] = []
    size = 0
    for prompt in prompts:
        if batch and size + len(prompt) > limit:
            yield batch
            batch, size = [], 0
        batch.append(prompt)
        size += len(prompt)
    if batch:
        yield batch


def due(notes: CollectionNotes | None, prompt_count: int) -> bool:
    if prompt_count <= 0:
        return False
    if notes is None or not notes.complete:
        return True
    return prompt_count >= notes.prompt_count + math.ceil(notes.prompt_count * GROWTH)


def read(path: Path) -> CollectionNotes | None:
    try:
        return CollectionNotes(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def write(path: Path, notes: CollectionNotes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(asdict(notes), indent=1), encoding="utf-8")
    os.replace(partial, path)


def _numbered(prompts: list[str]) -> str:
    return "\n".join(f"{i}. {prompt}" for i, prompt in enumerate(prompts, 1))


def _note_request(batch: list[str]) -> str:
    return (
        f"Below are {len(batch)} prompts from the collection, numbered, one per line. "
        "Write notes of at most 250 words on this batch: the subjects and settings "
        "that recur, how a typical prompt is built (its parts, their order, its "
        "length, phrases that come back), the ways the prompts differ from one "
        "another, and anything that stands out. Quote short phrases. Notes only, "
        f"no preamble.\n\n{_numbered(batch)}"
    )


def _patterns_request(notes: CollectionNotes) -> str:
    joined = "\n\n".join(f"Batch {i}:\n{note}" for i, note in enumerate(notes.batch_notes, 1))
    return (
        f"Here are notes written on each batch of the whole collection ({notes.prompt_count} "
        "prompts). Under the heading PATTERNS, write at most 400 words on what runs "
        "through the whole collection: the subjects, the settings, how the prompts are "
        "built, the phrases that keep coming back, and the ways the prompts vary. "
        f"Nothing before the heading and nothing after the words.\n\nNOTES\n{joined}"
    )


def _messages(user_text: str) -> list[dict]:
    return [{"role": "system", "content": COLLECTION_NOTES_SYSTEM_PROMPT},
            {"role": "user", "content": user_text}]


def _fills_the_window(answer: dict, answer_tokens: int) -> bool:
    return local_llm.tokens_read(answer) >= WINDOW_TOKENS - answer_tokens - _WINDOW_MARGIN


def take(prompts: list[str], notes: CollectionNotes | None, *, ask: Callable,
         let_go: Callable[[], None], batch_chars: int = BATCH_CHARS, clock=time.monotonic,
         budget_s: float) -> CollectionNotes:
    started = clock()
    if notes is None or notes.prompt_count != len(prompts) or notes.complete:
        notes = CollectionNotes(prompt_count=len(prompts), batches=0,
                                batch_chars=notes.batch_chars if notes else batch_chars)
    groups = list(batches(prompts, notes.batch_chars))
    notes.batches = len(groups)
    while len(notes.batch_notes) < len(groups):
        if clock() - started >= budget_s:
            let_go()
            return notes
        batch = groups[len(notes.batch_notes)]
        batch_started = clock()
        answer = ask(_messages(_note_request(batch)), temperature=0.6, timeout=_ASK_TIMEOUT_S,
                     json_answer=False, reads_tokens=WINDOW_TOKENS, answers_tokens=_NOTE_TOKENS,
                     stays_loaded=None)
        if _fills_the_window(answer, _NOTE_TOKENS):
            notes.batch_chars //= 2
            notes.batch_notes = []
            groups = list(batches(prompts, notes.batch_chars))
            notes.batches = len(groups)
            logger.info("Collection notes: a batch filled the model's window; batches of %d "
                        "characters from here, started over", notes.batch_chars)
            continue
        notes.batch_notes.append(local_llm.text_of(answer))
        logger.info("Collection notes: batch %d of %d, %d prompts, %d tokens, %.0f s",
                    len(notes.batch_notes), len(groups), len(batch),
                    local_llm.tokens_read(answer), clock() - batch_started)
    if clock() - started >= budget_s:
        let_go()
        return notes
    answer = ask(_messages(_patterns_request(notes)), temperature=0.8, timeout=_ASK_TIMEOUT_S,
                 json_answer=False, reads_tokens=WINDOW_TOKENS, answers_tokens=_PATTERNS_TOKENS,
                 stays_loaded="0")
    notes.patterns = local_llm.text_of(answer)
    logger.info("Collection notes written: %d prompts in %d batches, %.0f s this sitting",
                notes.prompt_count, notes.batches, clock() - started)
    return notes
