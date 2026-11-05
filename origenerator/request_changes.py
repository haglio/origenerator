from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import ClassVar

from origenerator.prompt_terms import (
    WEIGHT_STEP,
    end_of_the_term,
    index_of,
    reweighted,
    segments_of,
    unwrapped,
)
from origenerator.request_settings import Setting, setting_called
from origenerator.trigger_words import (
    lacks_trigger_word,
    trigger_words,
    with_trigger_words_swapped,
    without_phrases,
    without_trigger_word,
)
from origenerator.workflows.model_files import is_no_lora

_WORD = re.compile(r"[A-Za-z0-9']{2,}")
_ALIKE_ENOUGH_TO_BE_ONE_PART = 0.5
PROMPTS = {"positive": "Positive Prompt", "negative": "Negative Prompt"}
_NOTHING_CHANGED = "Nothing changed."
_SAYING_NOTHING = frozenset({
    "the", "and", "in", "on", "of", "with", "to", "it", "at", "an", "is", "for", "or", "no", "not",
    "her", "his", "him", "she", "he", "you", "me", "my", "please", "make", "have", "only", "more",
    "less", "use", "but", "that", "this", "did", "didn't", "don't", "do", "be", "as", "by",
    "should", "shouldn't", "would", "could", "can", "are", "was", "has", "they", "them", "their",
    "its", "there", "from", "into", "than", "then", "also", "just", "some", "any", "all",
})
_UNREADABLE = "Couldn't read one of the model's changes."
_LEFT_OUT = re.compile(r"(?:no|without)\s+(?:(?:a|an|any|the)\s+)?(\S.*)", re.IGNORECASE)


@dataclass(frozen=True)
class Prompts:
    in_scenes: bool = False
    take_weights: bool = True


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


def _naming(text) -> set[str]:
    return {word.removesuffix("s") for word in _words_of(text) - _SAYING_NOTHING}


def answers_him(reason, asked: list[str]) -> bool:
    return bool(_naming(reason) & set().union(*(_naming(request) for request in asked)))


def _spaced(words: str) -> str:
    return r"\s+".join(re.escape(part) for part in str(words).split())


def _found(text: str, words: str) -> re.Match | None:
    spaced = _spaced(words)
    return re.search(spaced, text, re.IGNORECASE) if spaced else None


def _whole(text: str, words: str) -> bool:
    spaced = _spaced(words)
    return bool(spaced) and re.search(rf"(?<!\w){spaced}(?!\w)", text, re.IGNORECASE) is not None


def _parts(text: str) -> list[str]:
    return [part.strip() for part in segments_of(text)]


def _left_out(part: str) -> str:
    said = _LEFT_OUT.fullmatch(unwrapped(part)[0])
    return said.group(1) if said else ""


def _same_parts(old: str, new: str) -> bool:
    return [part.lower() for part in _parts(old)] == [part.lower() for part in _parts(new)]


def _alike(old: str, new: str) -> float:
    return SequenceMatcher(None, old.lower(), new.lower(), autojunk=False).ratio()


def _each_new_part_with_the_old_one_it_rewrites(old: list[str], new: list[str]) -> dict[int, int]:
    rewrites: dict[int, int] = {}
    for place, part in enumerate(new):
        free = [index for index in range(len(old)) if index not in rewrites.values()]
        likest = max(free, key=lambda index: _alike(old[index], part), default=None)
        if likest is not None and _alike(old[likest], part) >= _ALIKE_ENOUGH_TO_BE_ONE_PART:
            rewrites[place] = likest
    return rewrites


def _rewritten(old: list[str], new: list[str]) -> list[tuple[str, str]]:
    if len(old) == len(new):
        return list(zip(old, new, strict=True))
    rewrites = _each_new_part_with_the_old_one_it_rewrites(old, new)
    added_after: dict[int | None, list[str]] = {}
    follows = None
    for place, part in enumerate(new):
        if place in rewrites:
            follows = rewrites[place]
        else:
            added_after.setdefault(follows, []).append(part)
    by_old = {index: new[place] for place, index in rewrites.items()}
    pairs = [("", part) for part in added_after.get(None, ())]
    for index, part in enumerate(old):
        pairs.append((part, by_old.get(index, "")))
        pairs += [("", added) for added in added_after.get(index, ())]
    return pairs


def _paired(old: list[str], new: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            pairs += [(part, part) for part in old[i1:i2]]
        else:
            pairs += _rewritten(old[i1:i2], new[j1:j2])
    return pairs


def _only_the_words_that_differ(old: str, new: str) -> tuple[str, str]:
    before, after = old.split(), new.split()
    while before and after and before[0] == after[0]:
        before, after = before[1:], after[1:]
    while before and after and before[-1] == after[-1]:
        before, after = before[:-1], after[:-1]
    return (" ".join(before), " ".join(after)) if before and after else (old, new)


def _joined(before: str, words: str, after: str) -> str:
    before, after = before.rstrip(" ,"), after.lstrip(" ,")
    return ", ".join(part for part in (before, words, after) if part)


def _said_done(before: str, after: str, prompt: str) -> str:
    if not before:
        return f"Added {_quoted(after)} to the {prompt}."
    if not after:
        return f"Removed {_quoted(before)} from the {prompt}."
    before, after = _only_the_words_that_differ(before, after)
    return f"Replaced {_quoted(before)} with {_quoted(after)} in the {prompt}."


def _trigger_words_of(lora) -> tuple[str, ...]:
    return () if is_no_lora(lora) else trigger_words(lora)


_AS_WRITTEN = Prompts()
_KEPT_OUT = "kept out: "
_WORDS_OF_AN_EDIT = ("replace", "with", "add", "remove")


class _Applying:
    def __init__(self, pair: tuple[str, str], asked: list[str], settings: list[Setting],
                 prompts: Prompts):
        self.shown_positive, self.negative = pair
        self.positive = self.shown_positive
        self.asked = asked
        self.settings = settings
        self.in_scenes = prompts.in_scenes
        self.take_weights = prompts.take_weights
        self.changes: dict = {}
        self.said: list[str] = []
        self.already_so: list[str] = []
        self.took_out = False

    def _say(self, line: str) -> None:
        self.said += [line]

    def setting(self, change: dict) -> None:
        setting = setting_called(change.get("setting"), self.settings)
        if setting is None:
            self._say(f"There is no setting called {_quoted(change.get('setting'))}.")
            return
        value = setting.taken(change.get("to"))
        if value is None:
            self._say(f"{setting.label} can't be {_quoted(change.get('to'))}.")
        elif value == setting.value:
            self.already_so += [f"{setting.label} is already {setting.shown()}."]
        elif self._answers_him(change, f"{setting.label} {change.get('to')}"):
            self.changes[setting.key] = value
            swapped = self._trigger_words_swapped(setting, value) if setting.folder == "loras" else ""
            self._say(
                f"Set {setting.label} to {setting.shown(value)} (was {setting.shown()}){swapped}.")

    def _trigger_words_swapped(self, setting: Setting, lora) -> str:
        old, new = _trigger_words_of(setting.value), _trigger_words_of(lora)
        before = self.positive
        held = bool(old) and not lacks_trigger_word(before, old, in_scenes=self.in_scenes)
        if new:
            self.positive = with_trigger_words_swapped(before, old, new, in_scenes=self.in_scenes)
        elif old:
            self.positive = without_trigger_word(before, old, in_scenes=self.in_scenes)
        if self.positive == before:
            return ""
        if not new:
            return f", and took its trigger word {old[0]} out of the Positive Prompt"
        if held:
            return f", and swapped its trigger word {old[0]} for {new[0]} in the Positive Prompt"
        return f", and put its trigger word {new[0]} in the Positive Prompt"

    def change(self, change) -> None:
        if not isinstance(change, dict):
            self._say(_UNREADABLE)
        elif "setting" in change:
            self.setting(change)
        else:
            self.prompt(change)

    def prompt(self, change: dict) -> None:
        which = str(change.get("prompt") or "").strip().lower()
        edit = next((edit for edit in self._EDITS if edit in change), None)
        if which not in PROMPTS or edit is None:
            self._say(_UNREADABLE)
        elif self._answers_him(change, " ".join(str(change.get(key) or "") for key in _WORDS_OF_AN_EDIT)):
            self.said += [line for line in self._EDITS[edit](self, which, change) if line]

    def _replace(self, which: str, change: dict) -> list[str]:
        old, new = str(change["replace"]), self._as_these_prompts_take(str(change.get("with") or ""))
        if not new.strip():
            return self._remove(which, {"remove": old})
        found = _found(getattr(self, which), old)
        if found is None:
            return [f"Couldn't find {_quoted(old)} in the {PROMPTS[which]}."]
        there = found.group(0)
        new, left_out = self._without_what_it_leaves_out(which, there, new)
        kept, said = self._what_he_asked_of(there, new, PROMPTS[which])
        if _same_parts(kept, there):
            said = []
        else:
            self.took_out = self.took_out or (which == "positive"
                                              and len(_parts(kept)) < len(_parts(there)))
            text = getattr(self, which)
            setattr(self, which, text[:found.start()] + kept + text[found.end():])
            said = said or [f"Replaced {_quoted(old)} with {_quoted(new)} in the {PROMPTS[which]}."]
        return said + [line for words in left_out for line in self._add("negative", {"add": words})]

    @staticmethod
    def _without_what_it_leaves_out(which: str, old: str, new: str) -> tuple[str, list[str]]:
        if which != "positive":
            return new, []
        there = {part.lower() for part in _parts(old)}
        left_out = {part: _left_out(part) for part in _parts(new) if part.lower() not in there}
        if not any(left_out.values()):
            return new, []
        return (", ".join(part for part in _parts(new) if not left_out.get(part)),
                [words for words in left_out.values() if words])

    def _as_these_prompts_take(self, words: str) -> str:
        if self.take_weights:
            return words
        return ", ".join(unwrapped(part)[0] for part in _parts(words))

    def _answers_him(self, change: dict, changed: str) -> bool:
        return answers_him(change.get("for"), self.asked) or self._names_what_he_asked(changed)

    def _names_what_he_asked(self, words: str) -> bool:
        return bool(_naming(words) & set().union(*(_naming(request) for request in self.asked)))

    def _what_he_asked_of(self, old: str, new: str, prompt: str) -> tuple[str, list[str]]:
        pairs = _paired(_parts(old), _parts(new))
        changed = [pair for pair in pairs if pair[0] != pair[1]]
        named = [pair for pair in changed if self._names_what_he_asked(" ".join(pair))]
        asked_for = named or [pair for pair in changed if pair[1]]
        if len(changed) <= 1 or (not named and len(asked_for) == len(changed)):
            return new, []
        kept, done = [], []
        for before, after in pairs:
            if before == after or (before, after) in asked_for:
                kept.append(after)
                if before != after:
                    done.append(_said_done(before, after, prompt))
            else:
                kept.append(before)
        return ", ".join(part for part in kept if part), done

    def _add(self, which: str, change: dict) -> list[str]:
        words, left_out = self._without_what_it_leaves_out(
            which, "", self._as_these_prompts_take(str(change["add"])))
        if left_out:
            said = [line for unwanted in left_out for line in self._add("negative", {"add": unwanted})]
            return said + (self._add(which, {**change, "add": words}) if words else [])
        text = getattr(self, which)
        kept_out = [_KEPT_OUT + words] if which == "negative" else []
        if _whole(text, words):
            return self._already_there(which, words, kept_out)
        anchor = _found(text, change.get("after") or "")
        at = end_of_the_term(text, anchor.end()) if anchor else len(text)
        setattr(self, which, _joined(text[:at], words, text[at:]))
        return [*kept_out, f"Added {_quoted(words)} to the {PROMPTS[which]}."]

    def _already_there(self, which: str, words: str, kept_out: list[str]) -> list[str]:
        text = getattr(self, which)
        index = index_of(text, words) if which == "negative" and self.take_weights else None
        if index is None:
            self.already_so += [*kept_out, f"The {PROMPTS[which]} already has {_quoted(words)}."]
            return []
        setattr(self, which, reweighted(text, index, WEIGHT_STEP))
        before, after = (segments_of(prompt)[index].strip() for prompt in (text, getattr(self, which)))
        return [*kept_out, f"Replaced {_quoted(before)} with {_quoted(after)} in the {PROMPTS[which]}."]

    def _remove(self, which: str, change: dict) -> list[str]:
        text, asked = getattr(self, which), _parts(str(change["remove"]))
        parts = [part for part in asked if _whole(text, part)]
        if len(parts) > 1:
            parts = [part for part in parts if self._names_what_he_asked(part)]
        if which == "negative" and not parts:
            return [f"Nothing in the Negative Prompt works against {_quoted(part)}." for part in asked]
        self.took_out = self.took_out or (which == "positive" and bool(parts))
        setattr(self, which, without_phrases(text, parts))
        return [f"Removed {_quoted(part)} from the {PROMPTS[which]}." for part in parts]

    _EDITS: ClassVar[dict] = {"replace": _replace, "add": _add, "remove": _remove}

    def _with_what_was_not_found(self, said: list[str]) -> list[str]:
        shown = self.shown_positive.lower()
        lines = []
        for line in said:
            words = line.removeprefix(_KEPT_OUT)
            if words == line:
                lines.append(line)
            elif not self.took_out and not any(word in shown for word in _naming(words)):
                lines.append(f"Couldn't find {_quoted(words)} in the Positive Prompt.")
        return lines

    def outcome(self) -> Outcome:
        said = self._with_what_was_not_found(self.said or self.already_so)
        return Outcome(self.positive, self.negative, self.changes,
                       " ".join(dict.fromkeys(said)) or _NOTHING_CHANGED)


def apply_changes(answer: dict, pair: tuple[str, str], *, asked: list[str],
                  settings: list[Setting], prompts: Prompts = _AS_WRITTEN) -> Outcome:
    applying = _Applying(pair, asked, settings, prompts)
    for change in answer.get("changes") or ():
        applying.change(change)
    return applying.outcome()
