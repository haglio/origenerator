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
    key: str
    label: str
    children: list[SettingsGroup]
    favorite: bool = False
    level: ClassVar[str] = "source_image"


@dataclass
class LoraGroup:
    key: str
    label: str
    children: list
    favorite: bool = False
    level: ClassVar[str] = "lora"


@dataclass
class ModelGroup:
    key: str
    label: str
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
    key: str
    label: str
    children: list[MediaGroup]
    favorite: bool = False
    level: ClassVar[str] = "all"


@dataclass
class CustomCollection:
    key: str
    label: str
    children: list
    rows: list = field(default_factory=list)
    folder_id: int | None = None
    favorite: bool = False
    level: ClassVar[str] = "custom"


def folder_level(group) -> str | None:
    return group.level if group.level in _HIERARCHY_LEVELS else None


def child_groups(group) -> list:
    return list(group.children)


def rows_under(group) -> list[dict]:
    if isinstance(group, SettingsGroup):
        return list(group.rows)
    rows = [row for child in child_groups(group) for row in rows_under(child)]
    if not isinstance(group, CustomCollection):
        return rows
    seen, unique = set(), []
    for row in [*group.rows, *rows]:
        if row["prompt_id"] not in seen:
            seen.add(row["prompt_id"])
            unique.append(row)
    return unique


def group_level(group) -> str:
    return group.level
