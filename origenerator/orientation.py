"""Which side of the folder list a generation sits on, and the keys that say so.

A hosting Fun Time session shows portrait media on the portrait region and
landscape on the landscape one, so the folder list is drawn a side per shape:
the whole table of contents on each, built from that shape's rows alone, so
whatever you stand on has exactly one region to play on, read off the key
rather than measured back out of the items. On its own the app can draw it once
over both shapes instead, for a slideshow that mixes them
(:mod:`origenerator.gallery.sides` says what each side holds).

A row's tree key is its folder's own key with its side appended
(:func:`oriented_key`), and :func:`split_key` takes it apart again. The
*folder's* key is untouched by this: a star, a custom name and a place in a
folder the user composed hang off the plain key, being the folder's rather than
the side's.

The shape is the folder's wherever its settings state a size: every item of
that folder sits on that side, a running one is placed before it has a
file, and an item that disagrees with its folder shows up beside it
rather than hiding on the other side. A folder whose settings state no size --
a video's, whose workflow derives the size in-graph from its start frame -- goes
by the item's own shape, read off its thumbnail (a cheap header read that
keeps the aspect) or its file, and by its start frame while it has neither. An
item that answers none of them files under Landscape, the roomier region --
the same default the region routing uses for an unmeasurable set.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from PIL import Image
from shared_ui.orientation import orientation_of_size

from origenerator import gallery
from origenerator.config import OUTPUT_PLACES
from origenerator.gallery.sides import LANDSCAPE, SIDES, on_side
from origenerator.gallery.signatures import READINGS_KEPT, canonical_settings
from origenerator.media import MediaType
from origenerator.workflows.derived_size import resolve_input_image_path

_SEPARATOR = "::"
_INSIDE = ">"

# How many measured shapes are kept at once. Comfortably above one library's
# worth, because a rebuild measures every row: a cap under that would evict the
# rows measured at the top of a pass before the pass reached the end, and
# every poll would go back to opening a thumbnail per row — the cost the cache
# exists to avoid. Above that ceiling it is only memory, and this many short
# paths is a few megabytes.
_MEASURED_LIMIT = 20_000

# Measured shapes, by the file that answered. A rebuild re-reads every row, and
# opening a thumbnail per row per poll is a cost the tree now pays for both
# sides at once; the file a shape was read from never changes its shape, so the
# answer is kept against its path. Only successful reads are kept — a row whose
# file has not landed yet has to be asked again once it has.
#
# Ordered so it can be bounded: nothing here ever becomes wrong, so the only
# reason to drop an entry is room, and the one to drop is the one longest
# unasked-for — a generation deleted an hour ago, rather than a row the open
# folder redraws every poll.
_measured: OrderedDict[str, str] = OrderedDict()


def oriented_key(base_key: str, side: str, inside: tuple[str, ...] = ()) -> str:
    """The tree key of *base_key*'s row on *side*: in its own place, or drawn
    again inside the folder of your own that *inside* leads down from."""
    return f"{base_key}{_SEPARATOR}{side}" + "".join(_INSIDE + key for key in inside)


def key_holds(outer: str, inner: str) -> bool:
    """Whether *outer* is *inner* or a folder it sits in, on the same side."""
    outer_base, outer_side = split_key(outer)
    inner_base, inner_side = split_key(inner)
    if outer_side != inner_side or not outer_base or not inner_base:
        return False
    return inner_base == outer_base or inner_base.startswith(outer_base + "/")


def split_key(key: str | None) -> tuple[str | None, str | None]:
    """``(base_key, side)`` — side ``None`` for a plain key."""
    if not key:
        return key, None
    base, _, placed = key.partition(_SEPARATOR)
    side = placed.partition(_INSIDE)[0]
    return (base, side) if side in SIDES else (key, None)


def base_of(key: str | None) -> str | None:
    """The folder a tree key names, with the side stripped off — what a star, a
    name and a place in a custom folder are all stored under."""
    return split_key(key)[0]


def side_of(key: str | None) -> str | None:
    """Which side a tree key is on (``None`` for a key naming no side)."""
    return split_key(key)[1]


def row_orientation(row: dict) -> str:
    """Which region *row*'s media belongs on: its folder's side (see the
    module's account of the order)."""
    asked = _asked_shape(row.get("workflow_name"), row.get("params_json"))
    if asked is not None:
        return asked
    return (_measure_any(_own_files(row))
            or _measure_any(_frame_candidate(gallery.parse_params(row.get("params_json"))))
            or LANDSCAPE)


@lru_cache(maxsize=READINGS_KEPT)
def _asked_shape(workflow_name: str | None, params_json: str | None) -> str | None:
    return requested_orientation(canonical_settings(workflow_name, gallery.parse_params(params_json)))


def _measure_any(candidates) -> str | None:
    """The shape of the first of *candidates* that can be read, or ``None``."""
    for candidate in candidates:
        path = str(candidate)
        remembered = _measured.get(path)
        if remembered is not None:
            _measured.move_to_end(path)  # asked for, so not the next to go
            return remembered
        try:
            with Image.open(candidate) as image:
                measured = orientation_of_size(*image.size)
        except (OSError, ValueError):
            continue
        _remember(path, measured)
        return measured
    return None


def _remember(path: str, measured: str) -> None:
    """Keep *path*'s shape, making room for it by dropping the entry nothing
    has asked for in longest."""
    _measured[path] = measured
    if len(_measured) > _MEASURED_LIMIT:
        _measured.popitem(last=False)


def _own_files(row: dict) -> Iterator[Path]:
    thumb = row.get("thumbnail_path")
    if thumb:
        yield Path(thumb)
    resolved = gallery.resolve_preview(row, OUTPUT_PLACES)
    if resolved is not None and resolved[1] == MediaType.IMAGE:
        yield Path(resolved[0])


def _frame_candidate(params: dict) -> list[Path]:
    """The start frame a run is built from, as the one file that says which way
    its output will come: the video workflows keep the frame's aspect at a fixed
    pixel budget (:mod:`origenerator.workflows.derived_size`), so a portrait
    frame makes a portrait video. Empty for a run made from nothing."""
    frame = resolve_input_image_path(params.get("input_image"))
    return [frame] if frame is not None else []


def requested_orientation(params: dict) -> str | None:
    """The shape a generation's *params* ask it to come out — ``None`` when they
    don't say."""
    try:
        width, height = int(params["width"]), int(params["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return orientation_of_size(width, height)


def filter_rows(rows, side: str | None) -> list[dict]:
    return on_side(rows, side, row_orientation)
