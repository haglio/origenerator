from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from origenerator import animation_paths
from origenerator.action_settings import GENAU, VIDEO
from origenerator.action_vocabulary import vocabulary
from origenerator.animation_names import JOINER, Animation
from origenerator.media import MediaType
from origenerator.voice.text import sounds_like, words

# Whisper's renderings of the verb and of the loop lane's sound.
_LEAD = ("animate", "animated")
_LANE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (VIDEO, ("kino", "video")),
    (GENAU, ("genau", "gunow", "genow", "ganau", "canow",
             "go now", "good now", "can now")),
)

_LANE_SPELLING = {VIDEO: "Kino", GENAU: "Genau"}


def lane_said_as(lane: str) -> str:
    return _LANE_SPELLING.get(lane, lane)
_GENAU_AS_SAID = "go now"


@dataclass(frozen=True)
class AnimateRequest:

    lane: str
    action: str


class Answer(NamedTuple):
    action: str | None
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


def _said_as(name: str) -> str:
    return name.replace(JOINER, " plus ").lower()


def spoken_actions(content: dict | None = None) -> dict[str, str]:
    words = vocabulary(MediaType.VIDEO, content)
    named = {" ".join((_said_as(button), *(box.lower() for box in checked))):
             Animation(button, checked).name
             for button in words.buttons
             for checked in ((), *((box,) for box in words.checkboxes))}
    named.update({box.lower(): Animation(button, (box,)).name
                  for box, button in words.said_alone.items()})
    return {form: name for said, name in named.items() for form in _forms(said, words.heard_as)}


def _forms(said: str, heard_as: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    forms = [said]
    for name, heard in heard_as.items():
        own = f" {_said_as(name)} "
        forms.extend(f" {form} ".replace(own, f" {other.lower()} ").strip()
                     for form in list(forms) if own in f" {form} " for other in heard)
    return tuple(dict.fromkeys(forms))


def _heard_as(actions) -> dict[str, str]:
    return dict(actions) if isinstance(actions, dict) else {_said_as(a): a for a in actions}


def _action_of(rest: list[str], actions) -> str | None:
    if not rest:
        return ""
    return _heard_as(actions).get(" ".join(rest))


def match_animate_command(text: str, actions=None) -> AnimateRequest | None:
    rest = _after_the_verb(words(text))
    if rest is None:
        return None
    lane, named = _lane_of(rest)
    action = _action_of(named, spoken_actions() if actions is None else actions)
    return None if action is None else AnimateRequest(lane, action)


def animate_command_phrases(actions=None) -> frozenset[str]:
    actions = spoken_actions() if actions is None else actions
    said = []
    for lane in ("", _GENAU_AS_SAID):
        opening = f"animate as {lane}".strip()
        said.append(opening)
        said.extend(f"{opening} {spoken}" for spoken in _heard_as(actions))
    return frozenset(said)


def what_to_animate(asked: AnimateRequest, state: str, *, content: dict | None = None
                    ) -> Answer:
    if not state:
        return Answer(None, "this image hasn't been sorted yet — say what it "
                            "shows, then ask again")
    if asked.action:
        if animation_paths.allows(asked.lane, asked.action, state, content=content):
            return Answer(asked.action)
        return Answer(None, f"a “{state}” image can't be animated as "
                            f"“{asked.action}”", unsupported=True)
    offered = animation_paths.actions_for(state, asked.lane, content=content)
    if not offered:
        return Answer(None, f"nothing can be animated from a “{state}” image "
                            "in this lane", unsupported=True)
    if len(offered) > 1:
        named = ", ".join(f"“{action}”" for action in offered)
        return Answer(None, f"which one? {named}")
    return Answer(offered[0])


def animate_command_spelling(text: str, actions=None) -> str | None:
    asked = match_animate_command(text, actions)
    if asked is None:
        return None
    lane = _LANE_SPELLING[asked.lane] if asked.lane != VIDEO else ""
    return " ".join(part for part in ("animate as", lane, asked.action) if part)
