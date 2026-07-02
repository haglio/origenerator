import json

from PIL import Image
from PyQt6.QtGui import QMovie

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.db import Database
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.gui.thumbnail_widget import ThumbnailWidget


def _write_looping_webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def _seed_db(tmp_path, n):
    db = Database(tmp_path / "test.db")
    for i in range(n):
        db.insert_generation(
            prompt_id=f"p{i}",
            workflow_name="sdxl_t2i",
            workflow_version="v002",
            positive_prompt=f"prompt {i}",
            negative_prompt="",
            seed=i,
            params_json=json.dumps({"seed": i}),
            workflow_json="{}",
        )
    return db


def _ids(strip):
    return [strip._list.itemAt(i).widget().prompt_id for i in range(strip._list.count())]


def test_strip_starts_empty(qtbot, tmp_path):
    strip = ThumbnailStrip(_seed_db(tmp_path, 3))
    qtbot.addWidget(strip)
    assert _ids(strip) == []


def test_show_generations_lists_given_ids_in_order(qtbot, tmp_path):
    strip = ThumbnailStrip(_seed_db(tmp_path, 3))
    qtbot.addWidget(strip)
    strip.show_generations(["p2", "p0"])
    widgets = [strip._list.itemAt(i).widget() for i in range(strip._list.count())]
    assert all(isinstance(w, ThumbnailWidget) for w in widgets)
    assert _ids(strip) == ["p2", "p0"]


def test_show_generations_skips_unknown_ids(qtbot, tmp_path):
    strip = ThumbnailStrip(_seed_db(tmp_path, 1))
    qtbot.addWidget(strip)
    strip.show_generations(["p0", "missing"])
    assert _ids(strip) == ["p0"]


def test_clicking_thumbnail_emits_activated_with_prompt_id(qtbot, tmp_path):
    strip = ThumbnailStrip(_seed_db(tmp_path, 2))
    qtbot.addWidget(strip)
    strip.show_generations(["p1", "p0"])
    first = strip._list.itemAt(0).widget()
    with qtbot.waitSignal(strip.thumbnail_activated) as blocker:
        first.clicked.emit(first.prompt_id)
    assert blocker.args == ["p1"]


def _insert(db, prompt_id, prompt, seed):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, negative_prompt="", seed=seed,
        params_json=json.dumps({"positive_prompt": prompt, "seed": seed}),
        workflow_json="{}",
    )


def test_video_rows_animate_their_thumbnail(qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    db = Database(tmp_path / "v.db")
    db.insert_generation(
        prompt_id="v1", workflow_name="wan22_i2v", workflow_version="v1",
        positive_prompt="dance", negative_prompt="", seed=1,
        params_json=json.dumps({"seed": 1}), workflow_json="{}",
    )
    db.update_generation(
        "v1", status="completed",
        output_files=json.dumps([{"filename": "wan22_i2v_v1.mp4"}]),
    )
    calls = []

    def fake_anim(row, output_dir, thumb_dir):
        calls.append((row["prompt_id"], output_dir, thumb_dir))
        return str(webp)

    monkeypatch.setattr(gallery, "animated_preview_path", fake_anim)
    strip = ThumbnailStrip(db)
    qtbot.addWidget(strip)
    strip.show_generations(["v1"])

    tile = strip._list.itemAt(0).widget()
    assert tile.findChildren(QMovie)  # the video thumbnail loops
    assert ("v1", COMFYUI_OUTPUT_DIR, THUMB_DIR) in calls  # via the shared resolver


def test_hovering_highlights_thumbnails_with_matching_settings(qtbot, tmp_path):
    db = Database(tmp_path / "h.db")
    _insert(db, "cat1", "cat", 1)
    _insert(db, "cat2", "cat", 2)   # same settings as cat1 (only the seed differs)
    _insert(db, "dog1", "dog", 1)
    strip = ThumbnailStrip(db)
    qtbot.addWidget(strip)
    strip.show_generations(["cat1", "cat2", "dog1"])
    w = {x.prompt_id: x for x in strip._widgets}

    w["cat1"].hovered.emit("cat1")
    assert w["cat1"].is_highlighted() and w["cat2"].is_highlighted()
    assert not w["dog1"].is_highlighted()

    w["cat1"].unhovered.emit("cat1")
    assert not any(x.is_highlighted() for x in strip._widgets)
