import json
import logging

import pytest

from origenerator.workflows import stroke_aim


def test_aim_fractions_map_the_box_to_column_span_and_base():
    # A anchor box at (200, 300) sized 100x500 in a 1000x1000 image: the track
    # column runs through the box center; the stroke spans the gripped length
    # (18%..72% of the box); the anchor pins the base (93%).
    aim = stroke_aim.aim_fractions_from_box((200, 300, 100, 500), 1000, 1000)
    assert aim["stroke_x"] == pytest.approx(0.25)
    assert aim["anchor_x"] == pytest.approx(0.25)
    assert aim["stroke_top"] == pytest.approx((300 + 0.18 * 500) / 1000)
    assert aim["stroke_bottom"] == pytest.approx((300 + 0.72 * 500) / 1000)
    assert aim["anchor_y"] == pytest.approx((300 + 0.93 * 500) / 1000)


def test_detect_grip_aim_picks_the_most_confident_anchor(monkeypatch, tmp_path):
    from PIL import Image

    frame = tmp_path / "frame.png"
    Image.new("RGB", (200, 400)).save(frame)
    monkeypatch.setattr(stroke_aim, "_detect", lambda path: [
        {"class": "LABEL_OTHER", "score": 0.9, "box": (0, 0, 10, 10)},
        {"class": "ANCHOR_EXPOSED", "score": 0.4, "box": (10, 20, 30, 40)},
        {"class": "ANCHOR_EXPOSED", "score": 0.8, "box": (50, 100, 60, 200)},
    ])
    aim = stroke_aim.detect_grip_aim(frame)
    assert aim["stroke_x"] == pytest.approx((50 + 30) / 200)  # the 0.8 box wins
    assert aim["stroke_top"] == pytest.approx((100 + 0.18 * 200) / 400)


def test_detect_grip_aim_returns_none_when_nothing_usable(monkeypatch, tmp_path):
    from PIL import Image

    frame = tmp_path / "frame.png"
    Image.new("RGB", (10, 10)).save(frame)
    monkeypatch.setattr(stroke_aim, "_detect", lambda path: [
        {"class": "ANCHOR_EXPOSED", "score": 0.2, "box": (1, 1, 2, 2)},  # sub-threshold
    ])
    assert stroke_aim.detect_grip_aim(frame) is None
    assert stroke_aim.detect_grip_aim(None) is None

    def boom(path):
        raise RuntimeError("model missing")

    monkeypatch.setattr(stroke_aim, "_detect", boom)
    assert stroke_aim.detect_grip_aim(frame) is None  # best-effort, never raises


class TestAnOverlayThatIsMissingTheDetectorLabels:
    """The labels are library vocabulary, so they come from the git-ignored
    overlay — which replaces the committed example rather than merging with it,
    and so must carry every key that one does. Read at module scope, an overlay
    written before `detector_labels` existed took the whole app down with a bare
    KeyError, at import, saying neither which key nor which file.

    tests/test_content.py holds the other half: the same overlay, imported.
    """

    @pytest.fixture
    def incomplete(self, tmp_path, monkeypatch):
        """The committed example with `detector_labels` taken out of it."""
        from origenerator import content

        example = json.loads(content.EXAMPLE_CONTENT.read_text(encoding="utf-8"))
        example.pop("detector_labels")
        overlay = tmp_path / "content.local.json"
        overlay.write_text(json.dumps(example), encoding="utf-8")
        monkeypatch.setattr(content, "LOCAL_CONTENT", overlay)
        content.load_content.cache_clear()
        stroke_aim._detector_labels.cache_clear()
        yield overlay
        content.load_content.cache_clear()
        stroke_aim._detector_labels.cache_clear()

    def test_reading_the_labels_names_the_key_and_the_file(self, incomplete):
        from origenerator.content import MissingOverlayKey

        with pytest.raises(MissingOverlayKey) as refused:
            stroke_aim._detector_labels()

        assert "detector_labels" in str(refused.value)
        assert str(incomplete) in str(refused.value)

    def test_auto_aim_is_lost_and_nothing_else_is(self, incomplete, monkeypatch,
                                                  tmp_path, caplog):
        """The module's own documented failure mode: any failure returns None
        and the caller falls back to its manual numbers. What is NEW is that it
        reaches that path at all — before, the app was gone at import."""
        from PIL import Image

        frame = tmp_path / "frame.png"
        Image.new("RGB", (200, 400)).save(frame)
        monkeypatch.setattr(stroke_aim, "_detect", lambda path: [
            {"class": "ANCHOR_EXPOSED", "score": 0.8, "box": (50, 100, 60, 200)},
        ])

        with caplog.at_level(logging.WARNING):
            assert stroke_aim.detect_grip_aim(frame) is None

        assert "detector_labels" in caplog.text
