from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QTabWidget, QToolButton, QInputDialog,
)
from PyQt6.QtCore import Qt

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_config import (
    ConfigSnapshot, configs_match, merge_denormalized,
)
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.job_queue import JobQueue
from origenerator.workflows import WORKFLOW_REGISTRY


class GenerateView(QWidget):
    """The Generate tab: closable per-configuration subtabs plus a live strip
    of every past generation. Clicking a strip thumbnail opens (or reuses) a
    subtab carrying that generation's settings."""

    def __init__(self, client: ComfyUIClient, db: Database, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._subtabs = QTabWidget()
        self._subtabs.setTabsClosable(True)
        self._subtabs.setMovable(True)
        self._subtabs.tabCloseRequested.connect(self._close_subtab)
        self._subtabs.tabBarDoubleClicked.connect(self._rename_subtab)
        add_btn = QToolButton()
        add_btn.setText("+")
        add_btn.setToolTip("New configuration")
        add_btn.clicked.connect(lambda: self._add_subtab())
        self._subtabs.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)
        layout.addWidget(self._subtabs, 1)

        self._strip = ThumbnailStrip(db)
        self._strip.thumbnail_activated.connect(self._on_strip_activated)
        layout.addWidget(self._strip)

        self._queue = JobQueue(db)  # one generation at a time across subtabs
        self._add_subtab()

    def _add_subtab(self) -> GenerateConfigPanel:
        panel = GenerateConfigPanel(self._client, self._db, queue=self._queue)
        index = self._subtabs.addTab(panel, panel.title())
        panel.title_changed.connect(lambda text, p=panel: self._update_title(p, text))
        panel.generation_completed.connect(self._on_panel_completed)
        self._subtabs.setCurrentIndex(index)
        return panel

    def _update_title(self, panel: GenerateConfigPanel, text: str):
        index = self._subtabs.indexOf(panel)
        if index >= 0:
            self._subtabs.setTabText(index, text)

    def _rename_subtab(self, index: int):
        panel = self._subtabs.widget(index)
        if panel is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename tab", "Tab name:", text=panel.title()
        )
        if ok and name.strip():
            panel.set_custom_title(name.strip())

    def _discard_subtab(self, index: int):
        """Remove and tear down one subtab, without the empty-strip backfill."""
        panel = self._subtabs.widget(index)
        self._queue.cancel(panel)  # drop its slot, advancing the queue if it was running
        self._subtabs.removeTab(index)
        panel.teardown()
        panel.deleteLater()

    def _close_subtab(self, index: int):
        self._discard_subtab(index)
        if self._subtabs.count() == 0:
            # Never leave the tab strip empty: closing the last config resets it.
            self._add_subtab()

    def _on_panel_completed(self, _prompt_id: str):
        self._strip.refresh()

    def _on_strip_activated(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        params = merge_denormalized(row)
        if not params:
            return
        workflow_name = row.get("workflow_name", "")
        active = self._subtabs.currentWidget()
        if active is not None and configs_match(
            active.current_config(), workflow_name, params
        ):
            return  # already editing these settings — don't spawn a duplicate
        self.open_config(workflow_name, params)

    def open_config(self, workflow_name: str, params: dict) -> GenerateConfigPanel:
        panel = self._add_subtab()
        panel.prefill(workflow_name, params)
        return panel

    def capture_state(self) -> dict:
        """Snapshot every open subtab so the session can be restored next launch.

        Each tab carries its configuration plus any user-set custom title, since
        a renamed tab is part of "which tabs I had open".
        """
        tabs = []
        for i in range(self._subtabs.count()):
            panel = self._subtabs.widget(i)
            tabs.append({
                "config": panel.current_config().to_dict(),
                "title": panel.custom_title(),
            })
        return {"tabs": tabs, "current": self._subtabs.currentIndex()}

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
            restored.append(
                (snapshot, title if isinstance(title, str) and title.strip() else None)
            )
        if not restored:
            return
        while self._subtabs.count():
            self._discard_subtab(0)
        for snapshot, title in restored:
            panel = self._add_subtab()
            panel.restore_config(snapshot)
            if title:
                panel.set_custom_title(title)
        current = state.get("current", 0)
        if isinstance(current, int) and 0 <= current < self._subtabs.count():
            self._subtabs.setCurrentIndex(current)

    def submit_replay(self, row: dict, overrides: dict) -> GenerateConfigPanel:
        """Open a fresh subtab and re-run a captured generation in it."""
        panel = self._add_subtab()
        panel.submit_replay(row, overrides)
        return panel
