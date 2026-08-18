"""Builds and queries the gallery's folder-tree widget — the left TOC pane.

Renders the Recents, Starred, Experiments, Requests and Trash shelves atop the
media → workflow → model → LoRA → [source image] → settings folders, and keeps the
key→item and prompt-id→item maps the view navigates by. Pure tree rendering and lookups over a ``FolderTree`` the
GalleryView owns and lays out; it has no database or refresh concerns — folder
rename/star/delete live in the view, which rebuilds the tree through :meth:`populate`.

The folders the user composed by hand ride between the shelves and the media
roots, rendered flat like a shelf: a custom folder's members can sit anywhere in
the hierarchy, so nesting them under it would draw the same folder twice and put
two rows in ``item_by_key`` for one key. Its contents show as tiles in the browser
pane instead, exactly as the Starred shelf shows its bookmarked folders.
"""

from PyQt6.QtWidgets import QTreeWidgetItem
from PyQt6.QtCore import Qt

from origenerator import gallery
from origenerator.gui import icons
from origenerator.gui.folder_tree import BRANCH_ICON_ROLE, DROP_KEY_ROLE
from origenerator.gui.shelf_orientation import ORIENTATION_LABELS, ORIENTATIONS, oriented_key
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
RECENTS_LABEL = "Recents"     # its row label; a clock is drawn in the caret column
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

# The shelves that collect media of every shape at once — each breaks down into
# a Portrait and a Landscape subfolder, so what a subfolder plays is one shape
# and lands on one region (see origenerator.gui.shelf_orientation).
ORIENTED_SHELF_KEYS = (RECENTS_KEY, STARRED_KEY, EXPERIMENTS_KEY)


def _row_tip(group) -> str:
    """A folder row's hover text: its name, and what its name doesn't say."""
    detail = gallery.folder_detail(group)
    return f"{group.label} · {detail}" if detail else group.label


class GalleryTree:
    """The folder tree: builds it from the gallery model and answers the lookups
    (key→item, prompt→item, breadcrumb, the selected folder's key) the view
    navigates by. The ``FolderTree`` widget itself is owned by the view."""

    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}  # folder key -> its tree row
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}   # prompt_id -> its settings row
        self.recents_item: QTreeWidgetItem | None = None   # the "Recents" shelf row
        self.starred_item: QTreeWidgetItem | None = None   # the "★ Favorites" shelf row
        self.experiments_item: QTreeWidgetItem | None = None  # the "Experiments" shelf row
        self.requests_item: QTreeWidgetItem | None = None  # the "Requests" shelf row
        self.trash_item: QTreeWidgetItem | None = None     # the "Trash" shelf row
        self.custom_items: dict[str, QTreeWidgetItem] = {}  # custom folder key -> its row
        self._built = False  # whether a first populate has happened (see _open_all)

    def populate(self, tree_model, expanded_keys, *, show_recents: bool,
                 experiment_count: int = 0, trash_count: int = 0,
                 request_count: int = 0, custom_folders=(),
                 folder_meta=None):
        """Rebuild the tree from ``tree_model``, restoring the folders in
        ``expanded_keys``. ``show_recents`` keeps the Recents shelf up even with no
        folders yet (in-flight work to show); Favorites appears only once folders do.
        ``experiment_count`` (unreviewed background experiments),
        ``request_count`` (items spoken requests have queued) and
        ``trash_count`` (deleted items still recoverable) show in their shelves'
        labels so waiting work is visible from anywhere. ``custom_folders`` are
        the user's own groupings, each getting a row of its own between the
        shelves and the media roots. ``folder_meta`` is the same label/star
        overlay the tree model was built with, so the All row it wraps around
        that model can be renamed and starred like any folder under it."""
        self._tree.blockSignals(True)
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.recents_item = None
        self.starred_item = None
        self.experiments_item = None
        self.requests_item = None
        self.trash_item = None
        self.custom_items = {}
        root = self._tree.invisibleRootItem()
        # Synthetic shelves lead the tree: Recents (in-flight work plus recently
        # finished items) whenever there is anything to show — so a first-ever
        # generation is visible while it runs, before any folder exists — then
        # Favorites (starred folders and items) once folders do, then
        # Experiments, Requests and Trash, all three always present: the first
        # hosts the background experimenter's switch and review queue, the
        # second is where everything you asked for out loud lands, and the
        # third is where every delete goes — and a bin you can only find once
        # you have something to recover is no use. Each is reachable in one
        # click however the tree is scrolled, and draws its marker in the caret
        # column so its label lines up with the media folders below.  The
        # collecting shelves mix every shape, so each carries a Portrait and a
        # Landscape subfolder — the same listing, one shape, one region.
        if show_recents:
            self.recents_item = self._add_shelf(
                root, RECENTS_LABEL, RECENTS_KEY, icons.clock_icon(), "Recently generated"
            )
            self._add_orientation_children(self.recents_item, RECENTS_KEY)
        if tree_model:
            self.starred_item = self._add_shelf(
                root, STARRED_LABEL, STARRED_KEY, icons.star_icon(filled=True),
                "Your favorite folders and items — drop a folder here to add it"
            )
            # Favoriting is what the shelf does with a dropped folder, so it collects.
            self.starred_item.setData(0, DROP_KEY_ROLE, STARRED_KEY)
            self._add_orientation_children(self.starred_item, STARRED_KEY)
        label = EXPERIMENTS_LABEL + (f" ({experiment_count})" if experiment_count else "")
        self.experiments_item = self._add_shelf(
            root, label, EXPERIMENTS_KEY, icons.flask_icon(),
            "Background experiments awaiting your review"
        )
        self._add_orientation_children(self.experiments_item, EXPERIMENTS_KEY)
        label = REQUESTS_LABEL + (f" ({request_count})" if request_count else "")
        self.requests_item = self._add_shelf(
            root, label, REQUESTS_KEY, icons.mic_icon(),
            "What you asked for out loud — “Request … over”"
        )
        label = TRASH_LABEL + (f" ({trash_count})" if trash_count else "")
        self.trash_item = self._add_shelf(
            root, label, TRASH_KEY, icons.trash_icon(),
            f"Deleted items — restorable here for {RETENTION_DAYS} days"
        )
        for custom in custom_folders:
            self.custom_items[custom.key] = self._add_custom_folder(root, custom)
        # One root over the media folders, standing for the library entire. It is
        # what the search means by "everywhere": the tree selection scopes a query,
        # so without a row above Images and Videos there is nowhere to stand that
        # doesn't already narrow the answer by half.
        if tree_model:
            self._add_node(gallery.all_group(tree_model, folder_meta), root)
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all(expanded_keys)
        self._tree.blockSignals(False)
        self._built = True

    def _open_all(self, expanded_keys) -> None:
        """Open the All row on a gallery's first build.

        Every other folder defaults shut, but All shut is a tree with nothing in
        it — Images and Videos are where the gallery starts. Only on the first
        build: after that its state is the user's, saved and restored with every
        other folder's, so collapsing it sticks.
        """
        item = self.item_by_key.get(gallery.ALL_KEY)
        if item is not None and not self._built and not expanded_keys:
            item.setExpanded(True)

    def _add_shelf(self, root, label, key, icon, tooltip) -> QTreeWidgetItem:
        """Add a synthetic shelf row (Recents/Favorites) leading the tree, its marker
        drawn in the caret column so its label aligns with the media folders below."""
        item = QTreeWidgetItem([label])
        item.setData(0, BRANCH_ICON_ROLE, icon)  # marker in the caret column
        item.setToolTip(0, tooltip)
        root.addChild(item)
        self.item_by_key[key] = item
        return item

    def _add_orientation_children(self, shelf_item, base_key: str) -> None:
        """The shelf's Portrait / Landscape subfolders: the same listing, one
        shape each, so what a subfolder plays lands on one region.

        Expanded outright: a shelf row draws its marker IN the caret column,
        so there is no expander to click — children left collapsed simply do
        not exist on screen, which read as the subfolders not existing at all.
        """
        for orientation in ORIENTATIONS:
            child = QTreeWidgetItem([ORIENTATION_LABELS[orientation]])
            child.setToolTip(
                0, f"Only the {orientation}-shaped items of this shelf")
            shelf_item.addChild(child)
            self.item_by_key[oriented_key(base_key, orientation)] = child
        shelf_item.setExpanded(True)

    def _add_custom_folder(self, root, group) -> QTreeWidgetItem:
        """Add a row for one of the user's own folders: a shelf-shaped row carrying
        its group (so the view's folder machinery — breadcrumb, tiles, slideshow —
        treats it like any other folder), editable for an inline rename, and
        collecting the folders dropped onto it."""
        count = len(gallery.rows_under(group))
        item = self._add_shelf(
            root, group.label, group.key, icons.custom_folder_icon(),
            f"{group.label} — {count} item{'s' if count != 1 else ''} "
            "in a folder you made; drop folders here to add them",
        )
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, DROP_KEY_ROLE, group.key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        return item

    def _add_node(self, group, parent_item) -> QTreeWidgetItem:
        # Starred state shows as the row's star icon (the delegate reads it from
        # the group), so the label itself carries no ★ prefix.
        item = QTreeWidgetItem([group.label])
        if gallery.is_renamable(group):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, GROUP_ROLE, group)
        # A workflow / model / LoRA / source-image row wears a lettered chip
        # naming its recipe level, and a media root the glyph its own items wear,
        # so a row's place in the hierarchy reads at a glance rather than by
        # counting indentation; the level joins the tooltip too. The All row and
        # the settings leaves get neither (folder_level returns None).
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
            named = icons.LEVEL_LABELS[level]
            # A media root is named after its own level ("Videos" at the video
            # level), so joining the two would just say it twice.
            item.setToolTip(0, group.label if named == group.label
                            else f"{group.label} · {named}")
        else:
            # A settings leaf is named by a code, so its tooltip is where the
            # prompt and the settings that set it apart from its siblings are
            # read — the row itself stays one short line.
            item.setToolTip(0, _row_tip(group))
        self.item_by_key[group.key] = item
        parent_item.addChild(item)
        for child in gallery.child_groups(group):
            self._add_node(child, item)
        if isinstance(group, gallery.SettingsGroup):
            for row in group.rows:
                self.leaf_by_id[row["prompt_id"]] = item
        return item

    def default_item(self) -> QTreeWidgetItem | None:
        """The folder to land on with no saved target: the first real media folder;
        failing that (only in-flight work so far, no finished folders), the Recents
        shelf, so a first generation stays visible while it runs."""
        root = self._tree.invisibleRootItem()
        skip = (self.recents_item, self.starred_item, self.experiments_item,
                self.requests_item, self.trash_item, *self.custom_items.values())
        for i in range(root.childCount()):
            item = root.child(i)
            if item not in skip:
                return item
        return self.recents_item

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def selected_folder_key(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        if item is self.recents_item:
            return RECENTS_KEY  # so a rebuild keeps the shelf selected
        if item is self.starred_item:
            return STARRED_KEY  # so a rebuild keeps the shelf selected
        if item is self.experiments_item:
            return EXPERIMENTS_KEY  # so a rebuild keeps the shelf selected
        if item is self.requests_item:
            return REQUESTS_KEY  # so a rebuild keeps the shelf selected
        if item is self.trash_item:
            return TRASH_KEY  # so a rebuild keeps the shelf selected
        for base in ORIENTED_SHELF_KEYS:
            for orientation in ORIENTATIONS:
                key = oriented_key(base, orientation)
                if self.item_by_key.get(key) is item:
                    return key  # a shelf's Portrait/Landscape subfolder
        group = item.data(0, GROUP_ROLE)
        return group.key if group else None

    def breadcrumb(self, item) -> str:
        parts = []
        node = item
        while node is not None:
            group = node.data(0, GROUP_ROLE)
            if group is not None:
                parts.append(group.label)
            node = node.parent()
        return "  ›  ".join(reversed(parts))
