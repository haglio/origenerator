"""The read-only facts about one generation that belong with neither the params
nor the form: the output file and when the run happened.

The gallery's info-pane tab is an editable :class:`GenerateConfigPanel`. It renders
the prompts and every parameter as fields (the ones the workflow lays out are
editable; the rest — an import's extras, hidden passthrough like vae or clip — show
as read-only rows in the same form). So the only things left for this block are the
output file and its timestamp, shown as a compact ``Basic`` section above the form.

Kept Qt-free so the section/item model is unit-testable directly;
``gui/metadata_block.py`` does the rendering.
"""

from dataclasses import dataclass

from origenerator import gallery


@dataclass
class MetaItem:
    """One line in a section, rendered as ``label: value``.

    ``copy`` drives a copy-to-clipboard button: ``None`` shows no button, a
    non-empty string is what the button copies.
    """

    label: str
    value: str
    copy: str | None = None


@dataclass
class MetaSection:
    title: str
    items: list[MetaItem]


def _output_path(file: dict) -> str:
    subfolder = file.get("subfolder") or ""
    filename = file.get("filename") or ""
    return f"{subfolder}/{filename}" if subfolder else filename


def _output_items(row: dict) -> list[MetaItem]:
    """One labeled item per output file; each copies just its filename, dropping
    the image/ or video/ subfolder the displayed path carries."""
    return [
        MetaItem("File", _output_path(f), copy=f["filename"])
        for f in gallery.row_output_files(row)
        if f.get("filename")
    ]


def _basic(row: dict) -> MetaSection:
    """The at-a-glance facts kept at the top: what this run produced, and when."""
    items = [*_output_items(row), MetaItem("Created", str(row.get("created_at", "")))]
    return MetaSection("Basic", items)


def build_sections(row: dict) -> list[MetaSection]:
    return [_basic(row)]
