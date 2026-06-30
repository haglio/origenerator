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


def _insert(db, prompt_id, prompt, seed):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, negative_prompt="", seed=seed,
        params_json=json.dumps({"positive_prompt": prompt, "seed": seed}),
        workflow_json="{}",
    )


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
