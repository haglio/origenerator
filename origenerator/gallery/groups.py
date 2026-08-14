"""The folder tree's node types and the helpers that walk them.

Each level of the gallery hierarchy — media, workflow, model, LoRA, source image,
settings — is a small dataclass holding its stable key, display label, star state,
and children. The walkers (:func:`child_groups`, :func:`rows_under`) and the
tier/level classifiers (:func:`folder_level`, :func:`group_level`) work off those
types alone, so they live with the definitions rather than with the tree builder.

:class:`CustomGroup` sits alongside them as the one folder the *user* composes:
it holds whichever folders they gathered into it rather than a slice of the
hierarchy. It answers the same walkers, so everything built on them — the
breadcrumb, the folder tiles, the slideshow's row list — treats it like any
other folder (see :mod:`origenerator.gallery.custom`).
"""

from dataclasses import dataclass


@dataclass
class SettingsGroup:
    key: str
    label: str
    rows: list[dict]
    starred: bool = False


@dataclass
class SourceImageGroup:
    """One source image an image-conditioned workflow animates: the settings
    leaves built from that image's configuration (its own re-rolls included)."""

    key: str
    label: str
    children: list[SettingsGroup]
    starred: bool = False


@dataclass
class LoraGroup:
    key: str
    label: str
    # SourceImageGroups when the workflow is image-conditioned, else SettingsGroups
    # directly — the same conditional the model level applies for the LoRA tier.
    children: list
    starred: bool = False


@dataclass
class ModelGroup:
    key: str
    label: str
    # Always LoraGroups: a workflow with no LoRA keys collapses to a single
    # "(no LoRA)" folder rather than skipping the level, so depth stays uniform.
    # (An image-conditioned workflow grows a source-image level below the LoRA.)
    children: list[LoraGroup]
    starred: bool = False


@dataclass
class WorkflowGroup:
    key: str
    workflow_name: str
    label: str
    model_groups: list[ModelGroup]
    starred: bool = False


@dataclass
class MediaGroup:
    key: str
    media_type: str
    label: str
    workflow_groups: list[WorkflowGroup]
    starred: bool = False


@dataclass
class CustomGroup:
    """A folder the user composed: the folders they gathered into it, in the
    order they were added.

    Unlike every tier above, its members can sit at any depth and in any branch —
    it is a grouping, not a projection — so it holds resolved child *groups*
    rather than rows, and nothing nests beneath it in the tree. ``folder_id`` is
    the saved custom folder it renders (``None`` for the throwaway one a live
    multi-selection makes)."""

    key: str
    label: str
    children: list
    folder_id: int | None = None
    starred: bool = False


def folder_level(group) -> str | None:
    """Which hierarchy level a folder sits at: ``"workflow"``, ``"model"``,
    ``"lora"``, or ``"source_image"`` — or ``None`` for the media roots and
    settings leaves.

    Powers the per-level badge the gallery draws on tree rows and browser tiles:
    a media folder is self-evidently Images/Videos and a settings leaf is where
    the generations themselves live, so neither needs one.
    """
    for cls, level in (
        (WorkflowGroup, "workflow"), (ModelGroup, "model"),
        (LoraGroup, "lora"), (SourceImageGroup, "source_image"),
    ):
        if isinstance(group, cls):
            return level
    return None


def child_groups(group) -> list:
    """The sub-folders directly under a folder (empty for a settings leaf)."""
    if isinstance(group, MediaGroup):
        return group.workflow_groups
    if isinstance(group, WorkflowGroup):
        return group.model_groups
    if isinstance(group, (ModelGroup, LoraGroup, SourceImageGroup, CustomGroup)):
        return group.children
    return []


def rows_under(group) -> list[dict]:
    """Every generation beneath a folder, at any depth.

    A custom folder can gather two folders where one contains the other, so its
    walk drops repeats — a generation counted twice would be played twice by the
    slideshow and counted twice on its tile."""
    if isinstance(group, SettingsGroup):
        return list(group.rows)
    rows = [row for child in child_groups(group) for row in rows_under(child)]
    if not isinstance(group, CustomGroup):
        return rows  # the hierarchy proper never nests a folder under two parents
    seen, unique = set(), []
    for row in rows:
        if row["prompt_id"] not in seen:
            seen.add(row["prompt_id"])
            unique.append(row)
    return unique


def group_level(group) -> str:
    """Which tier of the tree ``group`` sits at: media, workflow, model, lora, or
    settings. A bookmark records its tier so its key can be recomputed from a
    member row under whatever key formula is current (see
    :func:`folder_key_at_level`)."""
    if isinstance(group, MediaGroup):
        return "media"
    if isinstance(group, WorkflowGroup):
        return "workflow"
    if isinstance(group, ModelGroup):
        return "model"
    if isinstance(group, LoraGroup):
        return "lora"
    if isinstance(group, SourceImageGroup):
        return "source_image"
    if isinstance(group, CustomGroup):
        return "custom"
    return "settings"
