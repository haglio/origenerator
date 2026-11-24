from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from funestra.hud_title import LATEST_LABEL

from origenerator.gallery.tree import ALL_KEY, favorite_generations

LATEST_KEY = "__recents__"
FAVORITES_KEY = "__starred__"
FAVORITES_LABEL = "Favorites"
ENHANCED_KEY = "__enhanced__"
ENHANCED_LABEL = "Enhanced"
POPULATING_KEY = "__populating__"
POPULATING_LABEL = "Populating"
EXPERIMENTS_KEY = "__experiments__"
EXPERIMENTS_LABEL = "Experiments"
TRASH_KEY = "__trash__"
TRASH_LABEL = "Trash"
_IN_FOLDER = "@"


@dataclass(frozen=True)
class Glyph:
    name: str
    color: str | None = None


@dataclass(frozen=True)
class Voice:
    names: tuple[str, ...]
    said_bare: bool = True
    heard_by_a_surface: bool = True
    answered_when_hosted: bool = True


@dataclass(frozen=True)
class Collection:
    key: str
    label: str
    tooltip: str
    glyph: Glyph
    rows: Callable[[object], list[dict]] | None = None
    picked_fresh: Callable[[object, list[dict]], list[dict]] | None = None
    shown_in: Callable[[object], bool] = lambda shape: True
    marked: bool = False
    counted: bool = True
    gathers_folders: bool = False
    empty: str = ""
    voice: Voice | None = None
    slideshow_filter: str | None = None
    of_what_was_generated: bool = False
    newest_first: bool = False


ALL_COLLECTIONS: tuple[Collection, ...] = (
    Collection(
        LATEST_KEY, LATEST_LABEL, "Recently generated", Glyph("latest"),
        rows=lambda library: library.recent_rows,
        shown_in=lambda shape: shape.show_latest, counted=False,
        voice=Voice(("recents", "recent")), newest_first=True),
    Collection(
        FAVORITES_KEY, FAVORITES_LABEL,
        "Your favorite folders and items — drop a folder here to add it",
        Glyph("star", "GREEN"), picked_fresh=lambda _library, rows: favorite_generations(rows),
        shown_in=lambda shape: bool(shape.tree_model), marked=True, gathers_folders=True,
        empty=("No bookmarks yet.\n\nStar an image or video from its right-click menu, "
               "or favorite a folder from the list, to collect them here."),
        voice=Voice(("favorites",), said_bare=False), slideshow_filter="favorites"),
    Collection(
        ENHANCED_KEY, ENHANCED_LABEL, "Your enhanced items",
        Glyph("plus", "YELLOW"),
        rows=lambda library: library.enhanced_rows,
        shown_in=lambda shape: bool(shape.tree_model), marked=True,
        empty=("No enhanced items yet.\n\nEnhance an image from its "
               "right-click menu or the plus in its corner to see it here. A video shows here "
               "once Evolver has enhanced it."),
        slideshow_filter="enhanced"),
    Collection(
        POPULATING_KEY, POPULATING_LABEL,
        "What Populate has made and is making, in every folder it is running in",
        Glyph("bolt"), picked_fresh=lambda library, rows: library.populating_rows(rows),
        shown_in=lambda shape: bool(shape.tree_model), counted=False,
        empty=("Nothing is populating.\n\nTurn on Populate in a leaf folder to see what it "
               "makes here."),
        of_what_was_generated=True, newest_first=True),
    Collection(
        EXPERIMENTS_KEY, EXPERIMENTS_LABEL, "Background experiments awaiting your review",
        Glyph("flask"), rows=lambda library: library.experiment_rows,
        voice=Voice(("experiments", "experiment"), answered_when_hosted=False),
        of_what_was_generated=True),
    Collection(
        TRASH_KEY, TRASH_LABEL,
        "Deleted items — after a day only their thumbnails are kept, "
        "and restoring one makes it again",
        Glyph("trash", "RED"), rows=lambda library: library.held_rows, marked=True),
)



def all_collections() -> tuple[Collection, ...]:
    return ALL_COLLECTIONS


def collection_keys() -> tuple[str, ...]:
    return tuple(each.key for each in all_collections())


def collection(key: str) -> Collection:
    return next(each for each in all_collections() if each.key == key)


def spoken_collections() -> tuple[Collection, ...]:
    return tuple(each for each in all_collections() if each.voice is not None)


class FolderCollection(NamedTuple):
    which: str
    folder: str

    @property
    def key(self) -> str:
        return self.which if self.folder == ALL_KEY else f"{self.which}{_IN_FOLDER}{self.folder}"


def folder_collection(key: str | None) -> FolderCollection | None:
    which, _, folder = (key or "").partition(_IN_FOLDER)
    return FolderCollection(which, folder or ALL_KEY) if which in collection_keys() else None
