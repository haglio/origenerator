import json
import time

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTabWidget, QToolButton,
    QInputDialog, QStackedWidget, QLabel, QPushButton, QApplication,
)
from PyQt6.QtCore import Qt

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import settings_signature
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.eliding_tab_bar import ElidingTabBar
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.job_queue import JobQueue
from origenerator.workflows import WORKFLOW_REGISTRY


class GenerateView(QWidget):
    """The Generate tab: closable per-configuration subtabs. Each subtab lays out
    three resizable panes — a strip of every generation in that tab's settings
    folder, the settings form and run controls, and a live preview — so the tab
    row spans all three. Clicking a strip thumbnail opens (or reuses) a subtab
    carrying that generation's settings."""

    def __init__(self, client: ComfyUIClient, db: Database, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._subtabs = QTabWidget()
        # Install the eliding bar before setTabsClosable/setMovable: swapping the
        # bar afterwards drops those settings (they don't carry to a new bar).
        self._subtabs.setTabBar(ElidingTabBar())
        self._subtabs.setTabsClosable(True)
        self._subtabs.setMovable(True)
        self._subtabs.tabCloseRequested.connect(self._close_subtab)
        self._subtabs.tabBarDoubleClicked.connect(self._rename_subtab)
        add_btn = QToolButton()
        add_btn.setText("+")
        add_btn.setToolTip("New configuration")
        add_btn.clicked.connect(lambda: self._add_subtab())
        self._subtabs.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)

        # Stack the tabs over an empty-state placeholder shown when none are open.
        # Each subtab carries its own three-pane splitter (strip, settings,
        # preview), so the tab row spans all three panes.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._subtabs)
        self._stack.addWidget(self._build_empty_state())
        layout.addWidget(self._stack, 1)

        self._queue = JobQueue(db)  # one generation at a time across subtabs
        # A double-click on a tab's ✕ closes it on the first click, then the tabs
        # shift and the completing double-click lands on the neighbor as a
        # tabBarDoubleClicked. This stamps each close so that stray double-click
        # can be told from a genuine rename gesture.
        self._last_close_at = float("-inf")
        self._add_subtab()

    def _build_empty_state(self) -> QWidget:
        self._empty_state = QWidget()
        box = QVBoxLayout(self._empty_state)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message = QLabel(
            "No generation tabs open.\n\n"
            "Open one from the Gallery — select a generation and choose\n"
            "“Reuse Parameters” — or start a blank one:"
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wrap rather than let the longest line set the tab's minimum width,
        # which would keep the window from tiling narrow.
        message.setWordWrap(True)
        box.addWidget(message)
        self._new_tab_btn = QPushButton("New configuration")
        self._new_tab_btn.clicked.connect(lambda: self._add_subtab())
        box.addWidget(self._new_tab_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return self._empty_state

    def _update_empty_state(self):
        empty = self._subtabs.count() == 0
        self._stack.setCurrentWidget(self._empty_state if empty else self._subtabs)

    def _add_subtab(self) -> GenerateConfigPanel:
        panel = GenerateConfigPanel(self._client, self._db, queue=self._queue)
        index = self._subtabs.addTab(panel, panel.title())
        panel.title_changed.connect(lambda text, p=panel: self._update_title(p, text))
        panel.strip_activated.connect(self._on_strip_activated)
        self._subtabs.setCurrentIndex(index)
        self._update_empty_state()
        return panel

    def _update_title(self, panel: GenerateConfigPanel, text: str):
        index = self._subtabs.indexOf(panel)
        if index >= 0:
            self._subtabs.setTabText(index, text)

    def _closed_within_double_click(self) -> bool:
        """Was a subtab closed within one double-click of now?

        The completing click of a double-click on a ✕ arrives this close, so a
        rename firing that soon after a close is that stray click, not a gesture.
        """
        interval = QApplication.doubleClickInterval() / 1000  # ms -> s
        return time.monotonic() - self._last_close_at < interval

    def _rename_subtab(self, index: int):
        if self._closed_within_double_click():
            return  # a stray double-click left over from closing a tab, not a rename
        panel = self._subtabs.widget(index)
        if panel is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename tab", "Tab name:", text=panel.title()
        )
        if ok and name.strip():
            panel.set_custom_title(name.strip())

    def _discard_subtab(self, index: int):
        """Remove and tear down one subtab, without revealing the empty state."""
        panel = self._subtabs.widget(index)
        self._queue.cancel(panel)  # drop its slot, advancing the queue if it was running
        self._subtabs.removeTab(index)
        panel.teardown()
        panel.deleteLater()

    def _close_subtab(self, index: int):
        self._last_close_at = time.monotonic()  # arm the stray-double-click guard
        self._discard_subtab(index)
        self._update_empty_state()  # closing the last tab reveals the empty state

    def _ids_for_settings(self, key) -> list[str]:
        """Every generation in a settings folder (workflow + signature), newest first."""
        if key is None:
            return []
        workflow_name, signature = key
        return [
            row["prompt_id"]
            for row in self._db.list_generations()  # newest first
            if (row.get("workflow_name") or "") == workflow_name
            and settings_signature(row.get("params_json")) == signature
        ]

    def _on_strip_activated(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        workflow_name = row.get("workflow_name", "")
        row_key = (workflow_name, settings_signature(row.get("params_json")))
        active = self._subtabs.currentWidget()
        if active is not None and active.settings_key() == row_key:
            return  # same settings folder as the active tab — don't spawn a duplicate
        params = merge_denormalized(row)
        if params:
            self.open_config(workflow_name, params)

    def open_config(self, workflow_name: str, params: dict) -> GenerateConfigPanel:
        panel = self._add_subtab()
        panel.prefill(workflow_name, params)
        # Seed the new tab's strip with its settings folder; it accumulates from there.
        panel.seed_strip(self._ids_for_settings(panel.settings_key()))
        return panel

    def capture_state(self) -> dict:
        """Snapshot every open subtab so the session can be restored next launch.

        Each tab carries its configuration, any user-set custom title, and the id
        of its in-flight job (if any) — so a tab whose generation is still running
        when the app closes reconnects to it, rather than coming back idle.
        """
        tabs = []
        for i in range(self._subtabs.count()):
            panel = self._subtabs.widget(i)
            tabs.append({
                "config": panel.current_config().to_dict(),
                "title": panel.custom_title(),
                "active_prompt_id": panel.active_prompt_id(),
            })
        return {"tabs": tabs, "current": self._subtabs.currentIndex()}

    def active_prompt_ids(self) -> set[str]:
        """Every in-flight job id across the open tabs.

        Lets the gallery know which running rows a Generate tab already owns, so
        its re-roll reconnection doesn't adopt a job the tab is already tracking.
        """
        ids = set()
        for i in range(self._subtabs.count()):
            pid = self._subtabs.widget(i).active_prompt_id()
            if pid:
                ids.add(pid)
        return ids

    def restore_state(self, state: dict):
        """Rebuild the subtabs from a :meth:`capture_state` snapshot.

        Entries for workflows no longer in the registry are skipped, as is any
        malformed data, so a corrupt or cross-version state file degrades to the
        default tab rather than failing to launch. If nothing restorable remains,
        the default tab created at construction is left as-is.
        """
        if not isinstance(state, dict):
            return
        raw_tabs = state.get("tabs")
        restored = []
        for entry in raw_tabs if isinstance(raw_tabs, list) else []:
            if not isinstance(entry, dict):
                continue
            snapshot = ConfigSnapshot.from_dict(entry.get("config") or {})
            if snapshot.workflow_name not in WORKFLOW_REGISTRY:
                continue
            title = entry.get("title")
            restored.append((
                snapshot,
                title if isinstance(title, str) and title.strip() else None,
                entry.get("active_prompt_id"),
            ))
        if not restored:
            return
        while self._subtabs.count():
            self._discard_subtab(0)
        for snapshot, title, active_prompt_id in restored:
            panel = self._add_subtab()
            panel.restore_config(snapshot)
            panel.seed_strip(self._ids_for_settings(panel.settings_key()))
            if title:
                panel.set_custom_title(title)
            self._reconnect_if_running(panel, active_prompt_id)
        current = state.get("current", 0)
        if isinstance(current, int) and 0 <= current < self._subtabs.count():
            self._subtabs.setCurrentIndex(current)

    def _reconnect_if_running(self, panel, active_prompt_id):
        """Rebind a restored tab to its job if that job is still running.

        The row's stored payload sizes the panel's progress ramp. A job that has
        since finished or gone (reconciled at startup) is no longer 'running', so
        the tab simply comes back idle.
        """
        if not active_prompt_id:
            return
        row = self._db.get_generation(active_prompt_id)
        if not row or row.get("status") not in ("running", "pending"):
            return
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
        try:
            payload = json.loads(row.get("workflow_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        panel.reconnect(active_prompt_id, workflow, payload)
