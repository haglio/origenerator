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


def _widgets(strip):
    return [strip._list.itemAt(i).widget() for i in range(strip._list.count())]


def test_refresh_builds_one_widget_per_generation_newest_first(qtbot, tmp_path):
    db = _seed_db(tmp_path, 3)
    strip = ThumbnailStrip(db)
    qtbot.addWidget(strip)
    widgets = _widgets(strip)
    assert all(isinstance(w, ThumbnailWidget) for w in widgets)
    assert [w.prompt_id for w in widgets] == ["p2", "p1", "p0"]


def test_clicking_thumbnail_emits_activated_with_prompt_id(qtbot, tmp_path):
    db = _seed_db(tmp_path, 2)
    strip = ThumbnailStrip(db)
    qtbot.addWidget(strip)
    first = _widgets(strip)[0]
    with qtbot.waitSignal(strip.thumbnail_activated) as blocker:
        first.clicked.emit(first.prompt_id)
    assert blocker.args == [first.prompt_id]


def test_refresh_picks_up_new_generations(qtbot, tmp_path):
    db = _seed_db(tmp_path, 1)
    strip = ThumbnailStrip(db)
    qtbot.addWidget(strip)
    assert len(_widgets(strip)) == 1
    db.insert_generation(
        prompt_id="p-new",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        params_json="{}",
        workflow_json="{}",
    )
    strip.refresh()
    assert [w.prompt_id for w in _widgets(strip)] == ["p-new", "p0"]
