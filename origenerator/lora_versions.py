from __future__ import annotations

from origenerator.model_titles import Version, lora_folder, model_title, versioned
from origenerator.recycle_bin import send_to_recycle_bin
from origenerator.workflows.model_files import ANY, is_no_lora, list_lora_files

FIRST_VERSION = Version(1, 0)


def installed_versions(base: str, family: str | None = None) -> list[tuple[Version, str]]:
    found = []
    for name in list_lora_files([], accepts=ANY if family is None else (family,), fix=None):
        parsed = None if is_no_lora(name) else versioned(model_title(name))
        if parsed is not None and parsed[0] == base:
            found.append((parsed[1], name))
    return sorted(found)


def newest_version(base: str, family: str | None = None) -> tuple[Version, str] | None:
    versions = installed_versions(base, family)
    return versions[-1] if versions else None


def next_version(base: str, family: str | None = None) -> Version:
    newest = newest_version(base, family)
    return Version(newest[0].major, newest[0].minor + 1) if newest else FIRST_VERSION


def _newer_version(lora, family: str | None) -> str | None:
    parsed = None if is_no_lora(lora) else versioned(model_title(lora))
    newest = newest_version(parsed[0], family) if parsed else None
    return newest[1] if newest and parsed[1] < newest[0] else None


def newest_offered_version(lora, offered) -> str | None:
    parsed = versioned(model_title(lora))
    versions = installed_versions(parsed[0]) if parsed else []
    return next((name for _version, name in reversed(versions) if name in offered), None)


def trash_tooltip(lora, family: str | None = None) -> str | None:
    newer = _newer_version(lora, family)
    return (f"Moves {model_title(lora)} to the Recycle Bin. {model_title(newer)} stays."
            if newer else None)


def trash_old_version(lora: str, *, send=send_to_recycle_bin) -> None:
    send(lora_folder() / lora)
