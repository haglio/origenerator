from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from origenerator.request_settings import Setting, setting_called
from origenerator.trigger_words import (
    trigger_words,
    with_trigger_word,
    without_phrases,
    without_trigger_word,
)
from origenerator.workflows.model_files import is_no_lora

_WORD = re.compile(r"[A-Za-z0-9']{2,}")
_NOT_ASKED_FOR = "you didn't ask for that"
PROMPTS = {"positive": "Positive Prompt", "negative": "Negative Prompt"}
_NOTHING_CHANGED = "Nothing changed."
_UNREADABLE = "Couldn't read one of the model's changes."


@dataclass(frozen=True)
class Outcome:
    positive: str
    negative: str
    settings: dict
    line: str


def _quoted(value) -> str:
    return f'"{value}"'


def _words_of(text) -> set[str]:
    return {word.lower() for word in _WORD.findall(str(text or ""))}


def answers_him(reason, asked: list[str]) -> bool:
    words = _words_of(reason)
    return bool(words) and any(words <= _words_of(request) for request in asked)


def _spaced(words: str) -> str:
    return r"\s+".join(re.escape(part) for part in str(words).split())


def _found(text: str, words: str) -> re.Match | None:
    spaced = _spaced(words)
    return re.search(spaced, text, re.IGNORECASE) if spaced else None


def _whole(text: str, words: str) -> bool:
    spaced = _spaced(words)
    return bool(spaced) and re.search(rf"(?<!\w){spaced}(?!\w)", text, re.IGNORECASE) is not None


def _end_of_the_part(text: str, start: int) -> int:
    depth = 0
    for at in range(start, len(text)):
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(text[at], 0)
        if text[at] == "," and depth <= 0:
            return at
    return len(text)


def _joined(before: str, words: str, after: str) -> str:
    before, after = before.rstrip(" ,"), after.lstrip(" ,")
    return ", ".join(part for part in (before, words, after) if part)


_DESCRIBED = {
    "replace": lambda change, prompt: (f"replace {_quoted(change['replace'])} with "
                                       f"{_quoted(change.get('with') or '')} in the {prompt}"),
    "add": lambda change, prompt: f"add {_quoted(change['add'])} to the {prompt}",
    "remove": lambda change, prompt: f"remove {_quoted(change['remove'])} from the {prompt}",
}


def _trigger_words_of(lora) -> tuple[str, ...]:
    return () if is_no_lora(lora) else trigger_words(lora)


class _Applying:
    def __init__(self, positive: str, negative: str, asked: list[str], settings: list[Setting],
                 in_scenes: bool):
        self.positive = positive
        self.negative = negative
        self.asked = asked
        self.settings = settings
        self.in_scenes = in_scenes
        self.changes: dict = {}
        self.said: list[str] = []

    def setting(self, change: dict) -> None:
        setting = setting_called(change.get("setting"), self.settings)
        if setting is None:
            self.said.append(f"There is no setting called {_quoted(change.get('setting'))}.")
            return
        value = setting.taken(change.get("to"))
        if value is None:
            self.said.append(f"{setting.label} can't be {_quoted(change.get('to'))}.")
        elif value == setting.value:
            self.said.append(f"{setting.label} is already {setting.shown()}.")
        elif not answers_him(change.get("for"), self.asked):
            self.said.append(f"Didn't set {setting.label} to {setting.shown(value)}: "
                             f"{_NOT_ASKED_FOR}.")
        else:
            self.changes[setting.key] = value
            swapped = self._trigger_words_swapped(setting, value) if setting.folder == "loras" else ""
            self.said.append(
                f"Set {setting.label} to {setting.shown(value)} (was {setting.shown()}){swapped}.")

    def _trigger_words_swapped(self, setting: Setting, lora) -> str:
        old, new = _trigger_words_of(setting.value), _trigger_words_of(lora)
        without = (without_trigger_word(self.positive, old, in_scenes=self.in_scenes) if old
                   else self.positive)
        taken_out = without != self.positive
        self.positive = (with_trigger_word(without, new, in_scenes=self.in_scenes) if new
                         else without)
        put_in = self.positive != without
        if taken_out and put_in:
            return f", and swapped its trigger word {old[0]} for {new[0]} in the Positive Prompt"
        if taken_out:
            return f", and took its trigger word {old[0]} out of the Positive Prompt"
        if put_in:
            return f", and put its trigger word {new[0]} in the Positive Prompt"
        return ""

    def change(self, change) -> None:
        if not isinstance(change, dict):
            self.said.append(_UNREADABLE)
        elif "setting" in change:
            self.setting(change)
        else:
            self.prompt(change)

    def prompt(self, change: dict) -> None:
        which = str(change.get("prompt") or "").strip().lower()
        edit = next((edit for edit in _DESCRIBED if edit in change), None)
        if which not in PROMPTS or edit is None:
            self.said.append(_UNREADABLE)
        elif not answers_him(change.get("for"), self.asked):
            self.said.append(f"Didn't {_DESCRIBED[edit](change, PROMPTS[which])}: {_NOT_ASKED_FOR}.")
        else:
            self.said.append(self._EDITS[edit](self, which, change))

    def _replace(self, which: str, change: dict) -> str:
        old, new = str(change["replace"]), str(change.get("with") or "")
        text = getattr(self, which)
        found = _found(text, old)
        if found is None:
            return f"Couldn't find {_quoted(old)} in the {PROMPTS[which]}."
        setattr(self, which, text[:found.start()] + new + text[found.end():])
        return f"Replaced {_quoted(old)} with {_quoted(new)} in the {PROMPTS[which]}."

    def _add(self, which: str, change: dict) -> str:
        words, text = str(change["add"]), getattr(self, which)
        if _whole(text, words):
            return f"The {PROMPTS[which]} already has {_quoted(words)}."
        anchor = _found(text, change.get("after") or "")
        at = _end_of_the_part(text, anchor.end()) if anchor else len(text)
        setattr(self, which, _joined(text[:at], words, text[at:]))
        return f"Added {_quoted(words)} to the {PROMPTS[which]}."

    def _remove(self, which: str, change: dict) -> str:
        words, text = str(change["remove"]), getattr(self, which)
        if not _whole(text, words):
            return f"Couldn't find {_quoted(words)} in the {PROMPTS[which]}."
        setattr(self, which, without_phrases(text, [words]))
        return f"Removed {_quoted(words)} from the {PROMPTS[which]}."

    _EDITS: ClassVar[dict] = {"replace": _replace, "add": _add, "remove": _remove}

    def outcome(self, note: str) -> Outcome:
        said = self.said or [" ".join(part for part in (_NOTHING_CHANGED, note) if part)]
        return Outcome(self.positive, self.negative, self.changes, " ".join(said))


def apply_changes(answer: dict, pair: tuple[str, str], *, asked: list[str],
                  settings: list[Setting], in_scenes: bool = False) -> Outcome:
    applying = _Applying(*pair, asked, settings, in_scenes)
    for change in answer.get("changes") or ():
        applying.change(change)
    return applying.outcome(str(answer.get("note") or "").strip())
