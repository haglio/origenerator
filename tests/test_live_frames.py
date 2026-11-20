from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image
from PySide6.QtGui import QImage

from origenerator.gui import live_frames
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.inflight import RunReading
from origenerator.gui.item_tile import ItemTile
from origenerator.gui.viewport import Viewport
from tests.test_generating_tile import FakeJob


def _frame(shade: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), (shade, 40, 90)).save(buffer, "PNG")
    return buffer.getvalue()


def _counting_decodes(monkeypatch) -> list[int]:
    decoded: list[int] = []

    class Counted:
        @staticmethod
        def fromData(data):
            decoded.append(len(data))
            return QImage.fromData(data)

    monkeypatch.setattr(live_frames, "QImage", Counted)
    live_frames.decoded.cache_clear()
    return decoded


def test_a_frame_shown_on_its_tile_its_tab_and_its_enhancing_tile_is_decoded_once(
        qtbot, monkeypatch):
    decoded = _counting_decodes(monkeypatch)
    frame = _frame(201)
    job = FakeJob(state="running")
    tile = GeneratingTile(job)
    viewport = Viewport(player=MagicMock(), make_player=lambda _parent: MagicMock())
    enhancing = ItemTile("i1", None, "item one")
    for widget in (tile, viewport, enhancing):
        qtbot.addWidget(widget)

    job.preview.emit(frame)
    viewport.show_frame(frame)
    enhancing.set_enhancing(RunReading(status="running", frame=frame))

    assert len(decoded) == 1, (
        "ComfyUI sends several frames a second, and each one is decoded once however many "
        "places show it")


def test_a_frame_that_cannot_be_read_is_no_image():
    assert live_frames.decoded(b"not an image") is None
