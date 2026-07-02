import io

from PIL import Image
from PyQt6.QtCore import Qt

from origenerator.gui.inflight_card import InFlightItem, InFlightCard
from origenerator.gui.media_badge import MediaBadge


def _png_bytes(color=(200, 50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _item(**kw):
    base = dict(key="p1", caption="SDXL › a cat", status="queued",
                frame=None, reveal=lambda: None)
    base.update(kw)
    return InFlightItem(**base)


def test_card_shows_queued_placeholder_without_a_frame(qtbot):
    card = InFlightCard(_item(status="queued"))
    qtbot.addWidget(card)
    assert card._image.text() == "Queued…"
    assert card._caption.text() == "SDXL › a cat"


def test_card_shows_generating_placeholder_when_running_without_a_frame(qtbot):
    card = InFlightCard(_item(status="running"))
    qtbot.addWidget(card)
    assert card._image.text() == "Generating…"


def test_card_shows_the_live_frame_when_one_is_present(qtbot):
    card = InFlightCard(_item(status="running", frame=_png_bytes()))
    qtbot.addWidget(card)
    assert not card._image.pixmap().isNull()  # the placeholder gave way to the frame


def test_media_badge_shows_only_when_the_item_names_a_type(qtbot):
    # An in-flight card on the Recents shelf wears the same image/video badge as a
    # finished tile, so a queued video reads as a video before its first frame.
    plain = InFlightCard(_item())                    # no type known → no badge
    qtbot.addWidget(plain)
    assert plain.findChildren(MediaBadge) == []
    badged = InFlightCard(_item(media_type="video"))
    qtbot.addWidget(badged)
    assert len(badged.findChildren(MediaBadge)) == 1


def test_clicking_the_card_emits_its_key(qtbot):
    card = InFlightCard(_item(key="job-7"))
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.clicked) as sig:
        qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    assert sig.args == ["job-7"]


def test_update_item_refreshes_caption_and_frame_in_place(qtbot):
    card = InFlightCard(_item(status="queued"))
    qtbot.addWidget(card)
    assert card._image.text() == "Queued…"

    card.update_item(_item(caption="new caption", status="running", frame=_png_bytes()))
    assert card._caption.text() == "new caption"
    assert not card._image.pixmap().isNull()
