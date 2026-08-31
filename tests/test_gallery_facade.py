"""What the gallery package publishes, and what it does not do.

``origenerator.gallery`` is a facade: ninety-odd names re-exported from a dozen
submodules, reached by the GUI as ``gallery.X``. Splitting a submodule behind it
is meant to be invisible from outside, and these are what say so — the published
surface held as an equality, and the one rule the package has about itself.
"""

import ast
from pathlib import Path

from origenerator import gallery

_PACKAGE = Path("origenerator/gallery")

# Every name the package publishes. Held as an equality rather than a floor: a
# name added without a line here is as much a failure as one dropped, because
# the GUI reaches most of these as gallery.X and nothing else records what the
# facade owes its callers.
PUBLISHED = {
    "ALL_KEY", "ALL_LABEL", "AllGroup", "BASE_RENDER_SOURCE", "CustomGroup",
    "ENHANCE_COMMAND", "ENHANCE_SETTING_KEYS", "ENHANCE_WORKFLOW",
    "EnhanceLevel", "EnhanceSettings", "GENAU_COMMAND", "LoraGroup",
    "MATCH_SOURCE_MODEL", "ModelGroup", "SELECTION_KEY", "SettingsGroup",
    "SourceImageGroup", "WorkflowGroup", "all_group",
    "animated_preview_path", "build_custom_folders", "build_gallery_tree",
    "build_image_config_index", "child_groups", "combined_params",
    "command_bias", "config_folder_name", "config_tab_title",
    "curated_params", "custom_folder_id", "custom_folder_key",
    "default_enhance_params", "describe_enhance_params", "displayed_levels",
    "enhance_levels", "enhance_params_for", "enhance_targets_row",
    "find_source_image_id", "fix_params_for", "fold_completed_enhancements",
    "fold_enhancement", "folder_detail", "folder_id", "folder_key_at_level",
    "folder_level", "group_level", "is_custom_key",
    "is_enhance_product_row", "is_enhanceable_row", "is_enhanced_row",
    "is_image_conditioned", "is_in_progress", "is_renamable", "item_label",
    "job_kind_label", "legacy_preenhance_settings_folder_keys",
    "legacy_preframe_settings_folder_key",
    "legacy_preversion_settings_folder_key", "legacy_settings_folder_key",
    "level_matching_params", "level_matching_settings", "lora_label",
    "lora_signature", "match_command", "match_fix_command",
    "media_type_of_row", "model_label", "model_signature", "name_parts",
    "named_folders_by_row", "original_files_of", "output_disk_files",
    "output_file_path", "output_file_reference", "parse_params",
    "produced_output", "recent_generations", "recognized_spelling",
    "remove_enhance_levels", "requested_generations", "resolve_preview",
    "row_output_files", "rows_awaiting_enhancement", "rows_in_settings",
    "rows_of_media_types", "rows_under", "selection_group",
    "settings_folder_key", "settings_signature", "source_image_id_for",
    "starred_folders", "starred_generations", "unreviewed_experiments",
    "videos_from_source_image", "workflow_output_type",
}


def test_the_facade_publishes_exactly_the_names_written_down_here():
    assert set(gallery.__all__) == PUBLISHED


def test_every_published_name_is_actually_there():
    # __all__ is a promise, not a check: a name listed but never imported
    # raises only when someone reaches for it, which for a facade this wide
    # means at some point long after the split that dropped it.
    missing = [name for name in PUBLISHED if not hasattr(gallery, name)]
    assert missing == []


def _writes_in(path: Path) -> list[str]:
    """Every ``db.<something>`` call in the file that is not a plain read."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    writes = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func.value
        if not (isinstance(target, ast.Name) and target.id == "db"):
            continue
        writes.append(f"{path.name}:{node.lineno} db.{node.func.attr}")
    return writes


def test_only_one_module_of_the_gallery_package_touches_the_database():
    # The package is otherwise pure: rows in, answers out. One module holds
    # every call against a database, so a reader looking for what the gallery
    # can change has one file to read and a caller wanting the pure half can
    # take it without a database at all.
    touching = sorted({path.name for path in _PACKAGE.glob("*.py")
                       if _writes_in(path)})
    assert touching == ["enhance_fold.py"]
