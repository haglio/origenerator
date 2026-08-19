import time
from io import BytesIO

from PIL import Image
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from origenerator.gui.reroll_tile import RerollTile


def _png_bytes(color=(10, 120, 200)):
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


class FakeJob(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(int, int)
    preview = pyqtSignal(bytes)

    def __init__(self, state="queued", last_progress=(0, 0), last_preview=None,
                 started_at=None):
        super().__init__()
        self._state = state
        self._last_progress = last_progress
        self._last_preview = last_preview
        self._started_at = started_at

    @property
    def state(self):
        return self._state

    @property
    def last_progress(self):
        return self._last_progress

    @property
    def last_preview(self):
        return self._last_preview

    @property
    def started_at(self):
        return self._started_at


def _has_image(tile):
    return not tile._image.pixmap().isNull()


def test_idle_tile_shows_plus_and_hides_cancel(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    assert tile._image.text() == "+"
    assert tile._cancel.isHidden()
    assert tile._status.text() == "New (random seed)"
    assert tile._bar.isHidden()  # nothing running: nothing for a bar to measure


def test_idle_tile_emits_add_requested_on_click(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert clicks == [True]


def test_active_queued_tile_says_waiting_over_the_picture(qtbot):
    # The stage is read on the scrim over the picture, the way an in-flight card
    # and an enhancing thumbnail say theirs — not in a caption underneath, which
    # cost the tile a row to repeat what the picture is already about.
    tile = RerollTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Waiting…"
    assert tile._status.isHidden()
    assert not tile._cancel.isHidden()
    assert tile._cancel.text() == "Cancel"


def test_an_auto_generating_folders_tile_says_next_seed(qtbot):
    # Pressing it there discards the seed and the loop starts another, so "Cancel"
    # would promise a stop that never comes.
    tile = RerollTile(FakeJob(state="running"), auto_generating=True)
    qtbot.addWidget(tile)
    assert tile._cancel.text() == "Next seed"
    assert "seed" in tile._cancel.toolTip()


def test_active_tile_cancel_button_emits_cancel_requested(qtbot):
    tile = RerollTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    cancels = []
    tile.cancel_requested.connect(lambda: cancels.append(True))
    tile._cancel.click()
    assert cancels == [True]


def test_active_tile_does_not_emit_add_on_click(qtbot):
    tile = RerollTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert clicks == []


def test_active_tile_emits_selected_on_click(qtbot):
    # Clicking a running tile selects it (so the info pane can mirror its
    # preview), rather than starting another re-roll.
    tile = RerollTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    picks = []
    tile.selected.connect(lambda: picks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert picks == [True]


def test_idle_tile_does_not_emit_selected_on_click(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    picks = []
    tile.selected.connect(lambda: picks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert picks == []


def test_set_selected_toggles_the_tile_highlight(qtbot):
    tile = RerollTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    assert not tile.is_selected()

    tile.set_selected(True)
    assert tile.is_selected()
    assert "solid" in tile.styleSheet()  # a solid selection border, not the dashed idle one

    tile.set_selected(False)
    assert not tile.is_selected()
    assert "dashed" in tile.styleSheet()


def test_started_signal_switches_the_scrim_to_generating(qtbot):
    job = FakeJob(state="queued")
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    job._state = "running"
    job.started.emit()
    assert tile._scrim.text() == "Generating…"


def test_the_bar_carries_the_percentage_and_the_clock(qtbot):
    # The same line the bottom strip's queue writes for the same job, so a run
    # reads identically wherever it is being watched.
    job = FakeJob(state="running", last_progress=(10, 20),
                  started_at=time.time() - 90.5)
    tile = RerollTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "50% · ~6:02 left"
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20)


def test_progress_signal_advances_the_bar(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 30.5)
    tile = RerollTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    job._last_progress = (3, 10)
    job.progress.emit(3, 10)
    assert tile._bar.caption().startswith("30% · ")
    assert (tile._bar.value(), tile._bar.maximum()) == (3, 10)


def test_a_job_comfyui_has_not_started_leaves_the_bar_blank_and_sweeping(qtbot):
    # Its wait is the strip's queue to explain; a zero counting up over a bar that
    # has not moved says the run is going nowhere.
    tile = RerollTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == ""
    assert tile._bar.maximum() == 0  # indeterminate: sweeping, not stuck at 0%


def test_the_clock_advances_between_polls(qtbot):
    # The gallery re-renders on its own schedule, which would make a seconds count
    # skip; the tile re-reads the clock itself so it moves a second at a time.
    job = FakeJob(state="running", started_at=time.time() - 5.5)
    tile = RerollTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "~1:34 left"

    job._started_at -= 3  # as if three seconds had gone by
    tile._tick.timeout.emit()
    assert tile._bar.caption() == "~1:31 left"


def test_preview_signal_renders_image(qtbot):
    job = FakeJob(state="queued")
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    assert not _has_image(tile)
    job.preview.emit(_png_bytes())
    assert _has_image(tile)


def test_the_bar_sits_along_the_foot_of_the_picture(qtbot):
    # Overlaid rather than laid out beneath, so a running tile is the same size
    # and shape as the idle one it replaced — the picture keeps its full height.
    tile = RerollTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    picture, bar = tile._image.geometry(), tile._bar.geometry()

    assert bar.bottom() == picture.bottom()
    assert bar.left() == picture.left() and bar.width() == picture.width()
    assert bar.top() > picture.center().y()


def test_tile_rebinds_to_running_job_from_cached_state(qtbot):
    # A tile rebuilt mid-run (navigation/poll) must show the job's current state.
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes(),
                  started_at=time.time() - 20.5)
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    assert _has_image(tile)
    assert tile._scrim.text() == "Generating…"
    assert tile._bar.caption().startswith("50% · ")
