from __future__ import annotations

import time
from dataclasses import replace
from typing import NamedTuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMenu, QTabWidget

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    build_image_config_index,
    media_type_of_row,
    settings_signature,
)
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui.copy_names import offer_copy_names
from origenerator.gui.eliding_tab_bar import MARK_CANVAS, ElidingTabBar, tab_mark
from origenerator.gui.generate_tab import GenerateTab
from origenerator.gui.how_many import HOW_MANY
from origenerator.item_names import ItemNames
from origenerator.library_views import NO_VIEWS, LibraryViews, TabViews
from origenerator.media import MediaType
from origenerator.workflows import workflow_named


class SavedTab(NamedTuple):
    config: ConfigSnapshot
    launched_runs: list[str]
    layout: dict


def parse_tabs_state(state) -> tuple[list[SavedTab], int]:
    if not isinstance(state, dict):
        return [], 0
    raw_tabs = state.get("tabs")
    restored = []
    for entry in raw_tabs if isinstance(raw_tabs, list) else []:
        if not isinstance(entry, dict):
            continue
        snapshot = ConfigSnapshot.from_dict(entry.get("config") or {})
        if workflow_named(snapshot.workflow_name) is None:
            continue
        launched = entry.get("launched_runs")
        layout = entry.get("layout")
        restored.append(SavedTab(
            snapshot,
            [run for run in launched if isinstance(run, str) and run]
            if isinstance(launched, list) else [],
            layout if isinstance(layout, dict) else {},
        ))
    current = state.get("current", 0)
    return restored, current if isinstance(current, int) else 0


class GeneratePane(QTabWidget):
    tab_added = pyqtSignal(object)
    generate_requested = pyqtSignal(str, list)
    turn_generate_requested = pyqtSignal(object, str, dict, dict)
    modify_batch_requested = pyqtSignal(str, str, dict)
    folder_requested = pyqtSignal(str)

    def __init__(self, client: ComfyUIClient | None, db: Database,
                 *, fun_time=None, views: TabViews = NO_VIEWS):
        super().__init__()
        self._client = client
        self._fun_time = fun_time
        self.currentChanged.connect(self._front_tab_relayout)
        self._db = db
        self._views = replace(views, library=LibraryViews(db),
                              names=views.names or ItemNames(db))
        # Qt drops setTabsClosable when the bar is swapped afterwards.
        self.setTabBar(ElidingTabBar())
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setIconSize(MARK_CANVAS)
        self.tabCloseRequested.connect(self._close_subtab)
        self.tabBarDoubleClicked.connect(self._pin_subtab)
        bar = self.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._open_tab_menu)
        bar.tabMoved.connect(lambda _from, _to: self._sync_preview_tab())
        self._preview_tab: GenerateTab | None = None
        self._last_close_at = float("-inf")
        self._how_many = HOW_MANY[0]
        self._request_auto_generate = False
        self._add_subtab()

    def _front_tab_relayout(self, _index: int = -1) -> None:
        tab = self.currentWidget()
        refresh = getattr(tab, "refresh_media_layout", None)
        if callable(refresh):
            refresh()

    def become_hosted(self, session) -> None:
        self._fun_time = session
        for tab in self.generate_tabs():
            tab.become_hosted(session)

    def become_standalone(self) -> None:
        self._fun_time = None
        for tab in self.generate_tabs():
            tab.become_standalone()

    def note_in_flight(self, items: list) -> None:
        readings = {item.key: item.reading for item in items}
        for tab in self.generate_tabs():
            tab.note_in_flight(readings)

    def generate_tabs(self) -> list[GenerateTab]:
        return [
            w for i in range(self.count())
            if isinstance((w := self.widget(i)), GenerateTab)
        ]

    def how_many(self) -> int:
        return self._how_many

    def set_how_many(self, count: int) -> None:
        self._how_many = count
        for tab in self.generate_tabs():
            tab.set_how_many(count)

    def request_auto_generate(self) -> bool:
        return self._request_auto_generate

    def set_request_auto_generate(self, on: bool) -> None:
        self._request_auto_generate = on
        for tab in self.generate_tabs():
            tab.set_request_auto_generate(on)

    def current_generate_tab(self) -> GenerateTab | None:
        widget = self.currentWidget()
        return widget if isinstance(widget, GenerateTab) else None

    def _add_subtab(self, *, preview: bool = False) -> GenerateTab:
        tab = GenerateTab(self._client, self._db, fun_time=self._fun_time, views=self._views)
        index = self.addTab(tab, tab_mark(tab.tab_icon()), tab.title())
        tab.title_changed.connect(lambda _text, p=tab: self._update_tab(p))
        tab.displayed_changed.connect(lambda p=tab: self._close_if_a_second_copy(p))
        tab.user_edited.connect(lambda p=tab: self._pin_tab(p))
        tab.set_how_many(self._how_many)
        tab.how_many_chosen.connect(self.set_how_many)
        tab.set_request_auto_generate(self._request_auto_generate)
        tab.request_auto_generate_chosen.connect(self.set_request_auto_generate)
        tab.generate_requested.connect(
            lambda name, batch, p=tab: self._on_tab_generate(p, name, batch)
        )
        tab.modify_batch_requested.connect(
            lambda key, name, params, p=tab: self._on_tab_changes(p, key, name, params)
        )
        tab.turn_generate_requested.connect(
            lambda name, params, asked, p=tab: self._on_turn_generate(p, name, params, asked))
        self.setCurrentIndex(index)
        if preview:
            self._set_preview_tab(tab)
        self.tab_added.emit(tab)
        return tab

    def _update_tab(self, tab: GenerateTab):
        index = self.indexOf(tab)
        if index >= 0:
            self.setTabText(index, tab.title())
            self.setTabIcon(index, tab_mark(tab.tab_icon()))
        self._sync_preview_tab()

    def _closed_within_double_click(self) -> bool:
        interval = QApplication.doubleClickInterval() / 1000
        return time.monotonic() - self._last_close_at < interval

    def _pin_subtab(self, index: int):
        if index < 0:
            return
        if self._closed_within_double_click():
            return
        tab = self.widget(index)
        if isinstance(tab, GenerateTab):
            self._pin_tab(tab)

    def _discard_subtab(self, index: int):
        tab = self.widget(index)
        if not isinstance(tab, GenerateTab):
            return
        if tab is self._preview_tab:
            self._preview_tab = None
        self.removeTab(index)
        tab.deleteLater()

    def _close_subtab(self, index: int):
        self._last_close_at = time.monotonic()
        self._discard_subtab(index)
        self._keep_a_tab_open()

    def _keep_a_tab_open(self):
        if self.count() == 0:
            self._add_subtab()

    def _discard_all_subtabs(self):
        for index in range(self.count() - 1, -1, -1):
            self._discard_subtab(index)

    def _close_other_subtabs(self, index: int):
        keeper = self.widget(index)
        for i in range(self.count() - 1, -1, -1):
            if self.widget(i) is not keeper:
                self._discard_subtab(i)

    def _close_subtabs_to_the_right(self, index: int):
        for i in range(self.count() - 1, index, -1):
            self._discard_subtab(i)

    def _close_all_subtabs(self):
        self._last_close_at = time.monotonic()
        self._discard_all_subtabs()
        self._keep_a_tab_open()

    def _tab_menu(self, index: int) -> QMenu:
        menu = QMenu(self)
        tab = self.widget(index)
        if isinstance(tab, GenerateTab):
            folder = tab.settings_folder_key()
            if folder is not None:
                menu.addAction("Go to folder").triggered.connect(
                    lambda: self.folder_requested.emit(folder)
                )
            offer_copy_names(menu, [tab.name()])
        if self.count() > 1:
            if not menu.isEmpty():
                menu.addSeparator()
            menu.addAction("Close others").triggered.connect(
                lambda: self._close_other_subtabs(index)
            )
        if index < self.count() - 1:
            menu.addAction("Close to the right").triggered.connect(
                lambda: self._close_subtabs_to_the_right(index)
            )
        if self.count() > 1:
            menu.addAction("Close all").triggered.connect(self._close_all_subtabs)
        return menu

    def _open_tab_menu(self, pos):
        index = self.tabBar().tabAt(pos)
        if index < 0:
            return
        menu = self._tab_menu(index)
        if menu.actions():
            menu.exec(self.tabBar().mapToGlobal(pos))

    def _set_preview_tab(self, tab: GenerateTab | None):
        self._preview_tab = tab
        self._sync_preview_tab()

    def _italic_tab(self) -> GenerateTab | None:
        if self._preview_tab is not None:
            return self._preview_tab
        return next((p for p in self.generate_tabs() if p.is_blank()), None)

    def _sync_preview_tab(self):
        tab = self._italic_tab()
        self.tabBar().set_preview_index(self.indexOf(tab) if tab is not None else -1)

    def _pin_tab(self, tab):
        if self._preview_tab is tab:
            self._set_preview_tab(None)

    def _landing_tab(self) -> GenerateTab:
        cur = self.current_generate_tab()
        blank = cur if cur is not None and cur.is_blank() else next(
            (p for p in self.generate_tabs() if p.is_blank()), None
        )
        if blank is not None:
            self._set_preview_tab(blank)
            return blank
        if self._preview_tab is not None:
            return self._preview_tab
        return self._add_subtab(preview=True)

    def pin_current_tab(self):
        self._pin_tab(self.currentWidget())

    def pin_tab(self, tab):
        self._pin_tab(tab)

    def _on_tab_generate(self, tab, workflow_name: str, batch: list[dict]):
        self._pin_tab(tab)
        self.generate_requested.emit(workflow_name, batch)

    def _on_turn_generate(self, tab, workflow_name: str, params: dict, asked: dict):
        self._pin_tab(tab)
        self.turn_generate_requested.emit(tab, workflow_name, params, asked)

    def _on_tab_changes(self, tab, folder_key: str, workflow_name: str,
                           params: dict):
        self._pin_tab(tab)
        self.modify_batch_requested.emit(folder_key, workflow_name, params)

    def tabInserted(self, index: int):
        super().tabInserted(index)
        self._sync_preview_tab()

    def tabRemoved(self, index: int):
        super().tabRemoved(index)
        self._sync_preview_tab()

    @staticmethod
    def _row_settings_key(row: dict, image_index: dict):
        workflow_name = row.get("workflow_name", "")
        return workflow_name, settings_signature(workflow_name, row.get("params_json"),
                                                 image_index,
                                                 workflow_version=row.get("workflow_version"))

    def open_config(self, workflow_name: str, params: dict) -> GenerateTab | None:
        if self._client is None:
            return None
        tab = self._landing_tab()
        tab.prefill(workflow_name, params)
        self.setCurrentWidget(tab)
        return tab

    def open_modify_batch(self, folder_key: str, label: str, workflow_name: str,
                          params: dict, thumbnails: list) -> GenerateTab | None:
        if self._client is None:
            return None
        tab = self._landing_tab()
        tab.open_modify_batch(folder_key, label, workflow_name, params, thumbnails)
        self._pin_tab(tab)
        self.setCurrentWidget(tab)
        return tab

    def tab_showing(self, prompt_id: str, *, besides: GenerateTab | None = None,
                    ) -> GenerateTab | None:
        return next((tab for tab in self.generate_tabs()
                     if tab is not besides
                     and (tab.displayed_row() or {}).get("prompt_id") == prompt_id), None)

    def _close_if_a_second_copy(self, tab: GenerateTab) -> None:
        shown = (tab.displayed_row() or {}).get("prompt_id")
        first = self.tab_showing(shown, besides=tab) if shown else None
        if first is None:
            return
        was_in_front = self.currentWidget() is tab
        self._discard_subtab(self.indexOf(tab))
        if was_in_front:
            self.setCurrentWidget(first)

    def load_selection(self, row: dict, image_rows: list[dict]):
        target = (self.tab_showing(row["prompt_id"])
                  or self._tab_for_the_same_folder(row, image_rows)
                  or self._landing_tab())
        target.show_saved_generation(row, image_rows)
        self.setCurrentWidget(target)

    def _tab_for_the_same_folder(self, row: dict, image_rows: list[dict]) -> GenerateTab | None:
        image_index = build_image_config_index(
            [r for r in image_rows if media_type_of_row(r) == MediaType.IMAGE])
        cur = self.current_generate_tab()
        if (cur is not None and not cur.is_blank()
                and cur.workflow_and_signature(image_index)
                == self._row_settings_key(row, image_index)):
            return cur
        return None

    def tab_that_launched(self, origin: str | None):
        if not origin:
            return None
        return next((tab for tab in self.generate_tabs()
                     if origin in tab.launched_runs()), None)

    def watchers_of(self, key: str) -> list[GenerateTab]:
        return [tab for tab in self.generate_tabs()
                if tab.watched_key() == key]

    def tab_watching(self, key: str) -> GenerateTab | None:
        watching = self.watchers_of(key)
        return watching[0] if watching else None

    def landing_tab(self) -> GenerateTab:
        return self._landing_tab()

    def refresh_displayed(self, row: dict, image_rows: list[dict]):
        for tab in self.generate_tabs():
            tab.refresh_displayed(row, image_rows)

    def reread_names(self):
        for tab in self.generate_tabs():
            self.setTabText(self.indexOf(tab), tab.title())
            tab.reread_name()

    def reconcile_previews(self, live_ids):
        for tab in self.generate_tabs():
            tab.reconcile_preview(live_ids)

    def reread_folder_buttons(self):
        for tab in self.generate_tabs():
            tab.reread_folder_buttons()

    def release_media(self, paths):
        for tab in self.generate_tabs():
            tab.release_media(paths)

    def capture_state(self) -> dict:
        tabs = [
            {
                "config": tab.current_config().to_dict(),
                "launched_runs": tab.launched_runs(),
                "layout": tab.saved_layout(),
            }
            for tab in self.generate_tabs()
        ]
        return {"tabs": tabs, "current": self.currentIndex()}

    def restore_state(self, state: dict):
        if self._client is None:
            return
        restored, current = parse_tabs_state(state)
        if not restored:
            return
        self._discard_all_subtabs()
        for snapshot, launched, layout in restored:
            tab = self._add_subtab()
            tab.restore_config(snapshot)
            if self.indexOf(tab) < 0:
                continue
            tab.restore_layout(layout)
            for origin in launched:
                tab.note_launched(origin)
        if 0 <= current < self.count():
            self.setCurrentIndex(current)
