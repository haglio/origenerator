"""Present one generation's metadata as titled sections of items.

The gallery's detail sidebar renders these as formatted blocks rather than one
undifferentiated text dump. Kept Qt-free so the section/item model is unit-
testable directly; ``gui/metadata_panel.py`` does the rendering.
"""

from dataclasses import dataclass

from origenerator import gallery, timing

_PROMPT_KEYS = ("positive_prompt", "negative_prompt")


@dataclass
class MetaItem:
    """One line in a section. A blank ``label`` renders as a bare value (prompt
    text, a filename); a set ``label`` renders as ``label: value``."""

    label: str
    value: str


@dataclass
class MetaSection:
    title: str
    items: list[MetaItem]


def _details(row: dict) -> MetaSection:
    items = [
        MetaItem("Status", str(row.get("status", ""))),
        MetaItem("Source", str(row.get("source", "generated"))),
        MetaItem("Seed", str(row.get("seed", "N/A"))),
        MetaItem("Created", str(row.get("created_at", ""))),
    ]
    duration = row.get("duration_seconds")
    if duration is not None:
        items.append(MetaItem("Duration", timing.format_duration(duration)))
    return MetaSection("Details", items)


def _prompt(title: str, text: str | None) -> MetaSection:
    return MetaSection(title, [MetaItem("", text or "(empty)")])


def _parameters(row: dict) -> MetaSection | None:
    params = gallery.parse_params(row.get("params_json"))
    items = [
        MetaItem(key, str(value))
        for key, value in params.items()
        if key not in _PROMPT_KEYS
    ]
    return MetaSection("Parameters", items) if items else None


def _output_path(file: dict) -> str:
    subfolder = file.get("subfolder") or ""
    filename = file.get("filename") or ""
    return f"{subfolder}/{filename}" if subfolder else filename


def _output_files(row: dict) -> MetaSection | None:
    items = [
        MetaItem("", _output_path(f))
        for f in gallery.row_output_files(row)
        if f.get("filename")
    ]
    return MetaSection("Output Files", items) if items else None


def build_sections(row: dict) -> list[MetaSection]:
    sections = [
        _details(row),
        _prompt("Positive Prompt", row.get("positive_prompt")),
        _prompt("Negative Prompt", row.get("negative_prompt")),
        _parameters(row),
        _output_files(row),
    ]
    return [s for s in sections if s is not None]
