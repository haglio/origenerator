"""Which version of the picture on screen is showing, and how to step it.

An enhanced image is several files: the original, and each level made from it.
Shift+Left/Right in a slideshow moves within that one image rather than along the
set, because a version is not a neighbor — you compare two versions of a picture
by texture, which is exactly what cannot be told apart from memory, from a
thumbnail or over a picture that is moving.
"""

from __future__ import annotations

from typing import NamedTuple


class Version(NamedTuple):
    path: object
    media_type: str
    label: str = ""
    points_of_interest: tuple = ()


class LevelStepper:
    """The versions of each image, and the place within one of them."""

    def __init__(self) -> None:
        self._by_path: dict[str, list[Version]] = {}
        # The picture being stepped, once stepping has started. Kept separately
        # from what the caller offers, because the file on screen stops being
        # the one the set lists the image under the moment a level is showing.
        self._base: str | None = None
        self._index = 0
        self._stepping = False

    def arm(self, levels_by_path) -> bool:
        """Take the versions of every item that has more than itself.

        ``levels_by_path`` maps the file the set shows an item under to that
        item's versions, newest first, as ``(path, media_type, label, places)``.
        The gallery rebuilds this on every poll and spells its paths either way,
        so the keys are normalized and the lists copied — nothing here goes on
        pointing at what the caller handed over.
        """
        before = self._places()
        self._by_path = {}
        self._take(levels_by_path)
        return self._places() != before

    def add(self, levels_by_path) -> bool:
        before = self._places()
        self._take(levels_by_path)
        return self._places() != before

    def _take(self, levels_by_path) -> None:
        self._by_path.update({str(key): [Version(*version) for version in versions]
                              for key, versions in levels_by_path.items()})

    def points_of_interest(self, path) -> tuple:
        versions = self._by_path.get(str(path))
        return versions[0].points_of_interest if versions else ()

    def _places(self) -> dict[str, tuple]:
        return {key: versions[0].points_of_interest
                for key, versions in self._by_path.items()
                if versions and versions[0].points_of_interest}

    def restart(self) -> None:
        """Back to the top version, for a new picture."""
        self.back_to_the_top()
        self._stepping = False

    def back_to_the_top(self) -> None:
        """For a picture whose versions have just gone a level deeper."""
        self._base = None
        self._index = 0

    def step(self, delta: int, *, base: str):
        """Move ``delta`` versions within the picture on screen and answer the
        one to show, or ``None`` when there is nothing to step.

        Nothing to step is an item with one version: the caller leaves the set
        alone rather than paging it, since the shift was the whole point of the
        press.
        """
        base = self._base or base
        versions = self._by_path.get(base) or []
        if len(versions) <= 1:
            return None
        self._base = base
        self._stepping = True
        self._index = (self._index + delta) % len(versions)
        return versions[self._index]

    def levels(self, *, base: str) -> list[Version]:
        """The versions of the picture on screen — what the HUD names one of."""
        return self._by_path.get(self._base or base) or []

    @property
    def stepping(self) -> bool:
        return self._stepping

    @property
    def index(self) -> int:
        """Which of those versions is showing, from the top. Nought is both the
        newest version and an image nobody has stepped, which is why a resumed
        slideshow can take it as the number of steps down to where it was."""
        return self._index
