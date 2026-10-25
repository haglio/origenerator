"""The spoken ``animate as [Video|Genau] [act]``, said over an image.

The lane defaults to the full-length video and an act left unsaid comes back as
``""`` for :mod:`origenerator.animation_paths` to settle against what the image
shows. The loop lane answers to "go now" too and is said back as "Genau".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from origenerator import animation_paths
from origenerator.act_settings import CATEGORIES, GENAU, VIDEO
from origenerator.voice.text import sounds_like, words

# The verb as whisper renders it, and every rendering of the loop lane's sound.
_LEAD = ("animate", "animated")
_LANE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (VIDEO, ("kino", "video")),
    (GENAU, ("genau", "gunow", "genow", "ganau", "canow",
             "go now", "good now", "can now")),
)

# What the lane is said back as, and what is said for the loop one.
_LANE_SPELLING = {VIDEO: "Kino", GENAU: "Genau"}


def lane_said_as(lane: str) -> str:
    return _LANE_SPELLING.get(lane, lane)
_GENAU_AS_SAID = "go now"


@dataclass(frozen=True)
class AnimateRequest:

    lane: str
    act: str


class Answer(NamedTuple):
    """What one request comes to for one image: the act to run, or the line to
    say instead, and whether that line refuses something the image cannot do
    (said as an error rather than as a question)."""

    act: str | None
    said: str = ""
    unsupported: bool = False


def _after_the_verb(heard: list[str]) -> list[str] | None:
    if not heard or not sounds_like(heard[0], _LEAD):
        return None
    rest = heard[1:]
    return rest[1:] if rest[:1] == ["as"] else rest


def _lane_of(rest: list[str]) -> tuple[str, list[str]]:
    for lane, spellings in _LANE_WORDS:
        for spelling in spellings:
            said = spelling.split()
            if rest[: len(said)] == said:
                return lane, rest[len(said):]
    return VIDEO, rest


def _act_of(rest: list[str], acts) -> str | None:
    """The act ``rest`` names, ``""`` for an utterance that names none, and
    ``None`` for words that are no act -- which is no command at all."""
    if not rest:
        return ""
    said = " ".join(rest)
    for act in acts:
        if act.lower() == said:
            return act
    return None


def match_animate_command(text: str, acts=CATEGORIES) -> AnimateRequest | None:
    rest = _after_the_verb(words(text))
    if rest is None:
        return None
    lane, named = _lane_of(rest)
    act = _act_of(named, acts)
    return None if act is None else AnimateRequest(lane, act)


def animate_command_phrases(acts=CATEGORIES) -> frozenset[str]:
    said = []
    for lane in ("", _GENAU_AS_SAID):
        opening = f"animate as {lane}".strip()
        said.append(opening)
        said.extend(f"{opening} {act.lower()}" for act in acts)
    return frozenset(said)


def what_to_animate(asked: AnimateRequest, state: str, *, content: dict | None = None
                    ) -> Answer:
    """The act to run for an image already in ``state``, or what to say instead:
    two questions (an unsorted image, an unsaid act with a choice to make) and
    two refusals, which are marked so the surface says them as errors."""
    if not state:
        return Answer(None, "this image hasn't been sorted yet — say what it "
                            "shows, then ask again")
    if asked.act:
        if animation_paths.allows(asked.lane, asked.act, state, content=content):
            return Answer(asked.act)
        return Answer(None, f"a “{state}” image can't be animated as "
                            f"“{asked.act}”", unsupported=True)
    offered = animation_paths.acts_for(state, asked.lane, content=content)
    if not offered:
        return Answer(None, f"nothing can be animated from a “{state}” image "
                            "in this lane", unsupported=True)
    if len(offered) > 1:
        named = ", ".join(f"“{act}”" for act in offered)
        return Answer(None, f"which one? {named}")
    return Answer(offered[0])


def animate_command_spelling(text: str, acts=CATEGORIES) -> str | None:
    """The utterance in the words the app names them by -- "gunow" read back as
    "Genau" -- or ``None`` when it is no animation."""
    asked = match_animate_command(text, acts)
    if asked is None:
        return None
    lane = _LANE_SPELLING[asked.lane] if asked.lane != VIDEO else ""
    return " ".join(part for part in ("animate as", lane, asked.act) if part)
