"""Custom folders: the groupings the user composes by hand.

Everything else in the gallery tree is derived — a folder exists because some
generation's settings put it there. A custom folder is the opposite: the user
picks folders (Shift/Ctrl in the tree, or a drag onto its row) and names the
result. It holds *references* to folders, never copies of them, so a member
folder keeps its place in the hierarchy and gaining or losing generations
updates every custom folder that gathers it.

A saved folder is stored as a name plus a member list (see
:meth:`origenerator.db.Database.list_custom_folders`); :func:`build_custom_folders`
resolves those member keys against the freshly built tree into a
:class:`~origenerator.gallery.groups.CustomGroup`, which answers the same walkers
every other folder does. A member whose folder isn't in the tree right now — its
generations deleted, or its key drifted before the reconcile catches up — is
simply skipped rather than dropped from the saved list, so a folder that comes
back rejoins the grouping it was in.

Keys are ``__custom__/<id>``: prefixed like the synthetic shelves so no derived
folder key can collide with one, and carrying the row id so the saved folder is
recoverable from the key alone.
"""

from origenerator.gallery.groups import CustomGroup, child_groups

CUSTOM_PREFIX = "__custom__/"
# The throwaway folder a live multi-selection stands up: never saved, so it needs
# no id — but it is a CustomGroup like any other, so the pane, the breadcrumb and
# the slideshow treat a selection exactly as they treat a saved grouping.
SELECTION_KEY = "__selection__"


def custom_folder_key(folder_id: int) -> str:
    """The tree key of the saved custom folder with this row id."""
    return f"{CUSTOM_PREFIX}{folder_id}"


def custom_folder_id(key: str) -> int | None:
    """The saved custom folder a key names, or ``None`` if it names anything else
    (a derived folder, a shelf, or the unsaved selection)."""
    if not isinstance(key, str) or not key.startswith(CUSTOM_PREFIX):
        return None
    try:
        return int(key[len(CUSTOM_PREFIX):])
    except ValueError:
        return None


def is_custom_key(key) -> bool:
    """Whether ``key`` names a custom folder — saved or the live selection."""
    return key == SELECTION_KEY or custom_folder_id(key) is not None


def index_folders(tree: list) -> dict:
    """Every folder in ``tree`` by key, at any depth — how a member reference is
    resolved back to the live folder it points at."""
    found: dict = {}

    def walk(groups):
        for group in groups:
            found[group.key] = group
            walk(child_groups(group))

    walk(tree)
    return found


def build_custom_folders(tree: list, records) -> list[CustomGroup]:
    """Resolve saved custom folders against ``tree``.

    ``records`` are the rows :meth:`Database.list_custom_folders` returns —
    ``{"id", "name", "members"}`` with ``members`` a list of folder keys in the
    order they were added. Members that don't resolve are skipped (see the module
    docstring); an empty folder still appears, since a folder you have made and
    named but not yet filled is exactly where you are about to drop something.
    """
    index = index_folders(tree)
    folders = []
    for record in records:
        members = [index[key] for key in record["members"] if key in index]
        folders.append(CustomGroup(
            custom_folder_key(record["id"]), record["name"], members,
            folder_id=record["id"],
        ))
    return folders


def selection_group(groups: list) -> CustomGroup:
    """The unsaved custom folder a multi-selection stands for: the selected
    folders, labelled by how many there are."""
    return CustomGroup(SELECTION_KEY, f"{len(groups)} folders selected", list(groups))
