"""The read-only facts about one generation that the editable form does *not*
already show.

The gallery's info-pane tab is an editable :class:`GenerateConfigPanel`: it
renders the prompts and every parameter the workflow lays out as fields you can
change. Repeating those read-only would be the duplication the merged tab set out
to remove, so they are deliberately absent here. What the form has no field for —
the output file, when the run happened, its status and source, and any parameter
the workflow doesn't lay out (an import's extras, hidden passthrough like vae or
clip) — is gathered into titled sections for a compact block under the form.

Kept Qt-free so the section/item model is unit-testable directly;
``gui/metadata_block.py`` does the rendering.
"""

from dataclasses import dataclass

from origenerator import gallery

# Parameter keys that hold a reproducibility seed. A seed shown here earns a copy
# button — it's the value most often lifted to reproduce a result. Only reachable
# for an unknown workflow, since a registered one puts its seed in the form.
_SEED_KEYS = ("seed", "noise_seed")


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


def _extra_param_keys(params: dict, workflow_name: str | None) -> list[str]:
    """The row's param keys the workflow lays out no field for, in stored order.

    The editable form renders every key the workflow defines, so those are shown
    there, not repeated here. What's left — hidden passthrough (vae, clip), an
    import's extras — has no field, making this read-only block its only home. An
    unknown workflow lays out nothing, so all of its params surface here rather
    than being dropped. Empty for a row whose every param the form already covers.
    """
    laid_out = set(gallery.workflow_param_order(workflow_name))
    return [key for key in params if key not in laid_out]


def _param_item(key: str, value) -> MetaItem:
    copy = str(value) if key in _SEED_KEYS else None
    return MetaItem(key, str(value), copy=copy)


def _parameters(row: dict) -> MetaSection | None:
    params = gallery.parse_params(row.get("params_json"))
    keys = _extra_param_keys(params, row.get("workflow_name"))
    items = [_param_item(key, params[key]) for key in keys]
    return MetaSection("Parameters", items) if items else None


def _details(row: dict) -> MetaSection:
    return MetaSection("Details", [
        MetaItem("Status", str(row.get("status", ""))),
        MetaItem("Source", str(row.get("source", "generated"))),
    ])


def build_sections(row: dict) -> list[MetaSection]:
    sections = [_basic(row), _parameters(row), _details(row)]
    return [s for s in sections if s is not None]
