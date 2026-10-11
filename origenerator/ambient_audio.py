"""Which clip each voice of the audio bed plays next.

Qt-free, so the choosing can be unit-tested without a media backend or a clock:
:func:`find_clips` reads the folder, :class:`AmbientFolder` follows it when it is
renamed, and :class:`AmbientRotation` owns every voice's walk through it.  The
players that make the sound are :mod:`origenerator.ambient_audio_players`.
"""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePath

from app_support.file_channel import write_whole

from origenerator.media import VIDEO_EXTS

logger = logging.getLogger(__name__)


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


class AmbientFolder:
    def __init__(self, folder: Path | None, *, memory: Path, within: Path,
                 repoint: Callable[[Path], bool]):
        self._folder = folder
        self._memory = memory
        self._within = within
        self._repoint = repoint

    @property
    def path(self) -> Path | None:
        return self._folder

    def clips(self) -> list[Path]:
        if self._folder is None:
            return []
        if not self._folder.is_dir():
            moved_to = self._where_it_went()
            if moved_to is None or not self._repoint(moved_to):
                return []
            logger.info("Ambient audio: %s was renamed %s; the overlay names it now",
                        self._folder, moved_to)
            self._folder = moved_to
        clips = find_clips(self._folder)
        self._remember(clips)
        return clips

    def _remember(self, clips: list[Path]) -> None:
        held = {"folder": str(self._folder),
                "clips": [str(clip.relative_to(self._folder)) for clip in clips]}
        if _read(self._memory) != held:
            self._memory.parent.mkdir(parents=True, exist_ok=True)
            write_whole(self._memory, json.dumps(held, indent=1) + "\n")

    def _where_it_went(self) -> Path | None:
        remembered = _read(self._memory)
        if Path(remembered.get("folder") or ".") != self._folder:
            return None
        held = [PurePath(clip) for clip in remembered.get("clips") or ()]
        searched = self._folder.parent
        while held and searched.is_relative_to(self._within) and searched != self._within:
            if searched.is_dir() and (home := _home_of(held, searched)) is not None:
                return home
            searched = searched.parent
        return None


def _home_of(held: list[PurePath], searched: Path) -> Path | None:
    by_name: dict[str, list[Path]] = {}
    for clip in find_clips(searched):
        by_name.setdefault(clip.name.casefold(), []).append(clip)
    homes: Counter[Path] = Counter()
    for clip in held:
        depth = len(clip.parts)
        for found in by_name.get(clip.name.casefold(), ()):
            if _folded(found.parts[-depth:]) == _folded(clip.parts):
                homes[Path(*found.parts[:-depth])] += 1
    if not homes:
        return None
    home, clips = homes.most_common(1)[0]
    return home if 2 * clips > len(held) else None


def _folded(parts: tuple[str, ...]) -> list[str]:
    return [part.casefold() for part in parts]


def _read(memory: Path) -> dict:
    try:
        held = json.loads(memory.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


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
