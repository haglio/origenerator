from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO

from app_support.threading_utils import wait_until
from PIL import Image
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QWidget
from shared_ui.colors import BLUE, TEXT_PRIMARY
from shared_ui.testing import appending_to

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

    started = Signal()
    progress = Signal(int, int)
    preview = Signal(bytes)

    def __post_init__(self):
        super().__init__()


def _has_image(tile):
    return not tile._image.pixmap().isNull()


def test_a_queued_tile_says_waiting_over_the_thumbnail(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._status_scrim.text() == "Waiting…", (
        "the stage is read on the scrim over the thumbnail, the way an in-flight tile and an "
        "enhancing thumbnail say theirs")


def test_the_bar_reads_cancel_while_the_cursor_is_over_it(qtbot):
    tile = GeneratingTile(FakeJob(state="running", last_progress=(10, 20)))
    qtbot.addWidget(tile)
    progress = tile._bar.text()

    QApplication.sendEvent(tile._bar, QEnterEvent(QPointF(), QPointF(), QPointF()))
    assert tile._bar.text() == "Cancel"
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20), (
        "only the words change; the blue bar goes on showing the run")

    QApplication.sendEvent(tile._bar, QEvent(QEvent.Type.Leave))
    assert tile._bar.text() == progress != "Cancel"


def test_the_bar_hovers_the_next_seed_on_a_populating_folders_tile(qtbot):
    tile = GeneratingTile(FakeJob(state="running"), populating=True)
    qtbot.addWidget(tile)
    assert "seed" in tile._bar.toolTip()


def test_a_click_on_the_bar_cancels_the_run(qtbot):
    tile = GeneratingTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    cancels, picks = [], []
    tile.cancel_requested.connect(lambda: cancels.append(True))
    tile.selected.connect(lambda: picks.append(True))
    qtbot.mouseClick(tile._bar, Qt.MouseButton.LeftButton)
    wait_until(lambda: cancels == [True], pump=QApplication.processEvents)
    assert picks == [], "the press cancels and does not also pick the tile"


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
    button = tile._name.geometry()

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
    assert tile._bar.caption() == "50% · ~6:02 left", (
        "the same line the Job Queue writes for the same job, so a run reads alike wherever it is watched")
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20)


def test_the_bar_says_which_pass_is_being_taken(qtbot):
    job = FakeJob(state="running", last_progress=(405, 818),
                  last_pass_progress=(1, 10), last_stage="Second pass",
                  started_at=time.time() - 90.5)
    tile = GeneratingTile(job, typical_seconds=725.0)
    qtbot.addWidget(tile)
    assert tile._bar.caption().startswith("Second pass · 49% · "), (
        "a video's three passes each restart the bar, and early in a long run the pass is the one "
        "thing it can report")


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
    assert tile._bar.caption() == "", (
        "its wait is the Job Queue's to explain; a zero counting up would say the run is stuck")
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


def test_the_bar_sits_between_the_thumbnails_bottom_corners(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    thumbnail, bar = tile._image.geometry(), tile._bar.geometry()

    assert thumbnail.contains(bar), "the bar rides over the thumbnail, as an enhancing image's does"
    assert bar.left() - thumbnail.left() == thumbnail.right() - bar.right()
    for icon in (tile._controls._trash, tile._controls._enhance_button):
        assert not icon.geometry().intersects(bar), (
            "the trash and the enhance button keep the thumbnail's lower corners")


def test_the_tile_shows_the_items_name_under_the_thumbnail(qtbot):
    tile = GeneratingTile(FakeJob(state="running"), name="5A0C3E7B 004")
    qtbot.addWidget(tile)
    assert tile._name.text() == "5A0C3E7B 004"
    assert tile._name.geometry().top() > tile._image.geometry().bottomLeft().y()


def test_the_tile_offers_its_favorite_trash_and_enhance_icons(qtbot):
    tile = GeneratingTile(FakeJob(state="running"), enhance="open")
    qtbot.addWidget(tile)
    pressed = []
    tile.control_triggered.connect(pressed.append)

    for icon in tile._controls.buttons():
        assert not icon.isHidden()
        icon.click()

    assert pressed == ["star", "trash", "enhance"]


def test_a_video_being_generated_offers_no_enhance_icon(qtbot):
    tile = GeneratingTile(FakeJob(state="running"), enhance=None)
    qtbot.addWidget(tile)
    assert tile._controls._enhance_button.isHidden()
    assert not tile._controls._trash.isHidden()


def test_a_tile_rebuilt_mid_run_shows_the_jobs_cached_state(qtbot):
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes(),
                  started_at=time.time() - 20.5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    assert _has_image(tile)
    assert tile._status_scrim.text() == "Generating…"
    assert tile._bar.caption().startswith("50% · ")


def test_the_tiles_own_clock_draws_the_line_the_jobs_progress_does(qtbot):
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes(),
                  started_at=time.time() - 20.5)
    tile = GeneratingTile(job)
    qtbot.addWidget(tile)
    job.last_progress = (8, 10)

    tile._tick.timeout.emit()

    assert tile._bar.caption().startswith("80% · "), (
        "the numbers are read back off the job rather than taken from a signal: the tile's own "
        "clock re-renders on a tick that carries none, and both paths must draw the same line")


def test_right_clicking_the_tile_asks_for_its_menu(qtbot):
    tile = GeneratingTile(FakeJob(state="running"))
    qtbot.addWidget(tile)
    asked = []
    tile.context_requested.connect(appending_to(asked))

    tile.customContextMenuRequested.emit(QPoint(5, 5))

    assert len(asked) == 1
