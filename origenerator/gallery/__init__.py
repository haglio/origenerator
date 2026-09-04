"""Pure gallery model: classify and group generations into a folder tree, with no
Qt dependency so it can be unit-tested directly.

The logic is split by responsibility, in dependency order:

* :mod:`.signatures` — parse a row's params and reduce them to the canonical keys
  the tree groups by (settings, model, LoRA, and an i2v's start-frame config).
* :mod:`.keys` — the stable key each derived folder is identified by, and the
  short code it is named by until the user names it.
* :mod:`.groups` — the folder-tier dataclasses and the helpers that walk them.
* :mod:`.custom` — the folders the user composes by hand, over those tiers.
* :mod:`.output` — what a generation produced on disk: media type, preview, files.
* :mod:`.labels` — the human-facing folder and Generate-tab names.
* :mod:`.source_image` — linking an i2v video to the image that seeded its frame.
* :mod:`.tree` — nesting rows into the workflow -> model -> LoRA ->
  [source image] -> settings hierarchy, and the bookmark-key helpers around it.
* :mod:`.enhance_settings` — what a folder's enhancement is configured with,
  and how one enhancement is described.
* :mod:`.enhance_graph` — the same knobs read back off a row's stored ComfyUI
  graph, for a row whose own params are vague about them.
* :mod:`.enhance` — what an enhancement is, which rows have had one and which
  want one.
* :mod:`.enhance_fold` — folding a finished enhancement onto the image it
  upgraded. The one module here that takes a database and changes what is in it;
  everything else takes rows and answers questions about them.

This package re-exports the public surface below, so ``from origenerator.gallery
import X`` and ``gallery.X`` keep working regardless of which submodule owns ``X``.
"""

from origenerator.gallery.combine import combined_params, curated_params
from origenerator.gallery.custom import (
    SELECTION_KEY,
    build_custom_folders,
    custom_folder_id,
    custom_folder_key,
    is_custom_key,
    selection_group,
)
from origenerator.gallery.enhance import (
    BASE_RENDER_SOURCE,
    EnhanceLevel,
    displayed_levels,
    enhance_levels,
    enhance_params_for,
    enhance_run_targets_row,
    enhance_target_id,
    enhance_targets_row,
    enhancement_recency,
    fix_params_for,
    is_enhance_product_row,
    is_enhanceable_row,
    is_enhanced_row,
    level_matching_params,
    level_matching_settings,
    original_files_of,
    remove_enhance_levels,
    rows_awaiting_enhancement,
)
from origenerator.gallery.enhance_fold import (
    fold_completed_enhancements,
    fold_enhancement,
)
from origenerator.gallery.enhance_settings import (
    ENHANCE_SETTING_KEYS,
    ENHANCE_WORKFLOW,
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    default_enhance_params,
    describe_enhance_params,
)
from origenerator.gallery.groups import (
    AllGroup,
    CustomGroup,
    LoraGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    child_groups,
    folder_detail,
    folder_level,
    group_level,
    is_renamable,
    rows_under,
)
from origenerator.gallery.keys import folder_id
from origenerator.gallery.labels import (
    config_folder_name,
    config_tab_title,
    item_label,
    job_kind_label,
    lora_label,
    model_label,
)
from origenerator.gallery.output import (
    animated_preview_path,
    is_in_progress,
    media_type_of_row,
    output_disk_files,
    output_file_path,
    output_file_reference,
    produced_output,
    resolve_preview,
    row_output_files,
    rows_of_media_types,
)
from origenerator.gallery.signatures import (
    is_image_conditioned,
    lora_signature,
    model_signature,
    parse_params,
    rows_in_settings,
    settings_signature,
    workflow_output_type,
)
from origenerator.gallery.source_image import (
    build_image_config_index,
    find_source_image_id,
    source_image_id_for,
    videos_from_source_image,
)
from origenerator.gallery.tree import (
    ALL_KEY,
    ALL_LABEL,
    all_group,
    build_gallery_tree,
    folder_key_at_level,
    legacy_preenhance_settings_folder_keys,
    legacy_preframe_settings_folder_key,
    legacy_preversion_settings_folder_key,
    legacy_settings_folder_key,
    named_folders_by_row,
    recent_generations,
    requested_generations,
    settings_folder_key,
    starred_folders,
    starred_generations,
    start_frame_index,
    unreviewed_experiments,
)
from origenerator.gallery.voice_commands import (
    ENHANCE_COMMAND,
    GENAU_COMMAND,
    command_bias,
    match_command,
    recognized_spelling,
)
from origenerator.workflows.detail_parts import (
    match_fix_command,
    name_parts,
)

# The surface outside code may import from this package, rather than left to be
# inferred from the import list above -- which reads to a linter as ninety-odd
# unused imports, so a genuinely accidental one could never be seen among them.
# A name kept for the package's own use is imported from its submodule and is
# not here.
__all__ = [
    "ALL_KEY",
    "ALL_LABEL",
    "BASE_RENDER_SOURCE",
    "ENHANCE_COMMAND",
    "ENHANCE_SETTING_KEYS",
    "ENHANCE_WORKFLOW",
    "GENAU_COMMAND",
    "MATCH_SOURCE_MODEL",
    "SELECTION_KEY",
    "AllGroup",
    "CustomGroup",
    "EnhanceLevel",
    "EnhanceSettings",
    "LoraGroup",
    "ModelGroup",
    "SettingsGroup",
    "SourceImageGroup",
    "WorkflowGroup",
    "all_group",
    "animated_preview_path",
    "build_custom_folders",
    "build_gallery_tree",
    "build_image_config_index",
    "child_groups",
    "combined_params",
    "command_bias",
    "config_folder_name",
    "config_tab_title",
    "curated_params",
    "custom_folder_id",
    "custom_folder_key",
    "default_enhance_params",
    "describe_enhance_params",
    "displayed_levels",
    "enhance_levels",
    "enhance_params_for",
    "enhance_run_targets_row",
    "enhance_target_id",
    "enhance_targets_row",
    "enhancement_recency",
    "find_source_image_id",
    "fix_params_for",
    "fold_completed_enhancements",
    "fold_enhancement",
    "folder_detail",
    "folder_id",
    "folder_key_at_level",
    "folder_level",
    "group_level",
    "is_custom_key",
    "is_enhance_product_row",
    "is_enhanceable_row",
    "is_enhanced_row",
    "is_image_conditioned",
    "is_in_progress",
    "is_renamable",
    "item_label",
    "job_kind_label",
    "legacy_preenhance_settings_folder_keys",
    "legacy_preframe_settings_folder_key",
    "legacy_preversion_settings_folder_key",
    "legacy_settings_folder_key",
    "level_matching_params",
    "level_matching_settings",
    "lora_label",
    "lora_signature",
    "match_command",
    "match_fix_command",
    "media_type_of_row",
    "model_label",
    "model_signature",
    "name_parts",
    "named_folders_by_row",
    "original_files_of",
    "output_disk_files",
    "output_file_path",
    "output_file_reference",
    "parse_params",
    "produced_output",
    "recent_generations",
    "recognized_spelling",
    "remove_enhance_levels",
    "requested_generations",
    "resolve_preview",
    "row_output_files",
    "rows_awaiting_enhancement",
    "rows_in_settings",
    "rows_of_media_types",
    "rows_under",
    "selection_group",
    "settings_folder_key",
    "settings_signature",
    "source_image_id_for",
    "starred_folders",
    "starred_generations",
    "start_frame_index",
    "unreviewed_experiments",
    "videos_from_source_image",
    "workflow_output_type",
]
