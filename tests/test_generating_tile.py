from __future__ import annotations

import time
from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from shared_ui.colors import BLUE, TEXT_PRIMARY

from origenerator.gui.combination import Combination
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.stylesheet import build_stylesheet


def _png_bytes(color=(10, 120, 200)):
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


class FakeJob(QObject):
    started = pyqtSignal()
    progress = pyqtSignal(int, int)
    preview = pyqtSignal(bytes)

    def __init__(self, state="queued", last_progress=(0, 0), last_preview=None,
                 started_at=None, last_pass_progress=None, last_stage=""):
        super().__init__()
        self._state = state
        self._last_progress = last_progress
        self._last_pass_progress = last_pass_progress
        self._last_stage = last_stage
        self._last_preview = last_preview
        self._started_at = started_at

    @property
    def state(self):
        return self._state

    @property
    def last_progress(self):
        return self._last_progress

    @property
    def last_pass_progress(self):
        return self._last_pass_progress

    @property
    def last_stage(self):
        return self._last_stage

    @property
    def last_preview(self):
        return self._last_preview

    @property
    def started_at(self):
        return self._started_at


def _has_image(tile):
    return not tile._image.pixmap().isNull()


def test_a_queued_tile_says_waiting_over_the_picture(qtbot):
    # The stage is read on the scrim over the picture, the way an in-flight card
    # and an enhancing thumbnail say theirs.
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Waiting…"
    assert not tile._cancel.isHidden()
    assert tile._cancel.text() == "Cancel"


def test_an_auto_generating_folders_tile_says_next_seed(qtbot):
    # Pressing it there discards the seed and the loop starts another, so "Cancel"
    # would promise a stop that never comes.
    tile = GeneratingTile(FakeJob(state="running"), auto_generating=True)
    qtbot.addWidget(tile)
    assert tile._cancel.text() == "Next seed"
    assert "seed" in tile._cancel.toolTip()


def test_the_cancel_button_emits_cancel_requested(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    cancels = []
    tile.cancel_requested.connect(lambda: cancels.append(True))
    tile._cancel.click()
    assert cancels == [True]


def test_a_click_on_the_tile_selects_it(qtbot):
    # So the info pane can mirror its preview.
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    picks = []
    tile.selected.connect(lambda: picks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert picks == [True]


def test_set_selected_toggles_the_tile_highlight(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    assert not tile.is_selected()

    tile.set_selected(True)
    assert tile.is_selected()
    assert "solid" in tile.styleSheet()  # a solid selection border, not the dashed resting one

    tile.set_selected(False)
    assert not tile.is_selected()
    assert "dashed" in tile.styleSheet()


def _picked_tile_drawn(qtbot):
    """A picked tile, and the pixels of the card it sits in, drawn under the app
    stylesheet."""
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        holder = QWidget()
        qtbot.addWidget(holder)
        tile = GeneratingTile(FakeJob(state="running"), holder)
        tile.set_selected(True)
        holder.resize(tile.size())
        holder.show()
        qtbot.waitExposed(holder)
        return tile, holder.grab().toImage()
    finally:
        app.setStyleSheet(prior)


def test_a_picked_tile_is_filled_with_the_familys_blue(qtbot):
    tile, image = _picked_tile_drawn(qtbot)
    button = tile._cancel.geometry()

    beside = tile.mapToParent(QPoint(button.left() - 1, button.center().y()))
    assert image.pixelColor(beside).name() == BLUE.name()


def test_a_picked_tile_wears_a_white_frame(qtbot):
    tile, image = _picked_tile_drawn(qtbot)

    edge = tile.mapToParent(QPoint(0, tile.height() // 2))
    assert image.pixelColor(edge).name() == TEXT_PRIMARY.name()


def test_started_signal_switches_the_scrim_to_generating(qtbot):
    job = FakeJob(state="queued")
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    job._state = "running"
    job.started.emit()
    assert tile._scrim.text() == "Generating…"


def test_the_bar_carries_the_percentage_and_the_clock(qtbot):
    # The same line the lower strip's queue writes for the same job, so a run
    # reads identically wherever it is being watched.
    job = FakeJob(state="running", last_progress=(10, 20),
                  started_at=time.time() - 90.5)
    tile = GeneratingTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "50% · ~6:02 left"
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20)


def test_the_bar_says_which_pass_is_being_taken(qtbot):
    # A video run is three passes, and the band along the bar's foot restarts
    # once per pass. Named, the caption says which of them is being done — the
    # one thing a twelve-minute run can report while the countdown is still too
    # early to mean anything.
    job = FakeJob(state="running", last_progress=(405, 818),
                  last_pass_progress=(1, 10), last_stage="Second pass",
                  started_at=time.time() - 90.5)
    tile = GeneratingTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption().startswith("Second pass · 49% · ")


def test_the_tile_stands_what_the_run_is_made_from(qtbot, tmp_path):
    # It stood a blurred copy of the frame, where the strip's corner stood a
    # sharp pair and the config tab stood a blank — three surfaces, three ideas
    # of one wait. All three stand the sum now.

    frame = tmp_path / "frame.png"
    Image.new("RGB", (60, 40), (0, 0, 255)).save(frame)
    clip = tmp_path / "clip.png"
    Image.new("RGB", (60, 40), (255, 0, 0)).save(clip)
    job = FakeJob(state="running", started_at=time.time() - 5)
    tile = GeneratingTile(job, made_from=Combination(str(frame), str(clip)))
    qtbot.addWidget(tile)

    picture = tile._image.pixmap()
    assert picture is not None and not picture.isNull()
    assert picture.width() > picture.height()   # the pair, not one picture alone


def test_a_tile_with_nothing_behind_it_keeps_its_plain_plate(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)

    assert tile._image.pixmap().isNull()


def test_progress_signal_advances_the_bar(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 30.5)
    tile = GeneratingTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    job._last_progress = (3, 10)
    job.progress.emit(3, 10)
    assert tile._bar.caption().startswith("30% · ")
    assert (tile._bar.value(), tile._bar.maximum()) == (3, 10)


def test_a_job_comfyui_has_not_started_leaves_the_bar_blank_and_sweeping(qtbot):
    # Its wait is the strip's queue to explain; a zero counting up over a bar that
    # has not moved says the run is going nowhere.
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == ""
    assert tile._bar.maximum() == 0  # indeterminate: sweeping, not stuck at 0%


def test_the_clock_advances_between_polls(qtbot):
    # The gallery re-renders on its own schedule, which would make a seconds count
    # skip; the tile re-reads the clock itself so it moves a second at a time.
    job = FakeJob(state="running", started_at=time.time() - 5.5)
    tile = GeneratingTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "~1:34 left"

    job._started_at -= 3  # as if three seconds had gone by
    tile._tick.timeout.emit()
    assert tile._bar.caption() == "~1:31 left"


def test_preview_signal_renders_image(qtbot):
    job = FakeJob(state="queued")
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    assert not _has_image(tile)
    job.preview.emit(_png_bytes())
    assert _has_image(tile)


def test_the_bar_sits_along_the_foot_of_the_picture(qtbot):
    # Overlaid rather than laid out beneath, so the picture keeps the full
    # height every card in the grid gives it.
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    picture, bar = tile._image.geometry(), tile._bar.geometry()

    assert bar.bottomLeft().y() == picture.bottomLeft().y()
    assert bar.left() == picture.left() and bar.width() == picture.width()
    assert bar.top() > picture.center().y()


def test_a_tile_rebuilt_mid_run_shows_the_jobs_cached_state(qtbot):
    # A tile rebuilt mid-run (navigation/poll) must show the job's current state.
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes(),
                  started_at=time.time() - 20.5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    assert _has_image(tile)
    assert tile._scrim.text() == "Generating…"
    assert tile._bar.caption().startswith("50% · ")


def test_right_clicking_the_tile_asks_for_its_menu(qtbot):
    # The tile is a card in the grid like any other, and every other one answers
    # a right-click. It hands the gesture up for the gallery to answer with the
    # run's own menu.
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    asked = []
    tile.context_requested.connect(lambda pos: asked.append(pos))

    tile.customContextMenuRequested.emit(QPoint(5, 5))

    assert len(asked) == 1
