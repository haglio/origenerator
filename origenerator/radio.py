"""Origenerator Radio: library videos' sound, dealt out into stations that play on.

Standalone, the radio's switch tunes three stations in at once.  Inside a Fun
Time session each Satellite Funestra is dealt three of its own the moment this
app is ready, which play on out of earshot and are tuned in one at a time while
an image is up (:mod:`funestra.radio`).  Either way the videos come from the one
folder the settings all of Haglio share name, and a station walks its own share
of them round and round.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from funestra.radio import Radio, Tuner, radio_file_for, write_radio

from origenerator.config import RADIO_DIR, RADIO_STATIONS
from origenerator.media import VIDEO_EXTS

logger = logging.getLogger(__name__)

FULL_LEVEL = 100


def find_videos(folder) -> list[Path]:
    """Every video under *folder*, at any depth, in a stable order.

    Sorted, so one video set always shuffles out of the same starting list and a
    test can name what it expects.  A missing folder is simply an empty set:
    the committed example settings name a path that doesn't exist, and a public
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


def deal_stations(videos: Sequence[Path], count: int, *,
                  shuffle: Callable[[list], None] = random.shuffle) -> list[list[Path]]:
    """*count* stations of *videos*, shuffled, with no video on two stations while
    there are enough to go round -- the same sound on two at once reads as a
    glitch rather than as two videos -- and every station given something when
    there are not."""
    if not videos:
        return []
    order = list(videos)
    shuffle(order)
    if len(order) >= count:
        return [order[station::count] for station in range(count)]
    return [order[station % len(order):] + order[:station % len(order)]
            for station in range(count)]


def _open_a_station(videos: Sequence[Path]):
    from funestra.mpv_engine import MpvStation  # noqa: PLC0415

    from origenerator.funestras_engine import offer_the_copy_beside_the_checkouts  # noqa: PLC0415

    offer_the_copy_beside_the_checkouts()
    return MpvStation.opened(videos)


class OrigeneratorRadio:
    """Standalone's Origenerator Radio: its stations, tuned in together while
    its switch is on, dealt afresh each time it is turned on, and held still
    while the room is paused."""

    def __init__(self, *, videos_dir=RADIO_DIR, stations: int = RADIO_STATIONS,
                 open_station: Callable[[Sequence[Path]], object] = _open_a_station,
                 shuffle: Callable[[list], None] = random.shuffle) -> None:
        self._videos_dir = videos_dir
        self._count = stations
        self._shuffle = shuffle
        self._stations = Radio(open_station, together=True)
        self._on = False
        self._frozen = False
        self._held_by: _HeldByASlideshow | None = None

    def start(self) -> None:
        """Tune every station in.  A no-op when already on, and silent -- with
        one line in the log -- when no folder is named or it holds no videos,
        which is what a public checkout has."""
        if self._on:
            return
        videos = find_videos(self._videos_dir)
        if not videos:
            logger.info("Origenerator Radio: no videos under %s, staying silent", self._videos_dir)
            return
        self._on = True
        dealt = deal_stations(videos, self._count, shuffle=self._shuffle)
        self._stations.take(dealt)
        self._tune()
        logger.info("Origenerator Radio: %d stations over %d videos", len(dealt), len(videos))

    def stop(self) -> None:
        self._on = False
        self._stations.close()

    def set_frozen(self, frozen: bool) -> None:
        self._frozen = frozen
        self._tune()

    def held_by_a_slideshow(self) -> Tuner:
        """The radio as the Standalone Slideshow's Funestra plays it, heard
        while its image is up at its volume, until that Funestra lets it go."""
        self._held_by = _HeldByASlideshow(self)
        return self._held_by

    def _heard_through(self, holder: _HeldByASlideshow, *, image: bool | None,
                       level: int | None, paused: bool) -> None:
        if holder is self._held_by:
            self._stations.tick(image=image, level=level, paused=paused or self._frozen)

    def _let_go_by(self, holder: _HeldByASlideshow) -> None:
        if holder is self._held_by:
            self._held_by = None
            self._tune()

    def _tune(self) -> None:
        if self._held_by is None:
            self._stations.tick(image=True, level=FULL_LEVEL, paused=self._frozen)


class _HeldByASlideshow:
    def __init__(self, radio: OrigeneratorRadio) -> None:
        self._radio = radio

    def tick(self, *, image: bool | None, level: int | None, paused: bool) -> None:
        self._radio._heard_through(self, image=image, level=level, paused=paused)

    def close(self) -> None:
        self._radio._let_go_by(self)


def deal_to_the_funestras(playlists: Mapping[str, Path], *, videos_dir=RADIO_DIR,
                          stations: int = RADIO_STATIONS,
                          shuffle: Callable[[list], None] = random.shuffle) -> list[Path]:
    """Deal each of a session's Funestras its own stations, written beside the
    playlist it plays (*playlists* by side), and say which files were written.
    The stations of two Funestras share no video while there are enough videos to
    go round, so the two never sound alike at once."""
    if not playlists:
        return []
    dealt = deal_stations(find_videos(videos_dir), stations * len(playlists), shuffle=shuffle)
    written = []
    for index, playlist in enumerate(playlists.values()):
        path = radio_file_for(playlist)
        write_radio(path, dealt[index * stations:(index + 1) * stations])
        written.append(path)
    return written
