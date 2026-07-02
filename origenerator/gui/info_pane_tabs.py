"""The gallery's info pane as a tabbed workspace.

Tab 0 is the always-present Inspect view — the gallery builds it and hands it in
here — and the tabs after it are editable per-configuration panels
(:class:`GenerateConfigPanel`) opened by Reuse Parameters or the "+" button. This
owns the config tabs' lifecycle — add, close, rename, session capture/restore, the
one-generation-at-a-time run queue, and the in-flight reporting the Recents shelf
reads — while the Inspect tab stays the gallery's concern. Clicking a config tab's
history-strip thumbnail opens (or reuses) a tab for that generation.

Config tabs need a ComfyUIClient to run; without one (a read-only gallery in a
test) the "+" is hidden and :meth:`open_config` is a no-op, so only Inspect shows.
"""

import json
import time

from PyQt6.QtWidgets import (
    QTabWidget, QToolButton, QInputDialog, QTabBar, QApplication,
)
from PyQt6.QtCore import Qt

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    build_image_config_index, media_type_of_row, settings_signature,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.eliding_tab_bar import ElidingTabBar
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.inflight_card import InFlightItem
from origenerator.job_queue import JobQueue
from origenerator.workflows import WORKFLOW_REGISTRY


class InfoPaneTabs(QTabWidget):
    """A permanent Inspect tab (index 0) over editable config tabs."""

    def __init__(self, client: ComfyUIClient | None, db: Database, inspect_page,
                 parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db
        self._inspect_page = inspect_page
        self._queue = JobQueue(db)  # one generation at a time across the config tabs
        # Install the eliding bar before setTabsClosable: swapping the bar
        # afterwards drops that setting (it doesn't carry to a new bar).
        self.setTabBar(ElidingTabBar())
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self._close_subtab)
        self.tabBarDoubleClicked.connect(self._rename_subtab)
        self._add_btn = QToolButton()
        self._add_btn.setText("+")
        self._add_btn.setToolTip("New configuration")
        self._add_btn.clicked.connect(lambda: self._add_subtab())
        self._add_btn.setVisible(client is not None)  # nothing to run without a client
        self.setCornerWidget(self._add_btn, Qt.Corner.TopRightCorner)
        # Tab 0: the gallery's Inspect page — always present, never closable, so
        # strip its close button (either side, whichever the style draws).
        self.addTab(inspect_page, "Inspect")
        bar = self.tabBar()
        bar.setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        bar.setTabButton(0, QTabBar.ButtonPosition.LeftSide, None)
        # A double-click on a tab's ✕ closes it, then the tabs shift and the
        # completing click lands on the neighbor as a tabBarDoubleClicked; stamp
        # each close so that stray double-click isn't taken for a rename gesture.
        self._last_close_at = float("-inf")

    # --- config tabs -------------------------------------------------------

    def _config_panels(self) -> list[GenerateConfigPanel]:
        """Every open config panel, in tab order (the Inspect page is skipped)."""
        return [
            w for i in range(self.count())
            if isinstance((w := self.widget(i)), GenerateConfigPanel)
        ]

    def _add_subtab(self) -> GenerateConfigPanel | None:
        if self._client is None:
            return None  # no client to run a generation
        panel = GenerateConfigPanel(self._client, self._db, queue=self._queue)
        index = self.addTab(panel, panel.title())
        panel.title_changed.connect(lambda text, p=panel: self._update_title(p, text))
        panel.strip_activated.connect(self._on_strip_activated)
        self.setCurrentIndex(index)
        return panel

    def _update_title(self, panel: GenerateConfigPanel, text: str):
        index = self.indexOf(panel)
        if index >= 0:
            self.setTabText(index, text)

    def _closed_within_double_click(self) -> bool:
        """Was a config tab closed within one double-click of now?

        The completing click of a double-click on a ✕ arrives this close, so a
        rename firing that soon after a close is that stray click, not a gesture.
        """
        interval = QApplication.doubleClickInterval() / 1000  # ms -> s
        return time.monotonic() - self._last_close_at < interval

    def _rename_subtab(self, index: int):
        if index <= 0:
            return  # the Inspect tab isn't renamable
        if self._closed_within_double_click():
            return  # a stray double-click left over from closing a tab, not a rename
        panel = self.widget(index)
        if not isinstance(panel, GenerateConfigPanel):
            return
        name, ok = QInputDialog.getText(
            self, "Rename tab", "Tab name:", text=panel.title()
        )
        if ok and name.strip():
            panel.set_custom_title(name.strip())

    def _discard_subtab(self, index: int):
        """Remove and tear down one config tab (never the Inspect tab)."""
        panel = self.widget(index)
        if not isinstance(panel, GenerateConfigPanel):
            return
        self._queue.cancel(panel)  # drop its slot, advancing the queue if it was running
        self.removeTab(index)
        panel.teardown()
        panel.deleteLater()

    def _close_subtab(self, index: int):
        self._last_close_at = time.monotonic()  # arm the stray-double-click guard
        self._discard_subtab(index)

    def _ids_for_settings(self, key) -> list[str]:
        """Every generation in a settings folder (workflow + signature), newest first."""
        if key is None:
            return []
        workflow_name, signature = key
        rows = self._db.list_generations()  # newest first
        index = build_image_config_index(
            [r for r in rows if media_type_of_row(r) == "image"]
        )
        return [
            row["prompt_id"]
            for row in rows
            if (row.get("workflow_name") or "") == workflow_name
            and settings_signature(workflow_name, row.get("params_json"), index) == signature
        ]

    def _on_strip_activated(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        workflow_name = row.get("workflow_name", "")
        index = build_image_config_index(
            [r for r in self._db.list_generations() if media_type_of_row(r) == "image"]
        )
        row_key = (workflow_name, settings_signature(workflow_name, row.get("params_json"), index))
        active = self.currentWidget()
        if isinstance(active, GenerateConfigPanel) and active.settings_key() == row_key:
            return  # same settings folder as the active tab — don't spawn a duplicate
        params = merge_denormalized(row)
        if params:
            self.open_config(workflow_name, params)

    def open_config(self, workflow_name: str, params: dict) -> GenerateConfigPanel | None:
        """Open (and select) an editable config tab prefilled from a generation.

        A no-op without a client — nothing could run the resulting config.
        """
        panel = self._add_subtab()
        if panel is None:
            return None
        panel.prefill(workflow_name, params)
        # Seed the new tab's strip with its settings folder; it accumulates from there.
        panel.seed_strip(self._ids_for_settings(panel.settings_key()))
        return panel

    def reveal_config(self, panel: GenerateConfigPanel):
        """Bring a config tab forward — landing a Recents-card click on the panel
        running its job (the info pane is always on screen, so this just selects it)."""
        index = self.indexOf(panel)
        if index >= 0:
            self.setCurrentIndex(index)

    def capture_state(self) -> dict:
        """Snapshot every open config tab so the session can be restored next launch.

        Each carries its configuration, any user-set custom title, and the id of its
        in-flight job (if any) — so a tab whose generation is still running when the
        app closes reconnects to it rather than coming back idle. ``current`` is the
        overall active tab (0 is Inspect), so the same tab reopens focused.
        """
        tabs = [
            {
                "config": panel.current_config().to_dict(),
                "title": panel.custom_title(),
                "active_prompt_id": panel.active_prompt_id(),
            }
            for panel in self._config_panels()
        ]
        return {"tabs": tabs, "current": self.currentIndex()}

    def active_prompt_ids(self) -> set[str]:
        """Every in-flight job id across the open config tabs.

        Lets the gallery know which running rows a config tab already owns, so its
        re-roll reconnection doesn't adopt a job a tab is already tracking.
        """
        ids = set()
        for panel in self._config_panels():
            pid = panel.active_prompt_id()
            if pid:
                ids.add(pid)
        return ids

    def in_flight_items(self) -> list[InFlightItem]:
        """A card per in-flight config-tab job — running or waiting its turn in the
        local queue — for the gallery's Recents shelf. Each carries a reveal that
        brings its tab forward, so clicking the card lands on the panel running it.
        """
        items = []
        for panel in self._config_panels():
            desc = panel.in_flight_descriptor()
            if desc is None:
                continue
            items.append(InFlightItem(
                key=desc["key"], caption=desc["caption"], status=desc["status"],
                frame=desc["frame"], reveal=lambda p=panel: self.reveal_config(p),
                media_type=desc["media_type"],
            ))
        return items

    def restore_state(self, state: dict):
        """Rebuild the config tabs from a :meth:`capture_state` snapshot.

        Entries for workflows no longer in the registry are skipped, as is any
        malformed data, so a corrupt or cross-version state file degrades to just
        the Inspect tab rather than failing to launch. A no-op without a client.
        """
        if not isinstance(state, dict) or self._client is None:
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
        while self.count() > 1:  # clear every config tab, leaving only Inspect (0)
            self._discard_subtab(self.count() - 1)
        for snapshot, title, active_prompt_id in restored:
            panel = self._add_subtab()
            panel.restore_config(snapshot)
            panel.seed_strip(self._ids_for_settings(panel.settings_key()))
            if title:
                panel.set_custom_title(title)
            self._reconnect_if_running(panel, active_prompt_id)
        current = state.get("current", 0)
        if isinstance(current, int) and 0 <= current < self.count():
            self.setCurrentIndex(current)

    def _reconnect_if_running(self, panel: GenerateConfigPanel, active_prompt_id):
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
