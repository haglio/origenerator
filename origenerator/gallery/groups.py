"""The folder tree's node types and the helpers that walk them.

Each level of the gallery hierarchy — media, workflow, model, LoRA, source
image, settings — is a small dataclass holding its stable key, display label, star state,
and children. The walkers (:func:`child_groups`, :func:`rows_under`) and the
tier/level classifiers (:func:`folder_level`, :func:`group_level`) work off those
types alone, so they live with the definitions rather than with the tree builder.

:class:`CustomGroup` sits alongside them as the one folder the *user* composes:
it holds whichever folders they gathered into it rather than a slice of the
hierarchy. It answers the same walkers, so everything built on them — the
folder path, the folder tiles, the slideshow's row list — treats it like any
other folder (see :mod:`origenerator.gallery.custom`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

_HIERARCHY_LEVELS = ("workflow", "model", "lora", "source_image")


@dataclass
class SettingsGroup:
    key: str
    label: str
    rows: list[dict]
    favorite: bool = False
    level: ClassVar[str] = "settings"
    children: ClassVar[tuple] = ()


@dataclass
class SourceImageGroup:
    """One source image an image-conditioned workflow animates: the settings
    leaves built from that image's configuration (its own re-rolls included)."""

    key: str
    label: str
    children: list[SettingsGroup]
    favorite: bool = False
    level: ClassVar[str] = "source_image"


@dataclass
class LoraGroup:
    key: str
    label: str
    # SourceImageGroups when the workflow is image-conditioned, else SettingsGroups
    # directly — the same conditional the model level applies for the LoRA tier.
    children: list
    favorite: bool = False
    level: ClassVar[str] = "lora"


@dataclass
class ModelGroup:
    key: str
    label: str
    # Always LoraGroups: a workflow with no LoRA keys collapses to a single
    # "(no LoRA)" folder rather than skipping the level, so depth stays uniform.
    # (An image-conditioned workflow grows a source-image level below the LoRA.)
    children: list[LoraGroup]
    favorite: bool = False
    level: ClassVar[str] = "model"


@dataclass
class WorkflowGroup:
    key: str
    workflow_name: str
    label: str
    children: list[ModelGroup]
    favorite: bool = False
    level: ClassVar[str] = "workflow"


@dataclass
class MediaGroup:
    key: str
    label: str
    children: list[WorkflowGroup]
    favorite: bool = False
    level: ClassVar[str] = "media"


@dataclass
class AllGroup:
    """The whole library as one folder: Images and Videos, gathered under a row.

    It exists so there is somewhere to *stand* that means everything. The tree
    selection scopes the search, so without a root over Images and Videos
    there would be no way to ask a question of the gallery as a whole — the
    collections are not folders, and either kind is already half of it.
    """

    key: str
    label: str
    children: list[MediaGroup]
    favorite: bool = False
    level: ClassVar[str] = "all"


@dataclass
class CustomGroup:
    """A folder the user composed: the folders they gathered into it and the
    items they put in it on their own, each in the order they were added.

    Unlike every tier above, what it gathers can sit at any depth and in any
    branch — it is a grouping, not a projection — so nothing nests beneath it in
    the tree. ``folder_id`` is the saved custom folder it renders (``None`` for
    the throwaway one a live multi-selection makes)."""

    key: str
    label: str
    children: list
    rows: list = field(default_factory=list)
    folder_id: int | None = None
    favorite: bool = False
    level: ClassVar[str] = "custom"


def folder_level(group) -> str | None:
    """Which hierarchy level a folder sits at: ``"workflow"``, ``"model"``,
    ``"lora"`` or ``"source_image"`` — ``None`` for the All row, Images and
    Videos, the settings leaves and a custom folder.

    Powers the TOC initial the gallery draws on tree rows and browser tiles, so
    a folder's place in the hierarchy reads at a glance rather than by counting
    indentation. A settings leaf is where the generations themselves live, and
    the All row is everything there is, so neither is a level anything needs
    naming.
    """
    return group.level if group.level in _HIERARCHY_LEVELS else None


def child_groups(group) -> list:
    """The sub-folders directly under a folder (empty for a settings leaf)."""
    return list(group.children)


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
    for row in [*group.rows, *rows]:
        if row["prompt_id"] not in seen:
            seen.add(row["prompt_id"])
            unique.append(row)
    return unique


def group_level(group) -> str:
    """Which tier of the tree ``group`` sits at: all, media, workflow, model,
    lora, source_image, custom, or settings. A favorite records its tier so its key can
    be recomputed from one of its rows under whatever key formula is current (see
    :func:`folder_key_at_level`)."""
    return group.level
