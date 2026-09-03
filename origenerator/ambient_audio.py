"""Which clip each voice of the audio bed plays next.

Qt-free, so the choosing can be unit-tested without a media backend or a clock:
:func:`find_clips` reads the folder and :class:`AmbientRotation` owns every
voice's endless walk through it.  The half that actually makes sound — the
players — is :mod:`origenerator.gui.ambient_audio`.
"""

from __future__ import annotations

import random
from pathlib import Path

from origenerator.media import VIDEO_EXTS


def find_clips(folder) -> list[Path]:
    """Every video under *folder*, at any depth, in a stable order.

    Sorted, so one clip set always shuffles out of the same starting list and a
    test can name what it expects.  A missing folder is simply an empty set:
    the committed example overlay names a path that doesn't exist, and a public
    checkout has to answer that with silence rather than a crash.
    """
    if folder is None:
        return []
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.rglob("*")
        if path.suffix.lower() in VIDEO_EXTS and path.is_file()
    )


class AmbientRotation:
    """Every voice's endless walk through one clip set.

    Each voice gets a shuffled pass of its own over the clips and advances
    through it independently, reshuffling into a fresh pass at the end -- so the
    voices drift apart as soon as two clip lengths differ, and no pass repeats a
    clip before the set is exhausted.  A voice skips any clip another voice
    already has on air, because the same sound arriving twice reads as a glitch
    rather than as two clips.  With fewer clips than voices that is impossible to
    honor, so a voice that walks a whole pass without finding a free clip takes
    the first one it passed.
    """

    def __init__(self, clips, voices: int, *, shuffle=random.shuffle):
        self._clips = list(clips)
        self._shuffle = shuffle
        self._orders: list[list[int]] = []
        self._positions: list[int] = []
        for _ in range(voices):
            order = list(range(len(self._clips)))
            self._shuffle(order)          # each voice its own order, from the start
            self._orders.append(order)
            self._positions.append(-1)    # the first next_clip steps this onto 0
        self._playing: list[Path | None] = [None] * voices

    @property
    def voices(self) -> int:
        return len(self._orders)

    def next_clip(self, voice: int):
        """Advance *voice* to its next clip and return it (``None`` with no clips)."""
        if not self._clips:
            return None
        self._playing[voice] = None  # between clips: free the one it just finished
        fallback = None
        for _ in range(len(self._clips)):
            clip = self._clips[self._step(voice)]
            if fallback is None:
                fallback = clip
            if clip not in self._playing:
                self._playing[voice] = clip
                return clip
        self._playing[voice] = fallback  # fewer clips than voices -- double up
        return fallback

    def _step(self, voice: int) -> int:
        """Move *voice* one place along its pass -- reshuffling into a new pass at
        the end -- and return the clip index it now sits on."""
        order = self._orders[voice]
        position = self._positions[voice] + 1
        if position >= len(order):
            self._shuffle(order)  # a fresh random pass each time round
            position = 0
        self._positions[voice] = position
        return order[position]
