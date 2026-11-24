from __future__ import annotations

from typing import NamedTuple, Protocol

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator import gallery, search
from origenerator.gui.gallery_pane import SEARCH_DRAW_LIMIT
from origenerator.gui.gallery_tree import PathStep, path_text
from origenerator.gui.no_wheel import NoWheelDropdown
from origenerator.gui.scope_search_edit import ScopeSearchEdit

_DELAY_MS = 300
MIN_CHARS = 3
_SORTS = (("Recent", search.SORT_RECENT), ("Model / LoRA", search.SORT_MODEL_LORA))
_SEARCH_ALL_TIP = ("Search every item for what you typed, whatever folder is "
                   "open in the TOC")
_SEARCH_ALL_GRAYED_TIP = (f"Type at least {MIN_CHARS} characters in the search "
                          "box, then press this to search every item rather "
                          "than only the folder open in the TOC")


class SearchScope(NamedTuple):
    steps: tuple[PathStep, ...]
    ids: set[str] | None

    @classmethod
    def everything(cls, live_ids) -> SearchScope:
        return cls((PathStep(gallery.ALL_LABEL, None),), live_ids)

    @property
    def path(self) -> str:
        return path_text(self.steps)


class SearchHost(Protocol):
    def search_scope(self) -> SearchScope: ...

    def name_search_on_screen(self, query: str, scope) -> None: ...

    def search_results_drawn(self) -> None: ...

    def hand_pane_back(self) -> None: ...

    def suppress_history(self): ...


def _once_after(pause_ms: int, then, *, owner: QObject) -> QTimer:
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(pause_ms)
    timer.timeout.connect(then)
    return timer


class GallerySearchController(QObject):
    def __init__(self, host: SearchHost, *, parent: QObject, library, toc, pane):
        super().__init__(parent)
        self._host = host
        self._library = library
        self._toc = toc
        self._pane = pane
        self._index = search.GallerySearch()
        self._query = ""
        self._everywhere = False
        self._outcome = search.SearchOutcome((), ())
        self._tiles: list = []
        self._sort = search.SORT_RECENT
        self._collapsed: set[str] = set()
        self._timer = _once_after(_DELAY_MS, self._run_pending, owner=self)

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
        self.field.returnPressed.connect(self._search_everywhere)
        self.search_all = QPushButton("Search all")
        self.search_all.clicked.connect(self._search_everywhere)
        self._gray_search_all(True)
        self.row = QWidget()
        field_row = QHBoxLayout(self.row)
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.setSpacing(GAP_SMALL)
        field_row.addWidget(self.field, 1)
        field_row.addWidget(self.search_all)

        self._count = QLabel("")
        self._count.setObjectName("mutedLabel")
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
    def everywhere(self) -> bool:
        return self._everywhere

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

    def follow_the_folder(self) -> None:
        self._everywhere = False

    def run(self) -> None:
        scope = (SearchScope.everything(self._library.live_ids) if self._everywhere
                 else self._host.search_scope())
        self._outcome = self._index.search(self._query, within=scope.ids)
        self._tiles = [*self._folders_named(), *(search.SearchTile(row=result.row, rows=[result.row])
                                                for result in self._outcome.results)]
        self._host.name_search_on_screen(self._query, scope)
        self._count.setText(self._count_text())
        self.bar.show()
        self._pane.show_search_results(self._tiles, search.SearchTerms(
            sort_mode=self._sort, query=self._query, outcome=self._outcome,
            scope=scope.path, collapsed=self._collapsed,
            on_section_toggled=self._on_section_toggled, on_clear_search=self.field.clear,
        ))
        self._host.search_results_drawn()

    def leave(self, *_args) -> None:
        if not self._query:
            return
        with self._host.suppress_history():
            self.field.clear()

    def clear_state(self) -> None:
        self._query = ""
        self._everywhere = False
        self._outcome = search.SearchOutcome((), ())
        self._tiles = []
        self._timer.stop()
        self.field.set_working(False)
        self.bar.hide()

    def restore(self, query: str, everywhere: bool = False) -> None:
        self.field.blockSignals(True)
        try:
            self.field.setText(query)
        finally:
            self.field.blockSignals(False)
        self.clear_state()
        self._query = query
        self._everywhere = everywhere and bool(query)
        self._gray_search_all(len(query) < MIN_CHARS)

    def _on_text_changed(self, text: str) -> None:
        query = (text or "").strip()
        self._timer.stop()
        self._gray_search_all(len(query) < MIN_CHARS)
        if len(query) < MIN_CHARS:
            if self._query:
                self._exit()
            self._query = ""
            return
        self._query = query
        self._timer.start()
        self.field.set_working(True)

    def _run_pending(self) -> None:
        if not self._query:
            return
        self.run()
        self.field.set_working(False)

    def _search_everywhere(self) -> None:
        if not self._query:
            return
        self._everywhere = True
        self._timer.stop()
        self._run_pending()

    def _gray_search_all(self, grayed: bool) -> None:
        self.search_all.setEnabled(not grayed)
        self.search_all.setToolTip(_SEARCH_ALL_GRAYED_TIP if grayed else _SEARCH_ALL_TIP)

    def _exit(self) -> None:
        self.clear_state()
        self._host.hand_pane_back()

    def _on_sort_changed(self, _index=0) -> None:
        self._sort = self._sort_dropdown.currentData() or search.SORT_RECENT
        if self._query:
            self.run()

    def _folders_named(self) -> list:
        groups = (self._toc.group_for_key(key) for key in self._outcome.folders)
        return [search.SearchTile(row=gallery.rows_under(group)[0], group=group, rows=[])
                for group in groups if group is not None]

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
