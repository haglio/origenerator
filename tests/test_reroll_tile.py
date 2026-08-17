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

    def __init__(self, state="queued", last_progress=(0, 0), last_preview=None):
        super().__init__()
        self._state = state
        self._last_progress = last_progress
        self._last_preview = last_preview

    @property
    def state(self):
        return self._state

    @property
    def last_progress(self):
        return self._last_progress

    @property
    def last_preview(self):
        return self._last_preview


def _has_image(tile):
    return not tile._image.pixmap().isNull()


def test_idle_tile_shows_plus_and_hides_cancel(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    assert tile._image.text() == "+"
    assert tile._cancel.isHidden()


def test_idle_tile_emits_add_requested_on_click(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert clicks == [True]


def test_active_queued_tile_shows_waiting_with_cancel(qtbot):
    tile = RerollTile(FakeJob(state="queued"))
    qtbot.addWidget(tile)
    assert tile._status.text() == "Waiting…"
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


def test_started_signal_switches_status_to_generating(qtbot):
    job = FakeJob(state="queued")
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    job.started.emit()
    assert tile._status.text().startswith("Generating")


def test_progress_signal_shows_percentage(qtbot):
    job = FakeJob(state="queued")
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    job.progress.emit(3, 10)
    assert tile._status.text() == "Generating… 30%"


def test_preview_signal_renders_image(qtbot):
    job = FakeJob(state="queued")
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    assert not _has_image(tile)
    job.preview.emit(_png_bytes())
    assert _has_image(tile)


def test_tile_rebinds_to_running_job_from_cached_state(qtbot):
    # A tile rebuilt mid-run (navigation/poll) must show the job's current state.
    job = FakeJob(state="running", last_progress=(5, 10), last_preview=_png_bytes())
    tile = RerollTile(job)
    qtbot.addWidget(tile)
    assert _has_image(tile)
    assert tile._status.text() == "Generating… 50%"
