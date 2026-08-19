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
* :mod:`.tree` — nesting rows into the media -> workflow -> model -> LoRA ->
  [source image] -> settings hierarchy, and the bookmark-key helpers around it.

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
from origenerator.gallery.groups import (
    AllGroup,
    CustomGroup,
    LoraGroup,
    MediaGroup,
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
    media_type_of_row,
    output_disk_files,
    output_file_path,
    output_file_reference,
    parse_file_list,
    produced_output,
    resolve_preview,
    row_output_files,
)
from origenerator.workflows.detail_parts import (
    match_fix_command,
    name_parts,
)
from origenerator.gallery.voice_commands import (
    ENHANCE_COMMAND,
    GENAU_COMMAND,
    command_bias,
    match_command,
)
from origenerator.gallery.enhance import (
    BASE_RENDER_SOURCE,
    ENHANCE_LEVEL_KEYS,
    ENHANCE_SETTING_KEYS,
    ENHANCE_WORKFLOW,
    MATCH_SOURCE_MODEL,
    EnhanceLevel,
    EnhanceSettings,
    default_enhance_params,
    describe_enhance_params,
    displayed_levels,
    enhance_levels,
    enhance_params_for,
    enhance_targets_row,
    fix_params_for,
    level_matching_params,
    level_matching_settings,
    original_files_of,
    fold_completed_enhancements,
    fold_enhancement,
    is_enhance_product_row,
    is_enhanceable_row,
    is_enhanced_row,
    remove_enhance_levels,
    rows_awaiting_enhancement,
)
from origenerator.gallery.signatures import (
    is_image_conditioned,
    lora_signature,
    model_signature,
    parse_params,
    rows_in_settings,
    settings_signature,
    workflow_output_type,
    workflow_param_order,
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
    unreviewed_experiments,
)
