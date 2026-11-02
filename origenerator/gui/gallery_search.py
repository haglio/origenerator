from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from origenerator import gallery, search
from origenerator.gui.gallery_pane import SEARCH_DRAW_LIMIT
from origenerator.gui.no_wheel import NoWheelDropdown
from origenerator.gui.scope_search_edit import ScopeSearchEdit
from origenerator.gui.search_expander import SearchExpander

_EXPAND_DELAY_MS = 700
_DELAY_MS = 300
MIN_CHARS = 3
_SORTS = (("Recent", search.SORT_RECENT), ("Model / LoRA", search.SORT_MODEL_LORA))


class SearchHost(Protocol):
    def search_scope(self): ...

    def image_config_index(self) -> dict: ...

    def group_for_key(self, key: str): ...

    def show_search_results(self, tiles, terms: search.SearchTerms) -> None: ...

    def name_search_on_screen(self, query: str, scope) -> None: ...

    def search_results_drawn(self) -> None: ...

    def hand_pane_back(self) -> None: ...

    def suppress_history(self): ...


class GallerySearchController(QObject):
    def __init__(self, host: SearchHost, *, parent: QObject,
                 expander: SearchExpander | None = None):
        super().__init__(parent)
        self._host = host
        self._index = search.GallerySearch()
        self._query = ""
        self._expansions = None
        self._widening_awaited = False
        self._outcome = search.SearchOutcome((), ())
        self._tiles: list = []
        self._sort = search.SORT_RECENT
        self._collapsed: set[str] = set()
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

        self.field = ScopeSearchEdit()
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

        self._count = QLabel("")
        self._count.setObjectName("estimateLabel")
        self._sort_dropdown = NoWheelDropdown()
        for label, mode in _SORTS:
            self._sort_dropdown.addItem(label, mode)
        self._sort_dropdown.setToolTip(
            "Order the results: newest first, or banded under a heading per "
            "model + LoRA combination — click a heading to fold its band away"
        )
        self._sort_dropdown.currentIndexChanged.connect(self._on_sort_changed)
        self.bar = QWidget()
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._count)
        row.addStretch(1)
        row.addWidget(QLabel("Sort:"))
        row.addWidget(self._sort_dropdown)
        self.bar.hide()

    @property
    def query(self) -> str:
        return self._query

    @property
    def index(self) -> search.GallerySearch:
        return self._index

    def sort(self) -> str:
        return self._sort

    def set_sort(self, mode: str | None) -> None:
        index = self._sort_dropdown.findData(search.saved_sort(mode))
        if index >= 0:
            self._sort_dropdown.setCurrentIndex(index)

    def focus_field(self) -> None:
        self.field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.field.selectAll()

    def sync_placeholder(self) -> None:
        self.field.set_scope(self._host.search_scope().path)

    def run(self) -> None:
        scope = self._host.search_scope()
        self._outcome = self._index.search(
            self._query, expansions=self._expansions, within=scope.ids
        )
        self._tiles = self._collapse_to_folders(self._outcome.results)
        self._host.name_search_on_screen(self._query, scope)
        self._count.setText(self._count_text())
        self.bar.show()
        self._host.show_search_results(self._tiles, search.SearchTerms(
            sort_mode=self._sort, query=self._query, outcome=self._outcome,
            scope=scope.path, collapsed=self._collapsed,
            on_section_toggled=self._on_section_toggled,
            still_searching=self._widening_awaited,
        ))
        self._host.search_results_drawn()

    def leave(self, *_args) -> None:
        if not self._query:
            return
        with self._host.suppress_history():
            self.field.clear()

    def clear_state(self) -> None:
        self._query = ""
        self._expansions = None
        self._widening_awaited = False
        self._outcome = search.SearchOutcome((), ())
        self._tiles = []
        self._timer.stop()
        self._expand_timer.stop()
        self.field.set_working(False)
        self.bar.hide()

    def restore(self, query: str) -> None:
        self.field.blockSignals(True)
        try:
            self.field.setText(query)
        finally:
            self.field.blockSignals(False)
        self.clear_state()
        self._query = query
        if query:
            self._expansions = self._expander.cached(query)

    def _on_text_changed(self, text: str) -> None:
        query = (text or "").strip()
        self._timer.stop()
        self._expand_timer.stop()
        if len(query) < MIN_CHARS:
            if self._query:
                self._exit()
            self._query = ""
            return
        if query != self._query:
            self._expansions = None
        self._query = query
        self._widening_awaited = self._index.widens(query) and self._expander.unanswered(query)
        self._timer.start()
        self._expand_timer.start()
        self.field.set_working(True)

    def _run_pending(self) -> None:
        if not self._query:
            return
        self._expansions = self._expander.cached(self._query)
        self.run()
        self.field.set_working(self._widening_awaited)

    def _exit(self) -> None:
        self.clear_state()
        self._host.hand_pane_back()

    def _on_sort_changed(self, _index=0) -> None:
        self._sort = self._sort_dropdown.currentData() or search.SORT_RECENT
        if self._query:
            self.run()

    def _request_expansion(self) -> None:
        if self._widening_awaited:
            self._expander.request(self._query)

    def _on_expanded(self, query: str, expansions) -> None:
        if not self._expander.same_words(query, self._query):
            return
        self._widening_awaited = False
        self.field.set_working(False)
        if expansions or not self._tiles:
            self._expansions = expansions
            self.run()

    def _collapse_to_folders(self, results) -> list:
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
        if collapsed:
            self._collapsed.add(heading)
        else:
            self._collapsed.discard(heading)

    def _count_text(self) -> str:
        count = len(self._tiles)
        text = f"{count:,} result{'s' if count != 1 else ''}"
        if count > SEARCH_DRAW_LIMIT:
            text += (f" — showing the newest {SEARCH_DRAW_LIMIT}; "
                     "add a word to narrow it")
        return text
