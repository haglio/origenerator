"""Follow an output file the user moved, so the row that recorded it keeps up.

ComfyUI's output folder belongs to the user, not to this app: it gets tidied
between sessions -- a loose file swept into a subfolder, a whole prefix's worth
filed somewhere else -- and every generation that recorded one keeps naming
where it *was*. Two things then go wrong, and only the first of them shows:

* the row loses its file. It draws its thumbnail and nothing else -- no preview,
  no reveal, no enhance, no delete, because each of those resolves through the
  recorded ``subfolder`` (see :func:`origenerator.gallery.output_file_path`);
* the startup import scan finds that file at its new path, does not recognize it
  -- it keys what it has already seen by path under the output dir -- and builds
  a second, lesser row for it: an ``imported`` one, beside the generated row
  that still holds the prompt and the settings.

So this runs *before* that scan, and looks for every recorded file no longer
where its row says, by name, across the output tree:

* **exactly one file of that name** -> rewrite that record's ``subfolder``;
* **none** -> leave it alone. The file was deleted rather than moved, and a row
  still naming where its file was beats one quietly emptied;
* **more than one** -> leave that alone too. ComfyUI counts per filename prefix,
  so two subfolders genuinely can hold a file of one name (the duplicates
  :mod:`origenerator.file_refs` is written around), and nothing here says which
  one is this row's. Broken is visible; repointed at another generation's file
  is not.

A record the recovery bin re-pointed carries an absolute ``path`` of its own and
is skipped: its file is in the trash, which is not the output tree.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from origenerator.gallery.output import parse_file_list

#: The row columns holding a list of output-file records. ``enhance_history``
#: is not among them: it names its files by name alone, so a move cannot
#: invalidate it -- and the levels it describes are resolved through
#: ``output_files``/``original_files`` anyway.
FILE_LISTS = ("output_files", "original_files")


def _by_name(output_dir: Path) -> dict[str, set[str]]:
    """Every file under *output_dir*, as name -> the subfolder(s) holding one.

    A subfolder is spelled the way a record spells it: posix-separated and
    relative to the output dir, with the root itself as ``""``. One walk rather
    than a stat per recorded file, because a healthy library pays this on every
    launch and there are thousands of rows and only one tree.
    """
    index: dict[str, set[str]] = defaultdict(set)
    for path in output_dir.rglob("*"):
        if path.is_file():
            subfolder = path.parent.relative_to(output_dir).as_posix()
            index[path.name].add("" if subfolder == "." else subfolder)
    return index


def _followed(files: list, index: dict[str, set[str]]) -> int:
    """Repoint each record in *files* whose file has moved; how many, in place."""
    moved = 0
    for record in files:
        if not isinstance(record, dict) or record.get("path"):
            continue
        name = record.get("filename") or ""
        holders = index.get(name, set())
        if len(holders) != 1 or (record.get("subfolder") or "") in holders:
            continue
        record["subfolder"] = next(iter(holders))
        moved += 1
    return moved


def relocate_moved_outputs(db, output_dir) -> int:
    """Repoint every recorded output file that moved. Returns how many.

    Best effort by construction: a name that is ambiguous or gone is left as it
    is, so the worst this can do to a library it cannot make sense of is
    nothing.
    """
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return 0
    index = _by_name(output_dir)
    moved = 0
    for row in db.list_generations():
        updates = {}
        for column in FILE_LISTS:
            files = parse_file_list(row.get(column))
            followed = _followed(files, index) if files else 0
            if followed:
                updates[column] = json.dumps(files)
                moved += followed
        if updates:
            db.update_generation(row["prompt_id"], **updates)
    return moved
