"""Which version of the picture on screen is showing, and how to step it.

An enhanced image is several files: the original, and each level made from it.
Shift+Left/Right in a show moves within that one image rather than along the
set, because a version is not a neighbor — you compare two versions of a picture
by texture, which is exactly what cannot be told apart from memory or from a
thumbnail.

Three fields on :class:`~origenerator.gui.slideshow_view.SlideshowView` carried
this — the map of versions, which picture is being stepped, and where in its
versions the show is — read and written from five of its methods and shared with
the thirty other fields around them. They are one object here, with no Qt in it.
"""

from __future__ import annotations


class LevelStepper:
    """The versions of each image, and the place within one of them."""

    def __init__(self) -> None:
        self._by_path: dict[str, list[tuple]] = {}
        # The picture being stepped, once stepping has started. Kept separately
        # from what the caller offers, because the file on screen stops being
        # the one the set lists the image under the moment a level is showing.
        self._base: str | None = None
        self._index = 0

    def arm(self, levels_by_path) -> None:
        """Take the versions of every image that has more than itself.

        ``levels_by_path`` maps the file the set shows an image under to that
        image's versions, newest first, as ``(path, media_type, label)``. The
        gallery rebuilds this on every poll and spells its paths either way, so
        the keys are normalized and the lists copied — nothing here goes on
        pointing at what the caller handed over.
        """
        self._by_path = {str(key): list(versions)
                         for key, versions in levels_by_path.items()}

    def restart(self) -> None:
        """Back to the top version, for a new picture — or for one whose
        versions have just gone a level deeper."""
        self._base = None
        self._index = 0

    def step(self, delta: int, *, base: str):
        """Move ``delta`` versions within the picture on screen and answer the
        one to show, or ``None`` when there is nothing to step.

        Nothing to step is an image with one version and a video with none: the
        caller leaves the set alone rather than paging it, since the shift was
        the whole point of the press.
        """
        base = self._base or base
        versions = self._by_path.get(base) or []
        if len(versions) <= 1:
            return None
        self._base = base
        self._index = (self._index + delta) % len(versions)
        return versions[self._index]

    def levels(self, *, base: str) -> list[tuple]:
        """The versions of the picture on screen — what the corner counts off."""
        return self._by_path.get(self._base or base) or []

    @property
    def index(self) -> int:
        """Which of those versions is showing, from the top. Nought is both the
        newest version and an image nobody has stepped, which is why a resumed
        show can take it as the number of steps down to where it was."""
        return self._index
