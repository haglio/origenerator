from __future__ import annotations

from origenerator.model_titles import Version, model_title, versioned
from origenerator.workflows.model_files import ANY, is_no_lora, list_lora_files

FIRST_VERSION = Version(1, 0)


def installed_versions(base: str, family: str | None = None) -> list[tuple[Version, str]]:
    found = []
    for name in list_lora_files([], accepts=ANY if family is None else (family,)):
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
