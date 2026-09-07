"""The gallery's search: the field, the results bar, and everything between.

One of the gallery's screen concerns, lifted out of the view that used to hold
all of them. What lives here is the whole of a search's life — the debounce and
the widening's longer one, the query and its expansions, the outcome, the tiles
the pane draws and the recipe bands folded shut, the sort and the count line.

What stays with the host is what a search is *of*: which folder the tree has
selected, what rows the gallery is holding, and what the pane and the header do
once results exist. :class:`SearchHost` names each of those, so this controller
can be built and driven without a gallery — and so the gallery cannot quietly
grow a fifteenth way of reaching in.

The field is the one path out of a search: clearing it runs the exit, so there
is one route rather than two (see :meth:`GallerySearchController.leave`).
"""
from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from origenerator import gallery, search
from origenerator.gui.browser_pane import SEARCH_DRAW_LIMIT
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.scope_search_edit import ScopeSearchEdit
from origenerator.gui.search_expander import SearchExpander

# How long the search waits after the last keystroke before asking the local LLM
# to widen the query. Long enough to be a real pause rather than a gap between
# two characters — the table-widened results are already on screen throughout, so
# nothing is being waited *for*; this only decides how often the model is asked.
_EXPAND_DELAY_MS = 700
# How long the field waits after the last keystroke before searching at all. A
# search is cheap but not free — it scores the whole library and rebuilds the
# pane — and running one per character means the results churn under a word
# still being typed, which is unreadable however fast it is.
_DELAY_MS = 300
# Below this many characters nothing is searched. One or two letters match a
# large fraction of any library through sheer stemming, so an as-you-type search
# would answer the first keystroke of every query with most of the gallery.
MIN_CHARS = 3
# The sort orders the results pane offers, as (label, mode) in menu order.
_SORTS = (("Recent", search.SORT_RECENT), ("Model / LoRA", search.SORT_RECIPE))


class SearchHost(Protocol):
    """What a search needs of the gallery around it, and nothing else."""

    def search_scope(self):
        """The selected row's breadcrumb and the generations under it — what
        this query covers, and what the field and the header name it by."""

    def image_config_index(self) -> dict:
        """The index folder keys are derived against, for collapsing several
        hits in one settings folder onto that folder."""

    def group_for_key(self, key: str):
        """The tree's group for a folder key, or ``None`` when the current model
        holds no row for it."""

    def show_search_results(self, tiles, **terms) -> None:
        """Hand the pane the results to draw."""

    def name_search_on_screen(self, query: str, scope: str) -> None:
        """Say in the header that a search is what the pane is showing."""

    def search_results_drawn(self) -> None:
        """Results are up: re-read whatever depends on what the pane holds."""

    def hand_pane_back(self) -> None:
        """The search is over — the pane belongs to the selected folder again."""

    def suppress_history(self):
        """A context manager holding the history still, for a move that is a
        step on the way rather than somewhere the user went."""


class GallerySearchController(QObject):
    """The search field and the results it fills the browser pane with."""

    def __init__(self, host: SearchHost, *, parent: QObject,
                 expander: SearchExpander | None = None):
        super().__init__(parent)
        self._host = host
        self._index = search.GallerySearch()
        self._query = ""            # what the field holds, stripped ("" = not searching)
        self._expansions = None     # the widening in force for that query, if any
        self._outcome = search.SearchOutcome((), ())
        self._tiles: list = []      # its hits as the pane draws them
        self._sort = search.SORT_RECENT
        self._collapsed: set[str] = set()   # recipe bands folded shut
        self._expander = expander or SearchExpander(self)
        self._expander.expanded.connect(self._on_expanded)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DELAY_MS)
        self._timer.timeout.connect(self._run_pending)
        self._expand_timer = QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(_EXPAND_DELAY_MS)
        self._expand_timer.timeout.connect(self._request_expansion)

        # The gallery search. It sits over the tree but no longer narrows it: what
        # it fills is the browser pane, with the matching generations themselves
        # (see :meth:`run`), because a thumbnail is what the user recognizes and a
        # folder name — a short code — is not. Matching is by meaning rather than
        # by letters, so "two women" reaches "a pair of dolls" and "two tall
        # ladies" alike; a model name, a LoRA name and a seed are searchable too.
        # Its counterpart is the find strip below the info pane, which searches
        # *inside* the open tab's prompts.
        self.field = ScopeSearchEdit()
        # Its placeholder names the scope — the whole path down to the selected
        # folder — and is kept current with the tree selection
        # (:meth:`sync_placeholder`); this is only what it says before the first
        # selection lands.
        self.field.set_scope(gallery.ALL_LABEL)
        self.field.setToolTip(
            "Search every generation by what it is of — matching related words, "
            "not just the ones you typed — or by model, LoRA, seed, or a name "
            "you gave one of the folders holding it. The results "
            f"fill the middle pane; nothing is searched under {MIN_CHARS} "
            "characters."
        )
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(self._on_text_changed)

        # How many the query found, and — past what the pane draws at once — that
        # it is showing a slice; beside it, the order the results are laid out in.
        # Recency is one question ("the one I made recently"); model + LoRA is the
        # other ("which recipe was that"), and picking it cuts the results into a
        # labelled band per combination rather than interleaving them.
        self._count = QLabel("")
        self._count.setObjectName("estimateLabel")
        # No-wheel: it rides directly over the scrolling results, and a wheel
        # notch that lands on it must scroll them rather than re-sort them.
        self._sort_combo = NoWheelComboBox()
        for label, mode in _SORTS:
            self._sort_combo.addItem(label, mode)
        self._sort_combo.setToolTip(
            "Order the results: newest first, or banded under a heading per "
            "model + LoRA combination — click a heading to fold its band away"
        )
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self.bar = QWidget()
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._count)
        row.addStretch(1)
        row.addWidget(QLabel("Sort:"))
        row.addWidget(self._sort_combo)
        self.bar.hide()  # shown only while a search is running

    # --- what the gallery asks of a search -----------------------------------

    @property
    def query(self) -> str:
        """The query in force, ``""`` when nothing is being searched."""
        return self._query

    @property
    def index(self) -> search.GallerySearch:
        """The index the gallery refills on every rebuild."""
        return self._index

    def sort(self) -> str:
        """The results order in force, for the session state to remember."""
        return self._sort

    def set_sort(self, mode: str | None) -> None:
        """Restore the remembered results order (ignoring anything unrecognized,
        so a state file from a version that offered a different one still opens)."""
        index = self._sort_combo.findData(mode)
        if index >= 0:
            self._sort_combo.setCurrentIndex(index)  # its signal sets the mode

    def focus_field(self) -> None:
        """Put the caret in the field with whatever it holds selected — where a
        find chord goes when there is no prompt in front of it to search."""
        self.field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.field.selectAll()

    def sync_placeholder(self) -> None:
        """Say in the empty field what a query typed there would search, so the
        scope is visible before there is a header or a result to name it.

        The whole path goes in; the field shows as much of its tail as it is wide
        enough for (:class:`ScopeSearchEdit`)."""
        self.field.set_scope(self._host.search_scope().path)

    def run(self) -> None:
        """Fill the browser pane with what the standing query matches, within the
        folder the tree has selected.

        Takes the pane over from that folder — the tree keeps its selection while
        a search runs, because the selection is the *scope*: picking another
        folder re-asks the question there rather than ending it, and clearing the
        field hands the pane straight back to wherever you had got to.
        """
        scope = self._host.search_scope()
        self._outcome = self._index.search(
            self._query, expansions=self._expansions, within=scope.ids
        )
        self._tiles = self._collapse_to_folders(self._outcome.results)
        self._host.name_search_on_screen(self._query, scope.path)
        self._count.setText(self._count_text())
        self.bar.show()
        self._host.show_search_results(
            self._tiles, sort_mode=self._sort,
            query=self._query, outcome=self._outcome,
            scope=scope.path, collapsed=self._collapsed,
            on_section_toggled=self._on_section_toggled,
        )
        self._host.search_results_drawn()

    def leave(self, *_args) -> None:
        """Clear the field, if a search is running — what navigating away means.

        This is for gestures that go *to* a result: opening a hit's folder, or
        following a link out of one. Picking a folder in the tree is not one of
        them — that re-scopes the search.

        Takes and ignores whatever the caller passes, so it can be wired straight
        to those gestures. Clearing the field is what actually ends the search: its
        ``textChanged`` runs the exit, so there is one path out rather than two.

        Off the history, because the folder the field hands the pane back to is a
        step on the way rather than anywhere the user went: the caller records the
        result it is opening. Recorded, it would sit between the results and that
        result, and Back out of a hit would land on a folder instead of on the
        hits it came from.
        """
        if not self._query:
            return
        with self._host.suppress_history():
            self.field.clear()

    def clear_state(self) -> None:
        """Forget the running query, its results and its bar — the state half of
        leaving a search, with nothing drawn. Split out because a Back onto a stop
        that had no search must clear the same state without redrawing the pane
        twice: the restore fills it itself."""
        self._query = ""
        self._expansions = None
        self._outcome = search.SearchOutcome((), ())
        self._tiles = []
        self._timer.stop()
        self._expand_timer.stop()
        self.bar.hide()

    def restore(self, query: str) -> None:
        """Put the search field back to what it held at a history stop.

        Set without its typing signals: those debounce and re-run, which would
        answer a restore with a search a beat later, over whatever the restore had
        by then moved on to. The expander's cache is consulted so a query that was
        widened comes back widened, and one it never answered comes back anyway.
        """
        self.field.blockSignals(True)
        try:
            self.field.setText(query)
        finally:
            self.field.blockSignals(False)
        self.clear_state()
        self._query = query
        if query:
            self._expansions = self._expander.cached(query)

    # --- the field's own life -------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """A keystroke in the search field: line the search up, don't run it yet.

        Nothing happens under three characters — one or two letters reach a large
        fraction of any library through stemming alone, so searching them would
        answer the first keystroke of every query with most of the gallery. Past
        that the search waits out :data:`_DELAY_MS` of quiet, and the model call
        waits out a longer one, so a word being typed doesn't churn the pane it is
        about to fill.
        """
        query = (text or "").strip()
        self._timer.stop()
        self._expand_timer.stop()
        if len(query) < MIN_CHARS:
            if self._query:
                self._exit()
            self._query = ""
            return
        if query != self._query:
            self._expansions = None  # last query's widening isn't this one's
        self._query = query
        self._timer.start()
        self._expand_timer.start()

    def _run_pending(self) -> None:
        """Typing has paused: run the standing query and draw it."""
        if not self._query:
            return
        # The cache is consulted, never asked: a query the expander has already
        # answered (re-typed, or reached again by backspacing) is smart from the
        # first draw, and one it hasn't waits for _request_expansion.
        self._expansions = self._expander.cached(self._query)
        self.run()

    def _exit(self) -> None:
        """Put the search away and give the pane back to the selected folder."""
        self.clear_state()
        self._host.hand_pane_back()

    def _on_sort_changed(self, _index=0) -> None:
        """Re-lay the results in the newly picked order (a no-op off a search)."""
        self._sort = self._sort_combo.currentData() or search.SORT_RECENT
        if self._query:
            self.run()

    def _request_expansion(self) -> None:
        """Typing has stopped: ask the local LLM to widen this query's words.

        Nothing is awaited — :meth:`_on_expanded` re-runs the search if and when
        an answer lands, and the table-widened results the user is already
        looking at stand if one never does.
        """
        if self._query:
            self._expander.request(self._query)

    def _on_expanded(self, query: str, expansions) -> None:
        """A widened vocabulary came back: re-run the search on it.

        Only for the query still in the field — a slow answer can land after the
        user has typed on, and widening results for a query they are no longer
        running would put items on screen they cannot account for. An empty
        answer (the endpoint down, or nothing to add) changes nothing, so it
        doesn't redraw the pane out from under them either.
        """
        if expansions and query == self._query:
            self._expansions = expansions
            self.run()

    # --- what a result looks like ---------------------------------------------

    def _collapse_to_folders(self, results) -> list:
        """The hits as tiles: a folder wherever one answered with several items.

        Every row in a settings folder shares a prompt and settings and differs
        only by seed, so a prompt match hits all of them — and drawing eight
        near-copies of one picture buries the other places the query reached.
        The folder stands for them instead, and a folder's lone hit stays itself.
        Order is by first hit, so the newest thing found still leads.

        A folder the tree has no row for (a hit whose folder the current model
        doesn't hold) falls back to its own items rather than vanishing.
        """
        image_index = self._host.image_config_index()
        by_folder: dict[str, list] = {}
        for result in results:
            key = gallery.settings_folder_key(result.row, image_index)
            by_folder.setdefault(key, []).append(result.row)
        tiles = []
        for key, rows in by_folder.items():
            group = self._host.group_for_key(key) if len(rows) > 1 else None
            if group is not None:
                tiles.append(search.SearchTile(row=rows[0], group=group, rows=list(rows)))
            else:
                tiles.extend(search.SearchTile(row=row, rows=[row]) for row in rows)
        return tiles

    def _on_section_toggled(self, heading: str, collapsed: bool) -> None:
        """Remember a recipe band's fold state, so a redraw — a rebuild, a landing
        generation, a widening — doesn't spring open the bands you shut."""
        if collapsed:
            self._collapsed.add(heading)
        else:
            self._collapsed.discard(heading)

    def _count_text(self) -> str:
        """How many the query found — and, past what the pane will draw at once,
        that it is showing a slice and what to do about it. A capped search that
        said only "2,000 results" would read as 2,000 tiles you could scroll to.

        Counted in tiles, which is what is on screen: a folder standing for its
        eight seed variants is one result to click, not eight."""
        count = len(self._tiles)
        text = f"{count:,} result{'s' if count != 1 else ''}"
        if count > SEARCH_DRAW_LIMIT:
            text += (f" — showing the newest {SEARCH_DRAW_LIMIT}; "
                     "add a word to narrow it")
        return text
