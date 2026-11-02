from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget
from shared_ui.colors import BLUE, TEXT_PRIMARY

from origenerator.gui.combination import Combination
from origenerator.gui.generating_tile import GeneratingTile
from tests.tile_drawing import drawn_under_the_app_stylesheet


def _png_bytes(color=(10, 120, 200)):
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


@dataclass(eq=False)
class FakeJob(QObject):
    state: str = "queued"
    last_progress: tuple = (0, 0)
    last_preview: bytes | None = None
    started_at: float | None = None
    last_pass_progress: tuple | None = None
    last_stage: str = ""

    started = pyqtSignal()
    progress = pyqtSignal(int, int)
    preview = pyqtSignal(bytes)

    def __post_init__(self):
        super().__init__()


def _has_image(tile):
    return not tile._image.pixmap().isNull()


def test_a_queued_tile_says_waiting_over_the_thumbnail(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._status_scrim.text() == "Waiting…"
    assert not tile._cancel.isHidden()
    assert tile._cancel.text() == "Cancel"


def test_an_auto_generating_folders_tile_says_cancel_and_hovers_the_next_seed(qtbot):
    tile = GeneratingTile(FakeJob(state="running"), auto_generating=True)
    qtbot.addWidget(tile)
    assert tile._cancel.text() == "Cancel"
    assert "seed" in tile._cancel.toolTip()


def test_the_cancel_button_emits_cancel_requested(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    cancels = []
    tile.cancel_requested.connect(lambda: cancels.append(True))
    tile._cancel.click()
    assert cancels == [True]


def test_a_click_on_the_tile_selects_it(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    picks = []
    tile.selected.connect(lambda: picks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert picks == [True]


def test_set_selected_toggles_the_tile_highlight(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    assert not tile._selected

    tile.set_selected(True)
    assert tile._selected
    assert "solid" in tile.styleSheet()

    tile.set_selected(False)
    assert not tile._selected
    assert "dashed" in tile.styleSheet()


def _picked_tile_drawn(qtbot):
    def build():
        holder = QWidget()
        tile = GeneratingTile(FakeJob(state="running"), holder)
        tile.set_selected(True)
        holder.resize(tile.size())
        return tile, holder

    return drawn_under_the_app_stylesheet(qtbot, build)


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
    job.state = "running"
    job.started.emit()
    assert tile._status_scrim.text() == "Generating…"


def test_the_bar_carries_the_percentage_and_the_clock(qtbot):
    job = FakeJob(state="running", last_progress=(10, 20),
                  started_at=time.time() - 90.5)
    tile = GeneratingTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "50% · ~6:02 left"
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20)


def test_the_bar_says_which_pass_is_being_taken(qtbot):
    job = FakeJob(state="running", last_progress=(405, 818),
                  last_pass_progress=(1, 10), last_stage="Second pass",
                  started_at=time.time() - 90.5)
    tile = GeneratingTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption().startswith("Second pass · 49% · ")


def test_the_tile_stands_what_the_run_is_made_from(qtbot, tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (60, 40), (0, 0, 255)).save(frame)
    video = tmp_path / "clip.png"
    Image.new("RGB", (60, 40), (255, 0, 0)).save(video)
    job = FakeJob(state="running", started_at=time.time() - 5)
    tile = GeneratingTile(job, made_from=Combination(str(frame), str(video)))
    qtbot.addWidget(tile)

    thumbnail = tile._image.pixmap()
    assert thumbnail is not None
    assert not thumbnail.isNull()
    assert thumbnail.width() > thumbnail.height()


def test_a_tile_with_nothing_behind_it_keeps_its_plain_plate(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)

    assert tile._image.pixmap().isNull()


def test_progress_signal_advances_the_bar(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 30.5)
    tile = GeneratingTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    job.last_progress = (3, 10)
    job.progress.emit(3, 10)
    assert tile._bar.caption().startswith("30% · ")
    assert (tile._bar.value(), tile._bar.maximum()) == (3, 10)


def test_a_job_comfyui_has_not_started_leaves_the_bar_blank_and_sweeping(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == ""
    assert tile._bar.maximum() == 0


def test_the_clock_advances_between_polls(qtbot):
    job = FakeJob(state="running", started_at=time.time() - 5.5)
    tile = GeneratingTile(job, typical_seconds=100.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "~1:34 left"

    job.started_at -= 3
    tile._tick.timeout.emit()
    assert tile._bar.caption() == "~1:31 left"


def test_preview_signal_renders_image(qtbot):
    job = FakeJob(state="queued")
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    assert not _has_image(tile)
    job.preview.emit(_png_bytes())
    assert _has_image(tile)


def test_the_bar_sits_along_the_foot_of_the_thumbnail(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    thumbnail, bar = tile._image.geometry(), tile._bar.geometry()

    assert bar.bottomLeft().y() == thumbnail.bottomLeft().y()
    assert bar.left() == thumbnail.left()
    assert bar.width() == thumbnail.width()
    assert bar.top() > thumbnail.center().y()


def test_a_tile_rebuilt_mid_run_shows_the_jobs_cached_state(qtbot):
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes(),
                  started_at=time.time() - 20.5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    assert _has_image(tile)
    assert tile._status_scrim.text() == "Generating…"
    assert tile._bar.caption().startswith("50% · ")


def test_right_clicking_the_tile_asks_for_its_menu(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    asked = []
    tile.context_requested.connect(asked.append)

    tile.customContextMenuRequested.emit(QPoint(5, 5))

    assert len(asked) == 1
