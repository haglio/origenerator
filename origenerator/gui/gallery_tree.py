"""Builds and queries the gallery's folder trees — the left TOC pane.

The pane is two trees, one per shape, each under a standing label and each
scrolling on its own (:class:`~origenerator.gui.split_folder_tree.SplitFolderTree`).
Each carries the whole table of contents: the Recents, Starred, Experiments,
Requests and Trash shelves, the folders the user composed, and the All row over
the workflow → model → LoRA → [source image] → settings hierarchy — all
built from that shape's rows alone. Standing anywhere means standing on one
shape, so a slideshow started there has one region to go to (see
:mod:`origenerator.gui.orientation`).

A row's key in the tree is therefore its folder's own key with the side
appended, and the two maps kept here — key→item and prompt-id→item — are keyed
that way. The folder's own key is what a star, a name and a custom folder's
membership hang off, and it is untouched: ``keys_by_folder`` maps one back to
the rows drawing it, which is how a navigation that knows only a folder key
(a re-roll, a combine, a folder tile) finds a row to select.

Pure rendering and lookups over the pane the GalleryView owns and lays out; it
has no database or refresh concerns — folder rename/star/delete live in the
view, which rebuilds both halves through :meth:`populate`.

The folders the user composed by hand ride between the shelves and the media
roots, rendered flat like a shelf: a custom folder's members can sit anywhere in
the hierarchy, so nesting them under it would draw the same folder twice and put
two rows in ``item_by_key`` for one key. Its contents show as tiles in the browser
pane instead, exactly as the Starred shelf shows its bookmarked folders.
"""

from dataclasses import dataclass, field

from PyQt6.QtWidgets import QTreeWidgetItem
from PyQt6.QtCore import Qt

from origenerator import gallery
from origenerator.gui import icons
from origenerator.gui.folder_tree import BRANCH_ICON_ROLE, DROP_KEY_ROLE, TREE_KEY_ROLE
from origenerator.gui.orientation import ORIENTATION_LABELS, orientation_of, oriented_key
from origenerator.recovery import RETENTION_DAYS

# The tree used to narrow itself to a query typed above it. It no longer does:
# a narrowed list of folder names is a poor answer to "where is the one with
# the two of them on the couch", because a folder's name is a short code and the
# thing you would actually recognize is the picture. The search now fills the
# browser pane with matching thumbnails instead (see
# BrowserPane.show_search_results), and the tree is left alone — so the folder
# you were standing in is still there when the search clears.

GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
RECENTS_KEY = "__recents__"   # synthetic tree node listing recently generated items
RECENTS_LABEL = "Latest"      # its row label; a clock is drawn in the caret column.
# "Latest" rather than "Recents" because that is the word the players use
# for the same ordering — a Fun Time session's browse says Latest, and this
# shelf is that same newest-first listing of what the app has made.
STARRED_KEY = "__starred__"   # synthetic tree node collecting every starred folder
# Its row label: the same concept as a Fun Time player's favorites (the star
# there IS the favorite mark), so it wears that name.  The key stays
# "__starred__" so saved expansions and history survive the rename.
STARRED_LABEL = "Favorites"
EXPERIMENTS_KEY = "__experiments__"  # synthetic node: the background-experiment home
EXPERIMENTS_LABEL = "Experiments"    # its row label; a flask is drawn in the caret column
REQUESTS_KEY = "__requests__"  # synthetic node: what spoken requests have queued
REQUESTS_LABEL = "Requests"    # its row label; a mic is drawn in the caret column
TRASH_KEY = "__trash__"   # synthetic node: deleted items still held for recovery
TRASH_LABEL = "Trash"     # its row label; a can is drawn in the caret column


@dataclass
class SideModel:
    """One side of the tree: everything the Portrait (or Landscape) root draws.

    Each count is that side's own — the Experiments row under Portrait says how
    many portrait experiments are waiting, because a number covering both sides
    would send you to a shelf that then showed you nothing.
    """

    orientation: str
    tree_model: list                       # this shape's media roots
    custom_folders: list = field(default_factory=list)
    show_recents: bool = False             # anything at all to list yet
    experiment_count: int = 0
    request_count: int = 0
    trash_count: int = 0


def _row_tip(group) -> str:
    """A folder row's hover text: its name, and what its name doesn't say."""
    detail = gallery.folder_detail(group)
    return f"{group.label} · {detail}" if detail else group.label


class GalleryTree:
    """The folder tree: builds it from the gallery model and answers the lookups
    (key→item, prompt→item, breadcrumb, the selected folder's key) the view
    navigates by. The pane holding the two trees is owned by the view."""

    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}  # tree key -> its row
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}   # prompt_id -> its settings row
        # plain key -> the tree keys drawing it, in side order. Each side draws
        # its own copy of every shelf, and of every folder holding rows of its
        # shape — so a caller holding a key with no side (a re-roll's folder, a
        # saved session's, a spoken shelf name) can still find a row.
        self.keys_by_folder: dict[str, list[str]] = {}
        self._built = False  # whether a first populate has happened (see _open_all)

    def populate(self, sides, expanded_keys, *, folder_meta=None):
        """Rebuild the tree from ``sides``, restoring the folders in ``expanded_keys``.

        ``sides`` are the :class:`SideModel`s to fill the halves with, one per
        shape. ``folder_meta`` is the same label/star overlay the tree models
        were built with, so the All row each side wraps around its model can be
        renamed and starred like any folder under it.
        """
        self._tree.blockSignals(True)
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.keys_by_folder = {}
        for side in sides:
            self._add_side(self._tree.root_for(side.orientation), side, folder_meta)
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all(expanded_keys)
        self._tree.blockSignals(False)
        self._built = True

    def _add_side(self, root, side, folder_meta) -> None:
        """One shape's whole table of contents, filling that shape's half.

        Both halves are always drawn, even for a side with nothing in it yet:
        the split is what tells a slideshow which screen it is for, so the side
        you have not generated for yet is still somewhere you can stand and
        somewhere its first generation can appear. Its label says so even while
        the rows under it are only empty shelves.
        """
        self._add_shelves(root, side)
        for custom in side.custom_folders:
            self._add_custom_folder(root, custom, side.orientation)
        # One row over that side's folders, standing for its library
        # entire. It is what the search means by "everywhere": the tree
        # selection scopes a query, so without a row above that side's folders
        # there is nowhere to stand that doesn't already narrow it by half.
        if side.tree_model:
            self._add_node(gallery.all_group(side.tree_model, folder_meta),
                           root, side.orientation)

    def _add_shelves(self, side_item, side) -> None:
        """The synthetic shelves leading a side: Recents (in-flight work plus
        recently finished items) whenever there is anything to show — so a first
        generation is visible while it runs, before any folder exists — then
        Favorites (starred folders and items) once folders do, then Experiments,
        Requests and Trash, all three always present: the first hosts the
        background experimenter's review queue, the second is where everything
        you asked for out loud lands, and the third is where every delete goes —
        and a bin you can only find once you have something to recover is no use.
        Each draws its marker in the caret column so its label lines up with the
        folders below."""
        if side.show_recents:
            self._add_shelf(side_item, RECENTS_LABEL, RECENTS_KEY, side.orientation,
                            icons.clock_icon(), "Recently generated")
        if side.tree_model:
            starred = self._add_shelf(
                side_item, STARRED_LABEL, STARRED_KEY, side.orientation,
                icons.star_icon(filled=True),
                "Your favorite folders and items — drop a folder here to add it"
            )
            # Favoriting is what the shelf does with a dropped folder, so it
            # collects. A star is the folder's own, not this side's, so the drop
            # key is the shelf's plain key.
            starred.setData(0, DROP_KEY_ROLE, STARRED_KEY)
        self._add_shelf(
            side_item, _counted(EXPERIMENTS_LABEL, side.experiment_count),
            EXPERIMENTS_KEY, side.orientation, icons.flask_icon(),
            "Background experiments awaiting your review"
        )
        self._add_shelf(
            side_item, _counted(REQUESTS_LABEL, side.request_count),
            REQUESTS_KEY, side.orientation, icons.mic_icon(),
            "What you asked for out loud — “Request … over”"
        )
        self._add_shelf(
            side_item, _counted(TRASH_LABEL, side.trash_count),
            TRASH_KEY, side.orientation, icons.trash_icon(),
            f"Deleted items — restorable here for {RETENTION_DAYS} days"
        )

    def _register(self, item, key: str, parent_item,
                  folder_key: str | None = None) -> QTreeWidgetItem:
        """Hang ``item`` under ``parent_item`` as ``key``, and index it.

        The key rides the row itself so the selected row can name its own place
        without anything having to work out which side it is on;
        ``keys_by_folder`` is the way back for a caller holding a key with no
        side on it (``folder_key`` — only a side's own root has none)."""
        item.setData(0, TREE_KEY_ROLE, key)
        parent_item.addChild(item)
        self.item_by_key[key] = item
        if folder_key is not None:
            self.keys_by_folder.setdefault(folder_key, []).append(key)
        return item

    def _open_all(self, expanded_keys) -> None:
        """Open every side's All row on a gallery's first build.

        Every other folder defaults shut, but All shut is a side with nothing in
        it — the workflow folders are where the gallery starts. Only on the first
        build: after that its state is the user's, saved and restored with every
        other folder's, so collapsing it sticks.
        """
        if self._built or expanded_keys:
            return
        for key in self.keys_by_folder.get(gallery.ALL_KEY, ()):
            self.item_by_key[key].setExpanded(True)

    def _add_shelf(self, side_item, label, key, orientation, icon,
                   tooltip) -> QTreeWidgetItem:
        """Add a synthetic shelf row (Recents/Favorites/…) leading a side, its
        marker drawn in the caret column so its label aligns with the media
        folders below."""
        item = QTreeWidgetItem([label])
        item.setData(0, BRANCH_ICON_ROLE, icon)  # marker in the caret column
        item.setToolTip(0, tooltip)
        return self._register(item, oriented_key(key, orientation), side_item,
                              folder_key=key)

    def _add_custom_folder(self, side_item, group, orientation) -> QTreeWidgetItem:
        """Add a row for one of the user's own folders: a shelf-shaped row carrying
        its group (so the view's folder machinery — breadcrumb, tiles, slideshow —
        treats it like any other folder), editable for an inline rename, and
        collecting the folders dropped onto it."""
        count = len(gallery.rows_under(group))
        item = QTreeWidgetItem([group.label])
        item.setData(0, BRANCH_ICON_ROLE, icons.custom_folder_icon())
        item.setToolTip(0, f"{group.label} — {count} item{'s' if count != 1 else ''} "
                           "in a folder you made; drop folders here to add them")
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, DROP_KEY_ROLE, group.key)  # the folder gathers, not the side
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        return self._register(item, oriented_key(group.key, orientation), side_item,
                              folder_key=group.key)

    def _add_node(self, group, parent_item, orientation) -> QTreeWidgetItem:
        # Starred state shows as the row's star icon (the delegate reads it from
        # the group), so the label itself carries no ★ prefix.
        item = QTreeWidgetItem([group.label])
        if gallery.is_renamable(group):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, GROUP_ROLE, group)
        # A workflow / model / LoRA / source-image row wears a lettered chip
        # naming its level, so a row's place in the hierarchy reads at a glance
        # rather than by counting indentation; the level joins the tooltip too.
        # The All row and the settings leaves get neither (folder_level returns
        # None).
        #
        # It is the row's *icon*, so it sits right of the caret and reads as the
        # first character of the folder's name — which is what it is. What that
        # costs is the label: Qt lays the text out after the icon, so a chipped
        # row's text starts a chip-width right of an unchipped sibling's. The
        # thing that stays uniform is where each row's name *block* begins, at
        # exactly its depth times the indentation.
        level = gallery.folder_level(group)
        if level is not None:
            item.setIcon(0, icons.level_badge_icon(level))
            item.setToolTip(0, f"{group.label} · {icons.LEVEL_LABELS[level]}")
        else:
            # A settings leaf is named by a code, so its tooltip is where the
            # prompt and the settings that set it apart from its siblings are
            # read — the row itself stays one short line.
            item.setToolTip(0, _row_tip(group))
        self._register(item, oriented_key(group.key, orientation), parent_item,
                       folder_key=group.key)
        for child in gallery.child_groups(group):
            self._add_node(child, item, orientation)
        if isinstance(group, gallery.SettingsGroup):
            for row in group.rows:
                self.leaf_by_id[row["prompt_id"]] = item
        return item

    def keys_for_folder(self, folder_key: str) -> list[str]:
        """The tree keys drawing ``folder_key`` — a folder's own key or a shelf's
        — in side order, empty for one no side is holding right now."""
        return list(self.keys_by_folder.get(folder_key, ()))

    def shelf_item(self, shelf_key: str, orientation: str) -> QTreeWidgetItem | None:
        """One side's copy of a shelf row."""
        return self.item_by_key.get(oriented_key(shelf_key, orientation))

    def default_item(self) -> QTreeWidgetItem | None:
        """The folder to land on with no saved target: the first side's All row —
        the whole of the shape the tree opens on — falling back to a side that
        has one, and then to a Latest shelf, so a first generation stays visible
        while it runs with no folders around it yet."""
        for base in (gallery.ALL_KEY, RECENTS_KEY):
            keys = self.keys_by_folder.get(base)
            if keys:
                return self.item_by_key[keys[0]]
        return None

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def selected_folder_key(self) -> str | None:
        """The tree key of the selected row — its folder's key with the side it is
        being looked at from appended, or a shelf's own oriented key."""
        item = self._tree.currentItem()
        return item.data(0, TREE_KEY_ROLE) if item is not None else None

    def breadcrumb(self, item) -> str:
        """The path down to ``item``, led by its side.

        The side comes from the row's own key rather than from a row above it —
        each half is a tree of its own — and it leads the path because a
        folder's label alone would not say which of the two copies of it you
        are standing in. The header over the browser pane is a long way from
        the label over the half you clicked.
        """
        parts = []
        node = item
        while node is not None:
            group = node.data(0, GROUP_ROLE)
            # Only a shelf row has no group, and it is named by its own text.
            parts.append(group.label if group is not None else node.text(0))
            node = node.parent()
        side = orientation_of(item.data(0, TREE_KEY_ROLE)) if item is not None else None
        if side is not None:
            parts.append(ORIENTATION_LABELS[side])
        return "  ›  ".join(reversed(parts))


def _counted(label: str, count: int) -> str:
    """A shelf's label, wearing its count when it has one to show."""
    return f"{label} ({count})" if count else label
