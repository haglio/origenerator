"""The read-only facts about one generation that belong with neither the params
nor the form: the output file and when the run happened.

The gallery's info-pane tab is an editable :class:`GenerateConfigPanel`. It renders
the prompts and every parameter as fields (the ones the workflow lays out are
editable; the rest — an import's extras, hidden passthrough like vae or clip — show
as read-only rows in the same form). So the only things left for this block are the
output file and its timestamp, shown as a compact ``Basic`` section above the form.

An image's files are not one of those things any more: each is a version of the
image, made by its own enhancement at its own settings and at its own moment, so
each is listed down in the version strip beside the level that produced it —
where the settings that made it already are — rather than pooled in one block at
the top under a label naming a level you then have to go and find. What stays
here is what no level claims: a video's file, and the siblings of a batch (which
are separate results of one run, not versions of each other).

Kept Qt-free so the section/item model is unit-testable directly;
``gui/metadata_block.py`` does the rendering.
"""

from dataclasses import dataclass
from datetime import datetime

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR


@dataclass
class MetaItem:
    """One line in a section, rendered as ``label: value``.

    ``copy`` drives a copy-to-clipboard button: ``None`` shows no button, a
    non-empty string is what the button copies. ``reveal`` drives a
    Show-in-Explorer button: ``None`` shows no button, otherwise the absolute
    path on disk the button reveals (selected in the OS file manager).
    """

    label: str
    value: str
    copy: str | None = None
    reveal: str | None = None


@dataclass
class MetaSection:
    title: str
    items: list[MetaItem]


def _output_path(file: dict) -> str:
    subfolder = file.get("subfolder") or ""
    filename = file.get("filename") or ""
    return f"{subfolder}/{filename}" if subfolder else filename


def _held_prefix(held_days: int | None) -> str:
    """How long this file's generation has been in the trash, for the front of
    its File line — nothing at all for an item that hasn't been deleted.

    It leads the line because the line is where you go to find out what a file
    *is*, and for a deleted one "how long until it's gone" is part of that. The
    Trash shelf's tiles carry the other half of the arithmetic (how many days it
    has left); this says how long it has been sitting there.
    """
    if held_days is None:
        return ""
    if held_days <= 0:
        return "(deleted today) "
    return f"({held_days} day{'s' if held_days != 1 else ''} in trash) "


def file_item(file: dict, label: str = "File", *,
              held_days: int | None = None) -> MetaItem:
    """One output file as a row: its path, a copy of just its filename (dropping
    the image/ or video/ subfolder the displayed path carries), and a reveal of
    its absolute location — under ComfyUI's output folder, or wherever the
    recovery bin has since moved it.

    ``held_days`` is set only for a deleted item, and puts how long it has been
    in the trash in front of the path.

    Shared with the version strip, which puts this exact row beside the level it
    belongs to — the same file information, wherever the file is listed."""
    filename = file.get("filename") or ""
    full = gallery.output_file_path(file, COMFYUI_OUTPUT_DIR)
    return MetaItem(label, _held_prefix(held_days) + _output_path(file),
                    copy=filename, reveal=str(full))


def created_item(file: dict, fallback: str = "") -> MetaItem:
    """When one output file was written, from the file itself.

    Per file rather than per row, because an image's versions were made at
    different moments — the enhancement you queued this evening sits beside a
    render from last week, and one ``created_at`` on the row can only be honest
    about one of them. Falls back to the row's own timestamp when the file is
    gone from disk."""
    full = gallery.output_file_path(file, COMFYUI_OUTPUT_DIR)
    try:
        stamp = datetime.fromtimestamp(full.stat().st_mtime)
    except OSError:
        return MetaItem("Created", str(fallback))
    return MetaItem("Created", stamp.strftime("%Y-%m-%d %H:%M:%S"))


def _basic(row: dict) -> MetaSection | None:
    """The at-a-glance facts kept at the top: what this run produced, and when.

    ``None`` — no block at all — once every file the row holds is listed as a
    version of the image, which is the ordinary case for an image and leaves
    nothing here to repeat."""
    listed = {level.file.get("filename")
              for level in gallery.displayed_levels(row)}
    files = [f for f in gallery.row_output_files(row)
             if f.get("filename") and f.get("filename") not in listed]
    if not files:
        return None
    held = row.get("days_in_trash")
    items = [file_item(f, held_days=held) for f in files]
    items.append(MetaItem("Created", str(row.get("created_at", ""))))
    return MetaSection("Basic", items)


def build_sections(row: dict) -> list[MetaSection]:
    basic = _basic(row)
    return [basic] if basic is not None else []
