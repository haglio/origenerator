"""The gallery's info pane as a tabbed workspace of editable generate tabs.

Every tab is the same plain, editable :class:`GenerateConfigPanel` — pick a
workflow and set params — with no special or permanent tab. New tabs fork via the
"+" button or a thumbnail double-click; the first one is created on construction.
The corner's close-all — a tab's own ✕ beside the word "All" — empties the pane in
one click, since a session that has spread across a dozen tabs otherwise costs a
dozen clicks to clear.
This owns every tab's lifecycle — add, close, rename, and session capture/restore
of each tab's configuration.

A tab's Generate doesn't run a job here; it emits :attr:`generate_requested`, which
this relays for the gallery to launch as a re-roll of the config's settings folder.
The gallery owns every in-flight job (a re-roll) and reconnects any left running
after a restart, so the tabs carry no job state.

Clicking a browser thumbnail loads that generation into the current tab (reusing
it for the same settings folder, or forking a new tab for a different one), where
its output shows in the preview, its settings seed the editable form, and a footer
offers the source-image link / animations / Send-to-Evolver for its media type.
Clicking a config tab's history-strip thumbnail opens (or reuses) a tab for that
generation.

Config tabs need a ComfyUIClient to run; without one (a read-only gallery in a
test) the corner buttons are hidden and :meth:`open_config` is a no-op — but a tab
still shows, its form up for inspection with Generate disabled.
"""

import time

from PyQt6.QtWidgets import (
    QTabWidget, QToolButton, QInputDialog, QApplication, QWidget, QHBoxLayout,
    QStyle, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    build_image_config_index, media_type_of_row, rows_in_settings, settings_signature,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.eliding_tab_bar import ElidingTabBar
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.icons import tab_close_icon
from origenerator.workflows import WORKFLOW_REGISTRY


class InfoPaneTabs(QTabWidget):
    """A strip of editable config tabs; each tab's Generate becomes a gallery re-roll."""

    tab_added = pyqtSignal(object)  # a fresh GenerateConfigPanel, for the view to wire
    generate_requested = pyqtSignal(str, dict)  # any tab's Generate: (workflow_name, params)

    def __init__(self, client: ComfyUIClient | None, db: Database, parent=None):
        super().__init__(parent)
        self._client = client
        self._db = db
        # Install the eliding bar before setTabsClosable: swapping the bar
        # afterwards drops that setting (it doesn't carry to a new bar).
        self.setTabBar(ElidingTabBar())
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self._close_subtab)
        self.tabBarDoubleClicked.connect(self._rename_subtab)
        self._add_btn = self._tab_row_button("+", "New configuration")
        self._add_btn.clicked.connect(lambda: self._add_subtab())
        self._close_all_btn = self._tab_row_button("All", "Close all configurations")
        # The tabs' own close mark, at the tabs' own size, rather than a ✕ typed
        # into the label: one control that closes tabs, spelled one way.
        indicator = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
        self._close_all_btn.setIcon(tab_close_icon())
        self._close_all_btn.setIconSize(QSize(indicator, indicator))
        self._close_all_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._close_all_btn.clicked.connect(self.close_all_subtabs)
        # Both buttons share a row that opens the tab strip: "+" leftmost, then
        # close-all, then the tabs. They lead the row rather than trailing it, so
        # the two controls are always in the same place however many tabs are open
        # and however wide they get.
        self._corner = QWidget()
        corner_row = QHBoxLayout(self._corner)
        # The same gap after close-all as between the two buttons, so the first
        # tab isn't jammed against it while they sit spaced from each other.
        corner_row.setContentsMargins(0, 0, 8, 0)
        # A gap of bare strip between them: both are flat and share the row's
        # background, so the seam is invisible but unclickable — a miss on the "+"
        # a user hits constantly lands on nothing rather than emptying the pane.
        corner_row.setSpacing(8)
        corner_row.addWidget(self._add_btn)
        corner_row.addWidget(self._close_all_btn)
        self._corner.setVisible(client is not None)  # nothing to run without a client
        self.setCornerWidget(self._corner, Qt.Corner.TopLeftCorner)
        # A double-click on a tab's ✕ closes it, then the tabs shift and the
        # completing click lands on the neighbor as a tabBarDoubleClicked; stamp
        # each close so that stray double-click isn't taken for a rename gesture.
        self._last_close_at = float("-inf")
        self._add_subtab()  # start with one editable tab

    # --- the two buttons standing in the tab row ----------------------------

    def _tab_row_button(self, text: str, tooltip: str) -> QToolButton:
        """A button that belongs to the tab strip: flat, tab-coloured, tab-tall.

        Styled as ``#tabBarButton`` (see :func:`build_stylesheet`) so it reads as
        part of the row rather than a little toolbar bolted onto it.
        """
        button = QToolButton()
        button.setObjectName("tabBarButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Fill the row's height rather than sit centred in it: a tab runs the full
        # height of the strip, and these stand alongside tabs.
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return button

    def _place_tab_row_buttons(self):
        """Hold the button row to exactly the tab row's height.

        Qt lays a corner widget out at the left edge with the tabs starting after
        it — the placement this wants — but it centres the widget in the row using
        the height its layout *asks* for, which is what left these buttons hanging
        below the strip into the pane underneath. So the ask itself is raised past
        the bar's height: the buttons fill the row rather than floating in it.
        """
        row_height = self.tabBar().sizeHint().height()
        for button in (self._add_btn, self._close_all_btn):
            button.setMinimumHeight(row_height)
        # Two pixels taller than the row, because Qt centres the corner using a
        # height it measures a little short of the bar's and the buttons ended up
        # sitting a pixel above the tabs. Overshooting and letting the ends clip
        # covers the row exactly, and needs no second guess at Qt's arithmetic.
        self._corner.setFixedHeight(row_height + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_tab_row_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_tab_row_buttons()

    # --- config tabs -------------------------------------------------------

    def _config_panels(self) -> list[GenerateConfigPanel]:
        """Every open config panel, in tab order."""
        return [
            w for i in range(self.count())
            if isinstance((w := self.widget(i)), GenerateConfigPanel)
        ]

    def current_config_panel(self) -> GenerateConfigPanel | None:
        """The config panel of the tab currently in front, or ``None``."""
        widget = self.currentWidget()
        return widget if isinstance(widget, GenerateConfigPanel) else None

    def _add_subtab(self) -> GenerateConfigPanel:
        """Build, add and select a fresh editable config tab.

        Works even without a client: the tab shows for inspection, its Generate
        disabled. The tab's strip / source-link / animation signals are wired so a
        click in any of them reaches the gallery.
        """
        panel = GenerateConfigPanel(self._client, self._db)
        index = self.addTab(panel, panel.title())
        panel.title_changed.connect(lambda text, p=panel: self._update_title(p, text))
        panel.generate_requested.connect(self.generate_requested)  # relay every tab's Generate
        panel.strip_activated.connect(self._on_strip_activated)
        self.setCurrentIndex(index)
        self.tab_added.emit(panel)  # let the view wire its source/animation links
        return panel

    def _update_title(self, panel: GenerateConfigPanel, text: str):
        index = self.indexOf(panel)
        if index >= 0:
            self.setTabText(index, text)
            self._place_tab_row_buttons()  # a retitled tab is a differently wide one

    def _closed_within_double_click(self) -> bool:
        """Was a config tab closed within one double-click of now?

        The completing click of a double-click on a ✕ arrives this close, so a
        rename firing that soon after a close is that stray click, not a gesture.
        """
        interval = QApplication.doubleClickInterval() / 1000  # ms -> s
        return time.monotonic() - self._last_close_at < interval

    def _rename_subtab(self, index: int):
        if index < 0:
            return
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
        """Remove and tear down one config tab."""
        panel = self.widget(index)
        if not isinstance(panel, GenerateConfigPanel):
            return
        self.removeTab(index)
        panel.teardown()
        panel.deleteLater()

    def _close_subtab(self, index: int):
        self._last_close_at = time.monotonic()  # arm the stray-double-click guard
        self._discard_subtab(index)

    def close_all_subtabs(self):
        """Close every open config tab at once, leaving the pane empty.

        The same end state as clicking each tab's ✕ in turn — an empty pane has
        always been reachable that way, and every caller here already copes with
        no tab in front — but at one click rather than one per tab. Walking from
        the last index down keeps each index valid as the tabs below it shift.
        """
        for index in range(self.count() - 1, -1, -1):
            self._discard_subtab(index)

    def _sync_close_all(self):
        """Grey out close-all when the pane is already empty."""
        self._close_all_btn.setEnabled(self.count() > 0)

    def tabInserted(self, index: int):  # Qt hook: every add path lands here
        super().tabInserted(index)
        self._sync_close_all()
        self._place_tab_row_buttons()  # the row just got wider

    def tabRemoved(self, index: int):  # Qt hook: every close path lands here
        super().tabRemoved(index)
        self._sync_close_all()
        self._place_tab_row_buttons()  # ...and narrower

    def _ids_for_settings(self, key) -> list[str]:
        """Every generation in a settings folder (workflow + signature), newest first."""
        rows = self._db.list_generations()  # newest first
        index = build_image_config_index(
            [r for r in rows if media_type_of_row(r) == "image"]
        )
        return [row["prompt_id"] for row in rows_in_settings(rows, key, index)]

    def _row_settings_key(self, row: dict):
        """The settings folder (workflow + signature) a stored row lands in."""
        workflow_name = row.get("workflow_name", "")
        index = build_image_config_index(
            [r for r in self._db.list_generations() if media_type_of_row(r) == "image"]
        )
        return workflow_name, settings_signature(workflow_name, row.get("params_json"), index,
                                                 workflow_version=row.get("workflow_version"))

    def _on_strip_activated(self, prompt_id: str):
        self.reveal_config(prompt_id)

    def reveal_config(self, prompt_id: str):
        """Bring a generation's settings forward as an editable tab.

        A tab already on that settings folder is selected rather than duplicated —
        the pane spreads across tabs by folder, so a second one for the same
        settings would be the same tab twice. Otherwise a fresh tab is opened,
        prefilled from the generation.

        This is where a click lands on a config tab's history strip and on a row
        of the generation queue: both name a generation and mean "show me its
        settings". A no-op for a generation the database no longer has.
        """
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        row_key = self._row_settings_key(row)
        existing = next(
            (p for p in self._config_panels() if p.settings_key() == row_key), None
        )
        if existing is not None:
            self.setCurrentWidget(existing)
            return
        params = merge_denormalized(row)
        if params:
            self.open_config(row.get("workflow_name", ""), params)

    def open_config(self, workflow_name: str, params: dict) -> GenerateConfigPanel | None:
        """Open (and select) an editable config tab prefilled from a generation.

        A no-op without a client — nothing could run the resulting config.
        """
        if self._client is None:
            return None
        panel = self._add_subtab()
        panel.prefill(workflow_name, params)
        # Seed the new tab's strip with its settings folder; it accumulates from there.
        panel.seed_strip(self._ids_for_settings(panel.settings_key()))
        return panel

    # --- loading the browser selection into a tab --------------------------

    def load_selection(self, row: dict, image_rows: list[dict]):
        """Show a browsed generation in a tab: reuse the current tab when it's
        blank or already on that settings folder, else fork a fresh tab.

        A blank/unused tab (nothing displayed yet) or one already on the clicked
        row's folder is replaced in place; a tab showing a different folder is left
        alone and a new tab opened, so browsing distinct generations spreads across
        tabs rather than clobbering an edited one.
        """
        key = self._row_settings_key(row)
        cur = self.current_config_panel()
        if cur is not None and (cur._displayed_row is None or cur.settings_key() == key):
            target = cur
        else:
            target = self._add_subtab()
        target.show_saved_generation(row, image_rows)
        self.setCurrentWidget(target)

    def show_result_in_current_tab(self, row: dict, image_rows: list[dict]):
        """Load a just-finished generation into the front tab, replacing its live
        preview with the saved output and footer.

        The tab in front is the one whose Generate launched this re-roll, so its
        result lands right there — it ends showing the finished image/video, not the
        idle placeholder. The form is left as the user left it (they may have kept
        typing the next prompt while it ran), so only the preview and footer update.
        A no-op if every tab has been closed."""
        panel = self.current_config_panel()
        if panel is not None:
            panel.show_completed_result(row, image_rows)

    def show_selection_preview(self, preview, prompt_id: str):
        """Point the current tab's preview at ``preview`` (a resolved
        ``(path, media_type)``, or ``None``) without touching its form or the tab
        set — the light-touch update a suppressed poll/rebuild re-selection makes.

        ``prompt_id`` is the shown generation, so its preview can still be dragged
        onto a combine slot after a Back/Forward that never re-seeded the form."""
        panel = self.current_config_panel()
        if panel is None:
            return
        if preview is None:
            panel._preview.clear()  # nothing to show disarms the drag itself
        else:
            panel._preview.show_media(*preview)
            panel._preview.set_draggable_id(prompt_id)

    def show_reroll_frame(self, frame: bytes | None, note: str | None = None):
        """Mirror a running re-roll's live frame into the current tab's preview —
        or a 'waiting' note when no frame has arrived yet, never the idle
        placeholder. The note is marked live, so double-clicking the pane opens
        the run fullscreen even before its first frame streams.

        ``note`` replaces the generic wait when something more useful can be said —
        how much of ComfyUI's queue is in front of this run — so a pane that sits
        unchanged for minutes reads as a queue rather than a hang."""
        panel = self.current_config_panel()
        if panel is None:
            return
        if frame:
            panel._preview.show_frame(frame)
        else:
            panel._preview.show_message(note or "Waiting for preview…", live=True)

    def clear_current_preview(self):
        """Empty the current tab's preview (a re-roll ended with nothing to show,
        or the selection was deleted)."""
        panel = self.current_config_panel()
        if panel is not None:
            panel._preview.clear()

    def release_media(self, paths):
        """Let every tab go of any of ``paths`` it's showing — files about to be
        moved or deleted.

        Every tab, not just the one in front: browsing generation after
        generation spreads them across tabs, and a tab out of sight holds its
        video's file open exactly as firmly as the front one does.
        """
        for panel in self._config_panels():
            panel._preview.release_media(paths)

    def capture_state(self) -> dict:
        """Snapshot every open tab so the session can be restored next launch.

        Each carries its configuration, any user-set custom title, and the runs its
        own Generate started; ``current`` is the active tab, so the same tab
        reopens focused. The gallery reconnects still-running re-rolls itself —
        the recorded runs are only how a tab knows which of them are *its*, so its
        Cancel and progress fill come back on the right tab after a restart.
        """
        tabs = [
            {
                "config": panel.current_config().to_dict(),
                "title": panel.custom_title(),
                "launched_runs": panel.launched_runs(),
            }
            for panel in self._config_panels()
        ]
        return {"tabs": tabs, "current": self.currentIndex()}

    def restore_state(self, state: dict):
        """Rebuild the tabs from a :meth:`capture_state` snapshot.

        Entries for workflows no longer in the registry are skipped, as is any
        malformed data, so a corrupt or cross-version state file degrades to the
        initial single tab rather than failing to launch. A no-op without a client.
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
            launched = entry.get("launched_runs")
            restored.append((
                snapshot,
                title if isinstance(title, str) and title.strip() else None,
                [r for r in launched if isinstance(r, str) and r]
                if isinstance(launched, list) else [],
            ))
        if not restored:
            return  # keep the initial tab rather than leaving no tabs at all
        self.close_all_subtabs()  # clear every tab before rebuilding from the snapshot
        for snapshot, title, launched in restored:
            panel = self._add_subtab()
            panel.restore_config(snapshot)
            panel.seed_strip(self._ids_for_settings(panel.settings_key()))
            if title:
                panel.set_custom_title(title)
            # Runs this tab started and the app was closed on: the gallery
            # reconnects them, and this is how the tab knows they are its own.
            for origin in launched:
                panel.note_launched(origin)
        current = state.get("current", 0)
        if isinstance(current, int) and 0 <= current < self.count():
            self.setCurrentIndex(current)
