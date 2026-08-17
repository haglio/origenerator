"""The gallery's info pane as a tabbed workspace of editable generate tabs.

Every tab is the same plain, editable :class:`GenerateConfigPanel` — pick a
workflow and set params — with no special or permanent tab. The pane always holds
at least one: closing the last tab opens a fresh blank one in its place, so the
resting state is a whole generate form waiting on a workflow rather than an empty
black rectangle. That is why there is no "+" — a tab is always there — and no
close-all; a tab's right-click menu closes the others, or everything to its
right, and tabs drag along the row to reorder.

Tabs open the way an IDE opens files, so browsing doesn't leave a row of them
behind. A single-clicked generation lands in the *preview* tab, drawn in italic:
the next single click replaces it. A double-click pins that tab upright, and the
click after it opens a new preview tab beside it.

This owns every tab's lifecycle — add, close, rename, and session capture/restore
of each tab's configuration.

A tab's Generate doesn't run a job here; it emits :attr:`generate_requested`, which
this relays for the gallery to launch as a re-roll of the config's settings folder.
The gallery owns every in-flight job (a re-roll) and reconnects any left running
after a restart, so the tabs carry no job state.

Clicking a browser thumbnail loads that generation into a tab (see
:meth:`load_selection`), where its output shows in the preview, its settings seed
the editable form, and a footer offers the source-image link / animations /
Send-to-Evolver for its media type. Clicking a config tab's history-strip
thumbnail opens (or reuses) a tab for that generation.

Config tabs need a ComfyUIClient to run; without one (a read-only gallery in a
test) :meth:`open_config` is a no-op — but a tab still shows, its form up for
inspection with Generate disabled.
"""

import time

from PyQt6.QtWidgets import QTabWidget, QInputDialog, QApplication, QMenu
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    build_image_config_index, media_type_of_row, rows_in_settings, settings_signature,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.eliding_tab_bar import ElidingTabBar
from origenerator.gui.generate_config_panel import GenerateConfigPanel
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
        # Drag a tab along the row to put it where you want it: the order is the
        # user's, not the order things happened to open in.
        self.setMovable(True)
        self.tabCloseRequested.connect(self._close_subtab)
        self.tabBarDoubleClicked.connect(self._rename_subtab)
        bar = self.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._open_tab_menu)
        # A dragged tab lands at a new index, and the italic mark is drawn by index.
        bar.tabMoved.connect(lambda _from, _to: self._sync_preview_tab())
        # The tab a click opened and the next click may replace (see the module
        # docstring). Tracked by panel rather than index, since tabs move.
        self._preview_panel: GenerateConfigPanel | None = None
        # A double-click on a tab's ✕ closes it, then the tabs shift and the
        # completing click lands on the neighbor as a tabBarDoubleClicked; stamp
        # each close so that stray double-click isn't taken for a rename gesture.
        self._last_close_at = float("-inf")
        self._add_subtab()  # the pane's resting tab

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

    def _add_subtab(self, *, preview: bool = False) -> GenerateConfigPanel:
        """Build, add and select a fresh editable config tab.

        ``preview`` opens it as the italic tab a later click may replace — what a
        single-clicked generation gets, where a deliberate open gets a tab of its
        own.

        Works even without a client: the tab shows for inspection, its Generate
        disabled. The tab's strip / source-link / animation signals are wired so a
        click in any of them reaches the gallery.
        """
        panel = GenerateConfigPanel(self._client, self._db)
        index = self.addTab(panel, panel.title())
        panel.title_changed.connect(lambda text, p=panel: self._update_title(p, text))
        panel.generate_requested.connect(  # relay every tab's Generate
            lambda name, params, p=panel: self._on_panel_generate(p, name, params)
        )
        panel.strip_activated.connect(self._on_strip_activated)
        self.setCurrentIndex(index)
        if preview:
            self._set_preview_panel(panel)
        self.tab_added.emit(panel)  # let the view wire its source/animation links
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
        if panel is self._preview_panel:
            self._preview_panel = None
        self.removeTab(index)
        panel.teardown()
        panel.deleteLater()

    def _close_subtab(self, index: int):
        self._last_close_at = time.monotonic()  # arm the stray-double-click guard
        self._discard_subtab(index)
        self._keep_a_tab_open()

    def _keep_a_tab_open(self):
        """Never leave the pane empty.

        Closing the last tab used to strand a black rectangle where the form had
        been, with nothing in it to click. A fresh blank tab takes its place
        instead — the pane's resting state, a whole generate form waiting on a
        workflow.
        """
        if self.count() == 0:
            self._add_subtab()

    def _discard_all_subtabs(self):
        """Tear down every open tab, leaving the pane momentarily empty.

        For a caller that rebuilds the tabs itself (:meth:`restore_state`);
        everything user-facing goes through the closes above, which top the pane
        back up. Walking from the last index down keeps each index valid as the
        tabs below it shift.
        """
        for index in range(self.count() - 1, -1, -1):
            self._discard_subtab(index)

    def _close_other_subtabs(self, index: int):
        """Close every tab but this one — the right-click menu's "Close others"."""
        keeper = self.widget(index)
        for i in range(self.count() - 1, -1, -1):
            if self.widget(i) is not keeper:
                self._discard_subtab(i)

    def _close_subtabs_to_the_right(self, index: int):
        """Close every tab after this one — the right-click menu's "Close to the
        right". Reads off position, so it follows a tab dragged elsewhere."""
        for i in range(self.count() - 1, index, -1):
            self._discard_subtab(i)

    def _tab_menu(self, index: int) -> QMenu:
        """The right-click menu for the tab at ``index``.

        Both entries always show, greyed when they would close nothing, so the
        menu reads the same wherever it opens instead of changing shape under the
        cursor.
        """
        menu = QMenu(self)
        others = menu.addAction("Close others")
        others.setEnabled(self.count() > 1)
        others.triggered.connect(lambda: self._close_other_subtabs(index))
        to_right = menu.addAction("Close to the right")
        to_right.setEnabled(index < self.count() - 1)
        to_right.triggered.connect(lambda: self._close_subtabs_to_the_right(index))
        return menu

    def _open_tab_menu(self, pos):
        """Pop the tab menu where a tab was right-clicked; nowhere else."""
        index = self.tabBar().tabAt(pos)
        if index >= 0:
            self._tab_menu(index).exec(self.tabBar().mapToGlobal(pos))

    # --- the preview tab ---------------------------------------------------

    def _set_preview_panel(self, panel: GenerateConfigPanel | None):
        """Make ``panel`` the one tab a later single click may replace."""
        self._preview_panel = panel
        self._sync_preview_tab()

    def _sync_preview_tab(self):
        """Tell the bar which tab to draw in italic, after anything that could
        have moved it — an open, a close, or a drag along the row."""
        panel = self._preview_panel
        self.tabBar().set_preview_index(self.indexOf(panel) if panel is not None else -1)

    def _pin_panel(self, panel):
        """Stop ``panel`` being the tab a later click replaces."""
        if self._preview_panel is panel:
            self._set_preview_panel(None)

    def pin_current_tab(self):
        """Keep the front tab: a double-click's "I'm staying here".

        The tab stops being the preview one, so the next single-clicked
        generation opens beside it rather than over it. A no-op on a tab that was
        already pinned.
        """
        self._pin_panel(self.currentWidget())

    def _on_panel_generate(self, panel, workflow_name: str, params: dict):
        """Relay a tab's Generate for the gallery to launch as a re-roll — and
        keep that tab.

        A tab with a run in flight is a tab being worked in: its Cancel and its
        filling progress bar belong to that run, and a later click replacing the
        tab would take both away while the job kept going.
        """
        self._pin_panel(panel)
        self.generate_requested.emit(workflow_name, params)

    def tabInserted(self, index: int):  # Qt hook: every add path lands here
        super().tabInserted(index)
        self._sync_preview_tab()  # the tabs after it just shifted right

    def tabRemoved(self, index: int):  # Qt hook: every close path lands here
        super().tabRemoved(index)
        self._sync_preview_tab()  # ...and back left

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
        """Show a single-clicked generation in a tab, without leaving a trail of
        them behind.

        Where it lands, in order: the front tab when that tab is the clicked row's
        own settings folder already; the pane's untouched resting tab, which
        becomes the preview tab by being clicked into; the preview tab, replaced
        where it stands; or a new preview tab when none is open.

        So a browse through a folder's items reuses one italic tab however many
        are clicked, while a tab that was pinned (double-clicked) or edited into a
        different folder is left where it is.
        """
        key = self._row_settings_key(row)
        cur = self.current_config_panel()
        if cur is not None and not cur.is_blank() and cur.settings_key() == key:
            target = cur  # already this generation's own tab, pinned or not
        elif cur is not None and cur.is_blank():
            target = cur  # the resting tab; a click is what makes it a preview tab
            self._set_preview_panel(target)
        elif self._preview_panel is not None:
            target = self._preview_panel  # replace the italic tab, don't fork
        else:
            target = self._add_subtab(preview=True)
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
        self._discard_all_subtabs()  # clear every tab before rebuilding from the snapshot
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
