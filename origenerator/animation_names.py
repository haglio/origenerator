from __future__ import annotations

from typing import NamedTuple

from origenerator.action_labels import Labels, labels_of
from origenerator.action_vocabulary import JOINER, Vocabulary, vocabulary
from origenerator.media import MediaType


class Animation(NamedTuple):
    action: str
    checked: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return JOINER.join((self.action, *self.checked))


def _video_words(words: Vocabulary | None) -> Vocabulary:
    return words if words is not None else vocabulary(MediaType.VIDEO)


def named(name: str, words: Vocabulary | None = None) -> Animation:
    boxes = _video_words(words).checkboxes
    parts = name.split(JOINER)
    checked: list[str] = []
    while len(parts) > 1 and parts[-1] in boxes:
        checked.insert(0, parts.pop())
    return Animation(JOINER.join(parts), tuple(checked))


def labels_for(name: str, words: Vocabulary | None = None) -> Labels:
    words = _video_words(words)
    animation = named(name, words)
    return Labels(words.buttons.get(animation.action, ()), animation.checked)


def animation_of(video: dict, words: Vocabulary | None = None) -> str:
    words = _video_words(words)
    labels = labels_of(video, MediaType.VIDEO)
    action = words.button_made_of(labels.actions)
    if not action:
        return ""
    return Animation(action, tuple(box for box in words.checkboxes if box in labels.checked)).name


def image_button_of(image: dict | None, words: Vocabulary | None = None) -> str:
    if image is None:
        return ""
    words = words if words is not None else vocabulary(MediaType.IMAGE)
    return words.button_made_of(labels_of(image, MediaType.IMAGE).actions)
