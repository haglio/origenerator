from __future__ import annotations

from origenerator.gallery.groups import CustomCollection, child_groups, rows_under

CUSTOM_PREFIX = "__custom__/"
SELECTION_KEY = "__selection__"


def custom_collection_key(folder_id: int) -> str:
    return f"{CUSTOM_PREFIX}{folder_id}"


def custom_folder_id(key: str) -> int | None:
    if not isinstance(key, str) or not key.startswith(CUSTOM_PREFIX):
        return None
    try:
        return int(key[len(CUSTOM_PREFIX):])
    except ValueError:
        return None


def index_folders(tree: list) -> dict:
    found: dict = {}

    def walk(groups):
        for group in groups:
            found[group.key] = group
            walk(child_groups(group))

    walk(tree)
    return found


def build_custom_collections(tree: list, records) -> list[CustomCollection]:
    items = {row["prompt_id"]: row for group in tree for row in rows_under(group)}
    built = [
        CustomCollection(custom_collection_key(record["id"]), record["name"], [],
                    [items[prompt_id] for prompt_id in record["items"] if prompt_id in items],
                    folder_id=record["id"])
        for record in records
    ]
    folders = index_folders(tree) | {group.key: group for group in built}
    for group, record in zip(built, records, strict=True):
        group.children.extend(folders[key] for key in record["folders"]
                              if key in folders and not holds(folders[key], group))
    return built


def holds(folder, other) -> bool:
    return folder.key == other.key or any(
        holds(child, other) for child in child_groups(folder) if isinstance(child, CustomCollection))


def outermost(folders: list) -> list:
    held = {child.key for folder in folders for child in child_groups(folder)
            if isinstance(child, CustomCollection)}
    return [folder for folder in folders if folder.key not in held]


def selection_group(groups: list) -> CustomCollection:
    return CustomCollection(SELECTION_KEY, f"{len(groups)} folders selected", list(groups))
