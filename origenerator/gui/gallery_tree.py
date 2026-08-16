"""Builds and queries the gallery's folder-tree widget — the left TOC pane.

Renders the Recents, Starred, Experiments and Trash shelves atop the media →
workflow → model → LoRA → [source image] → settings folders, and keeps the
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
from origenerator.recovery import RETENTION_DAYS

GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
RECENTS_KEY = "__recents__"   # synthetic tree node listing recently generated items
RECENTS_LABEL = "Recents"     # its row label; a clock is drawn in the caret column
STARRED_KEY = "__starred__"   # synthetic tree node collecting every starred folder
STARRED_LABEL = "Starred"     # its row label; the star is drawn in the caret column
EXPERIMENTS_KEY = "__experiments__"  # synthetic node: the background-experiment home
EXPERIMENTS_LABEL = "Experiments"    # its row label; a flask is drawn in the caret column
TRASH_KEY = "__trash__"   # synthetic node: deleted items still held for recovery
TRASH_LABEL = "Trash"     # its row label; a can is drawn in the caret column


def _prompt_texts(row: dict, params: dict) -> tuple[str, str]:
    """A generation's positive and negative prompt, lowercased for matching.

    Read from the row's own columns first, falling back to the params it ran
    with: the two are written together for a generation this app made, but an
    imported file recovers its prompt from the graph in the file's metadata and
    may end up carrying it in only one of them.
    """
    return tuple(
        str(row.get(key) or params.get(key) or "").lower()
        for key in ("positive_prompt", "negative_prompt")
    )


class GalleryTree:
    """The folder tree: builds it from the gallery model and answers the lookups
    (key→item, prompt→item, breadcrumb, the selected folder's key) the view
    navigates by. The ``FolderTree`` widget itself is owned by the view."""

    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}  # folder key -> its tree row
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}   # prompt_id -> its settings row
        self.recents_item: QTreeWidgetItem | None = None   # the "Recents" shelf row
        self.starred_item: QTreeWidgetItem | None = None   # the "★ Starred" shelf row
        self.experiments_item: QTreeWidgetItem | None = None  # the "Experiments" shelf row
        self.trash_item: QTreeWidgetItem | None = None     # the "Trash" shelf row
        self.custom_items: dict[str, QTreeWidgetItem] = {}  # custom folder key -> its row
        self._filter = ""                       # active filter query, lowercased
        self._pre_filter_expanded: set[str] | None = None  # expansion to restore on clear
        self.seed_matches: dict[str, list[str]] = {}  # leaf key -> prompt_ids the query hit by seed

    def populate(self, tree_model, expanded_keys, *, show_recents: bool,
                 experiment_count: int = 0, trash_count: int = 0, custom_folders=()):
        """Rebuild the tree from ``tree_model``, restoring the folders in
        ``expanded_keys``. ``show_recents`` keeps the Recents shelf up even with no
        folders yet (in-flight work to show); Starred appears only once folders do.
        ``experiment_count`` (unreviewed background experiments) and
        ``trash_count`` (deleted items still recoverable) show in their shelves'
        labels so waiting work is visible from anywhere. ``custom_folders`` are
        the user's own groupings, each getting a row of its own between the
        shelves and the media roots."""
        self._tree.blockSignals(True)
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.recents_item = None
        self.starred_item = None
        self.experiments_item = None
        self.trash_item = None
        self.custom_items = {}
        root = self._tree.invisibleRootItem()
        # Synthetic shelves lead the tree: Recents (in-flight work plus recently
        # finished items) whenever there is anything to show — so a first-ever
        # generation is visible while it runs, before any folder exists — then
        # Starred (bookmarked folders) once folders do, then Experiments and
        # Trash, both always present: one hosts the background experimenter's
        # switch and review queue, the other is where every delete goes, and a
        # bin you can only find once you have something to recover is no use.
        # Each is reachable in one click however the tree is scrolled, and draws
        # its marker in the caret column so its label lines up with the media
        # folders below.
        if show_recents:
            self.recents_item = self._add_shelf(
                root, RECENTS_LABEL, RECENTS_KEY, icons.clock_icon(), "Recently generated"
            )
        if tree_model:
            self.starred_item = self._add_shelf(
                root, STARRED_LABEL, STARRED_KEY, icons.star_icon(filled=True),
                "Your starred folders — drop a folder here to star it"
            )
            # Starring is what Starred does with a dropped folder, so it collects.
            self.starred_item.setData(0, DROP_KEY_ROLE, STARRED_KEY)
        label = EXPERIMENTS_LABEL + (f" ({experiment_count})" if experiment_count else "")
        self.experiments_item = self._add_shelf(
            root, label, EXPERIMENTS_KEY, icons.flask_icon(),
            "Background experiments awaiting your review"
        )
        label = TRASH_LABEL + (f" ({trash_count})" if trash_count else "")
        self.trash_item = self._add_shelf(
            root, label, TRASH_KEY, icons.trash_icon(),
            f"Deleted items — restorable here for {RETENTION_DAYS} days"
        )
        for custom in custom_folders:
            self.custom_items[custom.key] = self._add_custom_folder(root, custom)
        for media in tree_model:
            self._add_node(media, root)
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._tree.blockSignals(False)

    def _add_shelf(self, root, label, key, icon, tooltip) -> QTreeWidgetItem:
        """Add a synthetic shelf row (Recents/Starred) leading the tree, its marker
        drawn in the caret column so its label aligns with the media folders below."""
        item = QTreeWidgetItem([label])
        item.setData(0, BRANCH_ICON_ROLE, icon)  # marker in the caret column
        item.setToolTip(0, tooltip)
        root.addChild(item)
        self.item_by_key[key] = item
        return item

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
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, GROUP_ROLE, group)
        # A workflow/model/LoRA row wears a lettered chip naming its recipe level,
        # so its place in the hierarchy reads at a glance rather than by counting
        # indentation; the level joins the tooltip too. Media roots and settings
        # leaves get neither (folder_level returns None).
        level = gallery.folder_level(group)
        if level is not None:
            item.setIcon(0, icons.level_badge_icon(level))
            item.setToolTip(0, f"{group.label} · {icons.LEVEL_LABELS[level]}")
        else:
            item.setToolTip(0, group.label)
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
                self.trash_item, *self.custom_items.values())
        for i in range(root.childCount()):
            item = root.child(i)
            if item not in skip:
                return item
        return self.recents_item

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def persisted_expanded_keys(self) -> set[str]:
        """The expansion a rebuild should save. While a filter is active that is
        the user's pre-filter set — the branches the filter opened to reveal a
        match are transient and must not stick once the filter clears."""
        if self._filter:
            return set(self._pre_filter_expanded or ())
        return self.expanded_keys()

    def apply_filter(self, query: str) -> None:
        """Narrow the tree to rows matching ``query`` (case-insensitive substring
        over the row label, or a settings leaf's generation seed or prompt text),
        keeping each match's ancestors so its path shows and expanding down to it;
        a matched folder keeps its whole subtree. Seed hits are recorded in
        :attr:`seed_matches` for the view to jump to. An empty query restores
        every row and the expansion the user had before filtering."""
        query = (query or "").strip().lower()
        if not query:
            if self._filter:
                self._restore_from_filter()
            self._filter = ""
            self.seed_matches = {}
            return
        if not self._filter:  # entering a filter: remember the user's expansion
            self._pre_filter_expanded = self.expanded_keys()
        self._filter = query
        self._run_filter()

    def reapply_filter(self) -> None:
        """Re-narrow a freshly rebuilt tree to the active filter — ``populate``
        rebuilds every row un-hidden, so the filter has to run again after it."""
        if self._filter:
            self._run_filter()

    def _run_filter(self) -> None:
        self.seed_matches = {}
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_item(root.child(i), self._filter, ancestor_match=False)

    def _filter_item(self, item, query, *, ancestor_match: bool) -> bool:
        """Hide ``item`` unless it, an ancestor, a descendant, or (for a settings
        leaf) one of its generations' seeds or prompt text matches; expand the path
        down to any descendant match. Returns whether it stays visible."""
        match = ancestor_match or query in item.text(0).lower()
        seed_ids, prompt_match = self._generation_hits(item, query)
        descendant_match = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), query, ancestor_match=match):
                descendant_match = True
        visible = match or descendant_match or bool(seed_ids) or prompt_match
        item.setHidden(not visible)
        if descendant_match:
            item.setExpanded(True)
        if seed_ids:
            self.seed_matches[item.data(0, GROUP_ROLE).key] = seed_ids
        return visible

    def _generation_hits(self, item, query) -> tuple[list[str], bool]:
        """What a settings leaf's own generations match on: the prompt_ids whose
        seed contains ``query``, and whether any of their prompt text does.

        Neither rides on a folder label, so this is the only way the filter can
        reach them. A seed names one specific item, so its hits are collected for
        the view to jump to; the prompt belongs to the whole leaf — it is part of
        the settings every row there shares — so it only decides whether the folder
        stays on screen. The label does lead with the positive prompt, but as a
        60-character headline: the words past it, and the negative prompt entirely,
        are findable here or nowhere.

        One parse of a row's params serves both checks, since scanning every
        generation in the tree happens on each keystroke.
        """
        group = item.data(0, GROUP_ROLE)
        if not isinstance(group, gallery.SettingsGroup):
            return [], False
        hits = []
        prompt_match = False
        for row in group.rows:
            params = gallery.parse_params(row.get("params_json"))
            seeds = (params.get("seed"), params.get("noise_seed"))
            if any(s is not None and query in str(s).lower() for s in seeds):
                hits.append(row["prompt_id"])
            if not prompt_match:
                prompt_match = any(query in text for text in _prompt_texts(row, params))
        return hits, prompt_match

    def _restore_from_filter(self) -> None:
        keys = self._pre_filter_expanded or set()
        for key, item in self.item_by_key.items():
            item.setHidden(False)
            item.setExpanded(key in keys)
        self._pre_filter_expanded = None

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
        if item is self.trash_item:
            return TRASH_KEY  # so a rebuild keeps the shelf selected
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
