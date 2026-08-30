"""The gallery's info pane as a tabbed workspace of editable generate tabs.

Every tab is the same plain, editable :class:`GenerateConfigPanel` — pick a
workflow and set params — with no special or permanent tab. The pane always holds
at least one: closing the last tab opens a fresh blank one in its place, so the
resting state is a whole generate form waiting on a workflow rather than an empty
black rectangle. That is why there is no "+" — a tab is always there. A tab's
right-click menu closes the others, everything to its right, or all of them,
listing only what that tab can actually do, and tabs drag along the row to
reorder. Closing all of them is not an empty pane either: the resting tab takes
their place, which is what "close all" means where one tab is always open.

Tabs open the way an IDE opens files, so browsing doesn't leave a row of them
behind. A single-clicked generation lands in the *preview* tab, drawn in italic:
the next single click replaces it. A double-click on the tab pins it upright, and
the click after it opens a new preview tab beside it. Opening a configuration by
name — a history-strip click, a queue row, the combine panel's "Open in
generator" — lands the same way, since it is the same "show me this" gesture;
generating from the tab pins it too.

The pane's blank resting tab is never left sitting beside real work: whatever
opens next takes it over rather than appearing next to it.

The resting tab wears the slant too, from the moment the pane opens: nothing has
been done in it, so the next open takes it over — which is all the italic ever
means here. Picking a workflow in it takes the slant off, since that is work
someone did and an open would throw it away.

Each tab is named after what it is showing, not typed: the item on display, by
its file, marked with that item's own thumbnail — or, before there is one, the
folder the config would generate into and the plain image/video mark for what it
makes. So the row of tabs reads as the things you have open.

This owns every tab's lifecycle — add, close, rename, and session capture/restore
of each tab's configuration.

A tab's Generate doesn't run a job here; it emits :attr:`generate_requested`, which
this relays for the gallery to launch as a re-roll of the config's settings folder.
The gallery owns every in-flight job (a re-roll) and reconnects any left running
after a restart, so the tabs carry no job state.

Clicking a browser thumbnail loads that generation into a tab (see
:meth:`load_selection`), where its output shows in the preview, its settings seed
the editable form, and a footer offers the source-image link / animations /
Send-to-Evolver for its media type.

Config tabs need a ComfyUIClient to run; without one (a read-only gallery in a
test) :meth:`open_config` is a no-op — but a tab still shows, its form up for
inspection with Generate disabled.
"""

import time

from PyQt6.QtWidgets import QTabWidget, QApplication, QMenu
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    build_image_config_index, media_type_of_row, settings_signature,
)
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui.eliding_tab_bar import ElidingTabBar, MARK_CANVAS, tab_mark
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.workflows import WORKFLOW_REGISTRY

class InfoPaneTabs(QTabWidget):
    """A strip of editable config tabs; each tab's Generate becomes a gallery re-roll."""

    tab_added = pyqtSignal(object)  # a fresh GenerateConfigPanel, for the view to wire
    generate_requested = pyqtSignal(str, dict)  # any tab's Generate: (workflow_name, params)
    # A rewrite tab's Generate: (source folder key, workflow_name, params) — one
    # run per picture in that folder rather than one run of these settings.
    changes_requested = pyqtSignal(str, str, dict)

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
        self.setIconSize(MARK_CANVAS)  # the mark, plus the gap it trails
        self.tabCloseRequested.connect(self._close_subtab)
        self.tabBarDoubleClicked.connect(self._pin_subtab)
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
        # A hosting session's OmniPause, held so a tab opened during it opens
        # held rather than starting its video into a frozen room.
        self._previews_paused = False
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

        ``preview`` opens it as the italic tab a later open may replace — what
        every gesture that shows a generation gets, where the pane's resting tab
        and a restored session's tabs stand on their own.

        Works even without a client: the tab shows for inspection, its Generate
        disabled. The tab's source-link / animation signals are wired so a click
        in either of them reaches the gallery.
        """
        panel = GenerateConfigPanel(self._client, self._db)
        index = self.addTab(panel, tab_mark(panel.tab_icon()), panel.title())
        panel.title_changed.connect(lambda _text, p=panel: self._update_tab(p))
        panel.generate_requested.connect(  # relay every tab's Generate
            lambda name, params, p=panel: self._on_panel_generate(p, name, params)
        )
        panel.changes_requested.connect(  # ...and a rewrite tab's, which asks for more
            lambda key, name, params, p=panel: self._on_panel_changes(p, key, name, params)
        )
        panel.set_preview_paused(self._previews_paused)  # a tab opened mid-freeze stays still
        self.setCurrentIndex(index)
        if preview:
            self._set_preview_panel(panel)
        self.tab_added.emit(panel)  # let the view wire its source/animation links
        return panel

    def _update_tab(self, panel: GenerateConfigPanel):
        """Re-label a tab from its panel — name and mark together, since both say
        the same thing about what the tab is showing."""
        index = self.indexOf(panel)
        if index >= 0:
            self.setTabText(index, panel.title())
            self.setTabIcon(index, tab_mark(panel.tab_icon()))
        # Whatever renamed it may also have been what made it stop being blank.
        self._sync_preview_tab()

    def _closed_within_double_click(self) -> bool:
        """Was a config tab closed within one double-click of now?

        The completing click of a double-click on a ✕ arrives this close, so a
        pin firing that soon after a close is that stray click, not a gesture.
        """
        interval = QApplication.doubleClickInterval() / 1000  # ms -> s
        return time.monotonic() - self._last_close_at < interval

    def _pin_subtab(self, index: int):
        """A double-click on a tab keeps it: the italic comes off, and the next
        open goes beside it rather than over it.

        The same gesture used to ask for a name. Tabs are named after what they
        show now, so there was nothing left for a typed one to say.
        """
        if index < 0:
            return
        if self._closed_within_double_click():
            return  # a stray double-click left over from closing a tab, not a pin
        panel = self.widget(index)
        if isinstance(panel, GenerateConfigPanel):
            self._pin_panel(panel)

    def _discard_subtab(self, index: int):
        """Take one config tab out of the row and let go of it."""
        panel = self.widget(index)
        if not isinstance(panel, GenerateConfigPanel):
            return
        if panel is self._preview_panel:
            self._preview_panel = None
        self.removeTab(index)
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

    def _close_all_subtabs(self):
        """Close every tab — the right-click menu's "Close all".

        The pane tops itself back up with a fresh resting tab, since it never
        sits empty; "all" is about the work open in the row, not about leaving a
        black rectangle behind.
        """
        self._last_close_at = time.monotonic()  # arm the stray-double-click guard
        self._discard_all_subtabs()
        self._keep_a_tab_open()

    def _tab_menu(self, index: int) -> QMenu:
        """The right-click menu for the tab at ``index``.

        Only what this tab can actually do: on the last tab there is nothing to
        its right, and on the only tab there are no others and no all — an entry
        that would close nothing is left out rather than listed dead.
        """
        menu = QMenu(self)
        if self.count() > 1:
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
        """Pop the tab menu where a tab was right-clicked; nowhere else.

        A menu with nothing in it — the pane's single resting tab — doesn't open
        at all, rather than flashing an empty box at the cursor.
        """
        index = self.tabBar().tabAt(pos)
        if index < 0:
            return
        menu = self._tab_menu(index)
        if menu.actions():
            menu.exec(self.tabBar().mapToGlobal(pos))

    # --- the preview tab ---------------------------------------------------

    def _set_preview_panel(self, panel: GenerateConfigPanel | None):
        """Make ``panel`` the one tab a later single click may replace."""
        self._preview_panel = panel
        self._sync_preview_tab()

    def _italic_panel(self) -> GenerateConfigPanel | None:
        """The tab drawn slanted: the one an open would take over.

        The preview tab when there is one; else the pane's untouched resting
        tab, which makes the same promise — nothing has been done in it, so the
        next open lands there. Read rather than stored, so the resting tab loses
        its slant the moment a workflow is picked in it and it becomes work.
        """
        if self._preview_panel is not None:
            return self._preview_panel
        return next((p for p in self._config_panels() if p.is_blank()), None)

    def _sync_preview_tab(self):
        """Tell the bar which tab to draw in italic, after anything that could
        have moved it — an open, a close, a drag along the row, or a tab that
        just stopped being blank."""
        panel = self._italic_panel()
        self.tabBar().set_preview_index(self.indexOf(panel) if panel is not None else -1)

    def _pin_panel(self, panel):
        """Stop ``panel`` being the tab a later click replaces."""
        if self._preview_panel is panel:
            self._set_preview_panel(None)

    def _landing_panel(self) -> GenerateConfigPanel:
        """The tab an opened generation lands in, so opening one doesn't leave a
        trail of tabs behind.

        In order: the pane's untouched resting tab, which becomes the preview tab
        by being opened into — a blank "New generation" is never left sitting
        beside real work; the preview tab, replaced where it stands; or a fresh
        preview tab when neither is there.
        """
        cur = self.current_config_panel()
        blank = cur if cur is not None and cur.is_blank() else next(
            (p for p in self._config_panels() if p.is_blank()), None
        )
        if blank is not None:
            self._set_preview_panel(blank)
            return blank
        if self._preview_panel is not None:
            return self._preview_panel  # replace the italic tab, don't fork
        return self._add_subtab(preview=True)

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

    def _on_panel_changes(self, panel, folder_key: str, workflow_name: str,
                           params: dict):
        """Relay a rewrite tab's Generate — and keep that tab, for the reason a
        launched tab is kept: the runs are its, and a later click replacing it
        would take their Cancel and their progress away mid-batch."""
        self._pin_panel(panel)
        self.changes_requested.emit(folder_key, workflow_name, params)

    def tabInserted(self, index: int):  # Qt hook: every add path lands here
        super().tabInserted(index)
        self._sync_preview_tab()  # the tabs after it just shifted right

    def tabRemoved(self, index: int):  # Qt hook: every close path lands here
        super().tabRemoved(index)
        self._sync_preview_tab()  # ...and back left

    def _row_settings_key(self, row: dict):
        """The settings folder (workflow + signature) a stored row lands in."""
        workflow_name = row.get("workflow_name", "")
        index = build_image_config_index(
            [r for r in self._db.list_generations() if media_type_of_row(r) == "image"]
        )
        return workflow_name, settings_signature(workflow_name, row.get("params_json"), index,
                                                 workflow_version=row.get("workflow_version"))

    def open_config(self, workflow_name: str, params: dict) -> GenerateConfigPanel | None:
        """Open (and select) an editable config tab prefilled from a generation —
        a history-strip click, a queue row, or "Open in generator".

        Lands where a browsed click lands (:meth:`_landing_panel`), and wears the
        same italic mark: naming a configuration is still "show me this", not a
        tab someone has settled into. Running it, or double-clicking its tab, pins
        it upright.

        A no-op without a client — nothing could run the resulting config.
        """
        if self._client is None:
            return None
        panel = self._landing_panel()
        panel.prefill(workflow_name, params)
        self.setCurrentWidget(panel)
        return panel

    def open_folder_request(self, folder_key: str, label: str, workflow_name: str,
                      params: dict, pictures: list) -> GenerateConfigPanel | None:
        """Open a folder's prompt rewrite in a tab (see
        :meth:`GenerateConfigPanel.open_folder_request`).

        Lands where an open lands, then keeps the tab upright: a rewrite is
        something being written, not a generation being looked at, so the next
        clicked thumbnail must open beside it rather than over it.

        A no-op without a client — nothing could run the rewrite.
        """
        if self._client is None:
            return None
        panel = self._landing_panel()
        panel.open_folder_request(folder_key, label, workflow_name, params, pictures)
        self._pin_panel(panel)
        self.setCurrentWidget(panel)
        return panel

    # --- loading the browser selection into a tab --------------------------

    def load_selection(self, row: dict, image_rows: list[dict], request=None):
        """Show a single-clicked generation in a tab, without leaving a trail of
        them behind.

        The front tab takes it when that tab is the clicked row's own settings
        folder already, pinned or not; anything else lands where an open lands
        (:meth:`_landing_panel`).

        So a browse through a folder's items reuses one italic tab however many
        are clicked, while a tab that was pinned (double-clicked) or edited into a
        different folder is left where it is.

        ``request`` is the spoken request that made this row, when one did, so the
        tab can mark what it changed and link back to what it was asked about.
        """
        key = self._row_settings_key(row)
        cur = self.current_config_panel()
        if cur is not None and not cur.is_blank() and cur.settings_key() == key:
            target = cur  # already this generation's own tab, pinned or not
        else:
            target = self._landing_panel()
        target.show_saved_generation(row, image_rows, request)
        self.setCurrentWidget(target)

    def panel_that_launched(self, origin: str | None):
        """The tab that launched the run beginning at ``origin``, or ``None``.

        A run's result belongs to the tab that asked for it: that tab ends showing
        the finished image/video rather than the live-frame placeholder. Every
        other tab is left alone — including the pane's resting tab, which the
        gallery's own launches (the folder tile's "+", the auto-generate loop)
        used to fill with a picture nothing in it had asked for. That left the
        resting tab no longer blank, so the next clicked generation opened a tab
        beside it instead of loading into it, and a loop running while the user
        browsed grew a row of them.

        A tab claims a gallery-side launch only while it is showing that very
        folder (see ``GalleryView._claim_launch``), so what a loop lands in is a
        tab already following it, never one parked elsewhere.

        Read *before* the finish is reconciled — a tab lets go of its runs as they
        end (see ``GalleryView._reconcile_generating``).
        """
        if not origin:
            return None
        return next((panel for panel in self._config_panels()
                     if origin in panel.launched_runs()), None)

    def set_previews_paused(self, paused: bool) -> None:
        """Freeze (or resume) every tab's playing video — the hosting session's
        OmniPause, which stops the room rather than only its shows.  A tab
        showing a still takes it inertly; one showing a video stops.

        Remembered, not just applied: a tab opened (or re-pointed at a video)
        while the room is frozen has to open frozen too, so ``_add_subtab``
        pushes the remembered flag into every panel it builds.  The looping
        thumbnails around these previews are held elsewhere and app-wide — see
        :mod:`origenerator.gui.looping_preview`.
        """
        self._previews_paused = paused
        for panel in self._config_panels():
            panel.set_preview_paused(paused)

    def show_selection_preview(self, preview, prompt_id: str):
        """Point the current tab's preview at ``preview`` (a resolved
        ``(path, media_type)``, or ``None``) without touching its form or the tab
        set — the light-touch update a suppressed poll/rebuild re-selection makes.

        ``prompt_id`` is the shown generation, so the tab can hang everything the
        picture carries back off it: the drag onto a combine slot, and the corner
        controls and right-click menu, both of which showing media clears. That
        is the tab's own business, so it does it
        (:meth:`~origenerator.gui.generate_config_panel.GenerateConfigPanel.show_selection_media`)
        rather than being reached into from here — which is what left the preview
        bare of its corners on every launch, since the restored selection comes
        through this path and not through a click.

        The pane's resting tab is left alone: a tab with no workflow picked and
        nothing on display holds no generation, so there is no preview of its own
        to refresh, and giving it one shows a picture over a form still asking
        which workflow to run. That is what reopening the app on the resting tab
        used to do — the restored gallery selection re-selects itself through here,
        and its image landed in a "New generation" tab. A genuine click doesn't
        come this way: it goes through :meth:`load_selection`, which fills such a
        tab whole — form, preview and footer together.
        """
        panel = self.current_config_panel()
        if panel is None:
            return
        if preview is None:
            panel._preview.clear()  # nothing to show disarms the drag itself
        elif not panel.is_blank():
            panel.show_selection_media(preview, prompt_id)

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

    def show_reroll_result(self, row: dict):
        """The re-roll whose frames the front tab was mirroring has landed: its
        saved output takes their place there, so a run watched to the end shows the
        picture it made instead of freezing on its last partial frame.

        The preview alone — the tab keeps its own form, footer and generation (see
        :meth:`GenerateConfigPanel.show_finished_media`); the whole end-state goes
        to the tab that launched the run, if a tab did."""
        panel = self.current_config_panel()
        if panel is not None:
            panel.show_finished_media(row)

    def refresh_displayed(self, row: dict, image_rows: list[dict]):
        """A row has changed: re-show it in every tab displaying it.

        Every tab rather than the front one, and only the tabs actually on that
        generation (:meth:`GenerateConfigPanel.refresh_displayed`) — a change to
        one image must not touch a tab looking at another.
        """
        for panel in self._config_panels():
            panel.refresh_displayed(row, image_rows)

    def drop_previews_of_gone_rows(self, live_ids):
        """Empty the preview of every tab showing a generation that is no longer
        there — the deletion (or trashing) a gallery rebuild has just taken in.

        Every tab, and only what has gone: a rebuild happens whenever anything
        lands, so blanking more than that takes the picture out of a tab the user
        left open and is looking at.
        """
        for panel in self._config_panels():
            row = panel.displayed_row()
            if row is not None and row.get("prompt_id") not in live_ids:
                panel._preview.clear()

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

        Each carries its configuration and the runs its own Generate started;
        ``current`` is the active tab, so the same tab reopens focused. The
        gallery reconnects still-running re-rolls itself — the recorded runs are
        only how a tab knows which of them are *its*, so its Cancel and progress
        fill come back on the right tab after a restart. No name is stored: a tab
        is named after what it shows, which its configuration brings back.
        """
        tabs = [
            {
                "config": panel.current_config().to_dict(),
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
            launched = entry.get("launched_runs")
            restored.append((
                snapshot,
                [r for r in launched if isinstance(r, str) and r]
                if isinstance(launched, list) else [],
            ))
        if not restored:
            return  # keep the initial tab rather than leaving no tabs at all
        self._discard_all_subtabs()  # clear every tab before rebuilding from the snapshot
        for snapshot, launched in restored:
            panel = self._add_subtab()
            panel.restore_config(snapshot)
            # Runs this tab started and the app was closed on: the gallery
            # reconnects them, and this is how the tab knows they are its own.
            for origin in launched:
                panel.note_launched(origin)
        current = state.get("current", 0)
        if isinstance(current, int) and 0 <= current < self.count():
            self.setCurrentIndex(current)
