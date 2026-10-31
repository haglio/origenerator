"""Custom collections: the groupings the user composes by hand.

Everything else in the gallery tree is derived — a folder exists because some
generation's settings put it there. A custom collection is the opposite: the user
picks folders (Shift/Ctrl in the tree, or a drag onto its row) and names the
result. It holds *references* to folders, never copies of them, so a gathered
folder keeps its place in the hierarchy and gaining or losing generations
updates every custom collection that gathers it.

A saved folder is stored as a name plus a list of folder keys (see
:meth:`origenerator.db.Database.list_custom_collections`); :func:`build_custom_collections`
resolves those keys against the freshly built tree and the other saved folders
into a :class:`~origenerator.gallery.groups.CustomCollection`, which answers the same
walkers every other folder does. A folder that isn't in the tree right now — its
generations deleted, or its key drifted before the reconcile catches up — is
simply skipped rather than dropped from the saved list, so a folder that comes
back rejoins the grouping it was in.

Keys are ``__custom__/<id>``: prefixed like the synthetic collections so no derived
folder key can collide with one, and carrying the row id so the saved folder is
recoverable from the key alone.
"""
from __future__ import annotations

from origenerator.gallery.groups import CustomCollection, child_groups, rows_under

CUSTOM_PREFIX = "__custom__/"
# The throwaway folder a live multi-selection stands up: never saved, so it needs
# no id — but it is a CustomCollection like any other, so the pane, the folder path and
# the slideshow treat a selection exactly as they treat a saved grouping.
SELECTION_KEY = "__selection__"


def custom_collection_key(folder_id: int) -> str:
    """The tree key of the saved custom collection with this row id."""
    return f"{CUSTOM_PREFIX}{folder_id}"


def custom_folder_id(key: str) -> int | None:
    """The saved custom collection a key names, or ``None`` if it names anything else
    (a derived folder, a collection, or the unsaved selection)."""
    if not isinstance(key, str) or not key.startswith(CUSTOM_PREFIX):
        return None
    try:
        return int(key[len(CUSTOM_PREFIX):])
    except ValueError:
        return None


def index_folders(tree: list) -> dict:
    """Every folder in ``tree`` by key, at any depth — how an item reference is
    resolved back to the live folder it points at."""
    found: dict = {}

    def walk(groups):
        for group in groups:
            found[group.key] = group
            walk(child_groups(group))

    walk(tree)
    return found


def build_custom_collections(tree: list, records) -> list[CustomCollection]:
    """Resolve saved custom collections against ``tree``.

    ``records`` are the rows :meth:`Database.list_custom_collections` returns —
    ``{"id", "name", "side", "folders"}`` with ``folders`` a list of folder keys in
    the order they were added. Folders that don't resolve are skipped (see the
    module docstring); an empty folder still appears, since a folder you have made
    and named but not yet filled is exactly where you are about to drop something.
    """
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
    """Whether ``other`` is ``folder``, or a custom collection anywhere inside it."""
    return folder.key == other.key or any(
        holds(child, other) for child in child_groups(folder) if isinstance(child, CustomCollection))


def outermost(folders: list) -> list:
    held = {child.key for folder in folders for child in child_groups(folder)
            if isinstance(child, CustomCollection)}
    return [folder for folder in folders if folder.key not in held]


def selection_group(groups: list) -> CustomCollection:
    """The unsaved custom collection a multi-selection stands for: the selected
    folders, labelled by how many there are."""
    return CustomCollection(SELECTION_KEY, f"{len(groups)} folders selected", list(groups))
