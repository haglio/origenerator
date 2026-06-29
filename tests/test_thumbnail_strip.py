import json

from origenerator.db import Database
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.gui.thumbnail_widget import ThumbnailWidget


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
