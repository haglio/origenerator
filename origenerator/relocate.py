"""Follow an output file the user moved, so the row that recorded it keeps up.

The library's folders belong to the user, not to this app: they get tidied
between sessions -- a loose file swept into a subfolder, a whole prefix's worth
filed somewhere else -- and every generation that recorded one keeps naming
where it *was*. Two things then go wrong, and only the first of them shows:

* the row loses its file. It draws its thumbnail and nothing else -- no preview,
  no reveal, no enhance, no delete, because each of those resolves through the
  recorded ``subfolder`` (see :func:`origenerator.gallery.output_file_path`);
* the startup import scan finds that file at its new path, does not recognize it
  -- it keys what it has already seen by the folder its record names -- and builds
  a second, lesser row for it: an ``imported`` one, beside the generated row
  that still holds the prompt and the settings.

So this runs *before* that scan, and looks for every recorded file no longer
where its row says, by name, across every place outputs are kept:

* **exactly one file of that name** -> rewrite that record's ``subfolder``;
* **none** -> leave it alone. The file was deleted rather than moved, and a row
  still naming where its file was beats one quietly emptied;
* **more than one** -> leave that alone too. ComfyUI counts per filename prefix,
  so two subfolders genuinely can hold a file of one name (the duplicates
  :mod:`origenerator.file_refs` is written around), and nothing here says which
  one is this row's. Broken is visible; repointed at another generation's file
  is not.

A record with a place of its own -- a file the bin moved to the trash, a starting
frame, a video in the library -- is skipped: none of them is in the output tree.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from origenerator.funscript import funscript_path_for
from origenerator.gallery.output import parse_file_list, place_of_its_own
from origenerator.output_places import OutputPlaces

logger = logging.getLogger(__name__)

#: The row columns holding a list of output-file records. ``enhance_history``
#: is not among them: it names its files by name alone, so a move cannot
#: invalidate it -- and the levels it describes are resolved through
#: ``output_files``/``original_files`` anyway.
FILE_LISTS = ("output_files", "original_files")


def _by_name(places: OutputPlaces) -> dict[str, set[str]]:
    """Every file kept in *places*, as name -> the subfolder(s) holding one.

    One walk rather than a stat per recorded file, because a healthy library
    pays this on every launch and there are thousands of rows.
    """
    index: dict[str, set[str]] = defaultdict(set)
    for path, subfolder in places.files():
        index[path.name].add(subfolder)
    return index


def _followed(files: list, index: dict[str, set[str]], places: OutputPlaces) -> int:
    """Repoint each record in *files* whose file has moved; how many, in place."""
    moved = 0
    for record in files:
        if not isinstance(record, dict) or place_of_its_own(record):
            continue
        name = record.get("filename") or ""
        holders = index.get(name, set())
        was = record.get("subfolder") or ""
        if len(holders) != 1 or was in holders:
            continue
        record["subfolder"] = next(iter(holders))
        _move_script(places.folder(was) / name, places.folder(record["subfolder"]) / name,
                     places)
        moved += 1
    return moved


def _move_script(was: Path, now: Path, places: OutputPlaces) -> None:
    script = funscript_path_for(was, places=places)
    destination = funscript_path_for(now, places=places)
    if script.is_file() and not destination.exists():
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            script.rename(destination)
        except OSError as e:
            logger.warning("A moved video's script stayed at %s: %s", script, e)


def relocate_moved_outputs(db, places: OutputPlaces) -> int:
    """Repoint every recorded output file that moved. Returns how many.

    Best effort by construction: a name that is ambiguous or gone is left as it
    is, so the worst this can do to a library it cannot make sense of is
    nothing.
    """
    index = _by_name(places)
    moved = 0
    for row in db.list_generations():
        updates = {}
        for column in FILE_LISTS:
            files = parse_file_list(row.get(column))
            followed = _followed(files, index, places) if files else 0
            if followed:
                updates[column] = json.dumps(files)
                moved += followed
        if updates:
            db.update_generation(row["prompt_id"], **updates)
    return moved
