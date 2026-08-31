"""What the gallery package publishes, and what it does not do.

``origenerator.gallery`` is a facade: ninety-odd names re-exported from a dozen
submodules, reached by the GUI as ``gallery.X``. Splitting a submodule behind it
is meant to be invisible from outside, and these are what say so — the published
surface held as an equality, and the one rule the package has about itself.
"""

import ast
from pathlib import Path

from origenerator import gallery

ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = ROOT / "origenerator" / "gallery"

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


# The one module of the package allowed to know a database exists.
THE_DB_MODULE = "enhance_fold.py"


def _modules(predicate) -> list[str]:
    """The package's modules for which *predicate* holds of the parsed source."""
    return sorted(path.name for path in _PACKAGE.glob("*.py")
                  if predicate(ast.parse(path.read_text(encoding="utf-8"))))


def _calls_a_db(tree) -> bool:
    """Whether the module calls anything on a local named ``db``."""
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and isinstance(node.func.value, ast.Name)
               and node.func.value.id == "db"
               for node in ast.walk(tree))


def _takes_a_db(tree) -> bool:
    """Whether any function in the module is handed a database."""
    return any(arg.arg == "db"
               for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               for arg in (*node.args.posonlyargs, *node.args.args,
                           *node.args.kwonlyargs))


def _imports_the_db_module(tree) -> bool:
    """Whether the module reaches for :mod:`origenerator.db` at all."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "origenerator.db":
            return True
        if isinstance(node, ast.Import) and any(a.name == "origenerator.db"
                                                for a in node.names):
            return True
    return False


def test_only_one_module_of_the_gallery_package_is_handed_a_database():
    # The package is otherwise pure: rows in, answers out. One module takes a
    # db, so a reader looking for what the gallery can change has one file to
    # read and a caller wanting the pure half can take it without a database.
    assert _modules(_takes_a_db) == [THE_DB_MODULE]


def test_only_that_module_calls_anything_on_a_database():
    # The same rule spelled a second way, because taking one and using one are
    # two facts and a module could pick up either without the other.
    assert _modules(_calls_a_db) == [THE_DB_MODULE]


def test_no_module_of_the_gallery_package_imports_the_database_module():
    # And a third: the two above see a parameter named db, so a module that
    # built its own connection would walk past both of them.
    assert _modules(_imports_the_db_module) == []
