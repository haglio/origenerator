"""Pure gallery model: classify and group generations into a folder tree, with no
Qt dependency so it can be unit-tested directly.

The logic is split by responsibility, in dependency order:

* :mod:`.signatures` — parse a row's params and reduce them to the canonical keys
  the tree groups by (settings, model, LoRA, and an i2v's start-frame config).
* :mod:`.groups` — the folder-tier dataclasses and the helpers that walk them.
* :mod:`.output` — what a generation produced on disk: media type, preview, files.
* :mod:`.labels` — the human-facing folder and Generate-tab names.
* :mod:`.source_image` — linking an i2v video to the image that seeded its frame.
* :mod:`.tree` — nesting rows into the media -> workflow -> model -> LoRA ->
  [source image] -> settings hierarchy, and the bookmark-key helpers around it.

This package re-exports the public surface below, so ``from origenerator.gallery
import X`` and ``gallery.X`` keep working regardless of which submodule owns ``X``.
"""

from origenerator.gallery.combine import combined_params
from origenerator.gallery.groups import (
    LoraGroup,
    MediaGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    child_groups,
    folder_level,
    group_level,
    rows_under,
)
from origenerator.gallery.labels import (
    config_tab_title,
    lora_label,
    model_label,
)
from origenerator.gallery.output import (
    animated_preview_path,
    media_type_of_row,
    output_disk_files,
    output_file_reference,
    parse_file_list,
    produced_output,
    resolve_preview,
    row_output_files,
)
from origenerator.gallery.enhance import (
    ENHANCE_WORKFLOW,
    enhance_params_for,
    fold_completed_enhancements,
    fold_enhancement,
    is_enhanceable_row,
    is_enhanced_row,
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
    build_gallery_tree,
    folder_key_at_level,
    is_unvetted_experiment,
    legacy_preenhance_settings_folder_keys,
    legacy_preframe_settings_folder_key,
    legacy_preversion_settings_folder_key,
    legacy_settings_folder_key,
    recent_generations,
    settings_folder_key,
    starred_folders,
    starred_generations,
    unreviewed_experiments,
)
