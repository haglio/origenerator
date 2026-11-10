from __future__ import annotations

import ast
from pathlib import Path

from origenerator import gallery

ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = ROOT / "origenerator" / "gallery"

PUBLISHED = {
    "ALL_KEY", "ALL_LABEL", "AllGroup", "CustomCollection",
    "ENHANCE_COMMAND", "ENHANCE_SETTING_KEYS", "ENHANCE_WORKFLOW",
    "EnhanceVersion", "EnhanceSettings", "GENERATION_SEED_KEYS",
    "JobKind", "LoraGroup",
    "MATCH_SOURCE_MODEL", "MEDIA_LABELS", "MediaGroup", "ModelGroup", "SELECTION_KEY", "CYCLE_FRAMES",
    "SettingsGroup",
    "SourceImageGroup", "WorkflowGroup", "all_group", "animated_preview_if_made",
    "build_custom_collections", "build_gallery_tree", "build_image_config_index", "image_config_index_of",
    "child_groups", "combined_params", "command_phrases", "config_folder_key",
    "config_folder_name",
    "generate_tab_title", "custom_folder_id",
    "custom_collection_key", "default_enhance_params", "describe_enhance_params",
    "disown_foreign_runs",
    "displayed_versions", "enhancement_versions", "enhance_params_for",
    "enhance_run_targets_row", "enhance_target_id", "enhance_targets_row",
    "enhanced_version_of", "enhancement_recency", "enhancements_of_images_gone", "find_source_image_id",
    "fix_params_for",
    "fold_completed_enhancements", "fold_enhancement",
    "folder_chain", "folder_id", "folder_key_at_level", "folder_key_for", "folder_level", "folder_names_by_row", "folder_signature",
    "full_settings",
    "generation_of_file",
    "generation_seed", "group_level", "holds", "image_lent_by", "input_image_reference",
    "is_enhance_product_row", "is_enhanceable_row",
    "is_enhanced_row", "is_image_conditioned", "is_in_progress",
    "job_kind_label", "landing_for",
    "legacy_parentless_folder_key", "legacy_preenhance_settings_folder_keys",
    "legacy_preframe_settings_folder_key",
    "legacy_preversion_settings_folder_key", "legacy_settings_folder_key",
    "version_matching_params", "version_matching_settings", "lora_label",
    "lora_signature", "make_animated_preview", "match_command",
    "media_type_of_row", "model_label", "model_matching_the_source", "model_signature",
    "models_matching_a_folders_sources", "models_matching_the_sources",
    "new_work_opens_a_section", "original_files_of",
    "outermost", "output_disk_files",
    "output_file_path", "output_file_reference", "parse_params",
    "produced_output", "prompts_differ_from", "rebuildable_source_image",
    "rebuildable_source_image_id_in",
    "recent_generations", "recently_worked_folders", "recognized_spelling",
    "remove_enhance_versions", "rerollable", "resolve_preview",
    "row_output_files", "rows_awaiting_enhancement", "rows_in_settings",
    "rows_under", "same_enhancement", "section_headings", "selection_group",
    "settings_folder_key", "settings_signature", "source_image_id_for",
    "source_image_id_in", "source_image_id_of", "source_image_of", "start_images_among",
    "enhanced_generations", "favorite_folders", "favorite_generations", "start_frame_index",
    "cycle_shaped",
    "unreviewed_experiments",
    "video_file_of", "videos_from_source_image", "was_made_from", "was_taken_from", "workflow_output_type",
    "written_params",
}


def test_the_facade_publishes_exactly_the_names_written_down_here():
    assert set(gallery.__all__) == PUBLISHED, (
        "listed, the names offered outside can be told from a stray import, which a linter "
        "cannot do among imports that only re-export; a name the package keeps "
        "for its own use is imported from its submodule and stays off the list")


def test_every_published_name_is_actually_there():
    missing = [name for name in PUBLISHED if not hasattr(gallery, name)]
    assert missing == []


THE_DB_MODULE = "enhance_fold.py"


def _modules(predicate) -> list[str]:
    return sorted(path.name for path in _PACKAGE.glob("*.py")
                  if predicate(ast.parse(path.read_text(encoding="utf-8"))))


def _calls_a_db(tree) -> bool:
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and isinstance(node.func.value, ast.Name)
               and node.func.value.id == "db"
               for node in ast.walk(tree))


def _takes_a_db(tree) -> bool:
    return any(arg.arg == "db"
               for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               for arg in (*node.args.posonlyargs, *node.args.args,
                           *node.args.kwonlyargs))


def _imports_the_db_module(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "origenerator.db":
            return True
        if isinstance(node, ast.Import) and any(a.name == "origenerator.db"
                                                for a in node.names):
            return True
    return False


def test_only_one_module_of_the_gallery_package_is_handed_a_database():
    assert _modules(_takes_a_db) == [THE_DB_MODULE], (
        "the package is otherwise rows in, answers out: whoever looks for what the gallery can "
        "change has one file to read")


def test_only_that_module_calls_anything_on_a_database():
    assert _modules(_calls_a_db) == [THE_DB_MODULE], (
        "taking a database and using one are two facts, and a module could pick up either without "
        "the other")


def test_no_module_of_the_gallery_package_imports_the_database_module():
    assert _modules(_imports_the_db_module) == []
