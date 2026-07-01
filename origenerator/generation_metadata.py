"""Present one generation's metadata as titled sections of items.

The gallery's detail sidebar renders these as formatted blocks rather than one
undifferentiated text dump. Kept Qt-free so the section/item model is unit-
testable directly; ``gui/metadata_panel.py`` does the rendering.

Sections run most-wanted first: ``Basic`` (the output file and date) leads so
those never need scrolling to; ``Details`` (status, source) trails at the end.
"""

from dataclasses import dataclass

from origenerator import gallery

_PROMPT_KEYS = ("positive_prompt", "negative_prompt")
# Parameter keys that hold a reproducibility seed, which earns a copy button.
_SEED_KEYS = ("seed", "noise_seed")


@dataclass
class MetaItem:
    """One line in a section. A blank ``label`` renders as a bare value (prompt
    text, a filename); a set ``label`` renders as ``label: value``.

    ``copy`` drives a copy-to-clipboard button: ``None`` shows no button, a
    non-empty string is what the button copies, and an empty string shows the
    button but disabled — a field that exists yet holds nothing (a blank prompt).
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


def _prompt(title: str, text: str | None) -> MetaSection:
    text = text or ""
    return MetaSection(title, [MetaItem("", text, copy=text)])


def _param_item(key: str, value) -> MetaItem:
    """A parameter row. Seeds carry a copy button — they're the value most often
    lifted to reproduce a result; other params are plain."""
    copy = str(value) if key in _SEED_KEYS else None
    return MetaItem(key, str(value), copy=copy)


def _parameters(row: dict) -> MetaSection | None:
    params = gallery.parse_params(row.get("params_json"))
    items = [
        _param_item(key, value)
        for key, value in params.items()
        if key not in _PROMPT_KEYS
    ]
    return MetaSection("Parameters", items) if items else None


def _details(row: dict) -> MetaSection:
    return MetaSection("Details", [
        MetaItem("Status", str(row.get("status", ""))),
        MetaItem("Source", str(row.get("source", "generated"))),
    ])


def build_sections(row: dict) -> list[MetaSection]:
    sections = [
        _basic(row),
        _prompt("Positive Prompt", row.get("positive_prompt")),
        _prompt("Negative Prompt", row.get("negative_prompt")),
        _parameters(row),
        _details(row),
    ]
    return [s for s in sections if s is not None]
