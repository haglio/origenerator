import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.db import Database
from origenerator.gui.gallery_view import GalleryView, _GROUP_ROLE
from origenerator.gui.preview_widget import PreviewWidget


@pytest.fixture(autouse=True)
def _stub_preview_resolution(monkeypatch):
    """Keep gallery_view unit tests off the real filesystem and media backend.

    Preview resolution is exercised in test_gallery.py and rendering in
    test_preview_widget.py; here it defaults to "nothing to show" so a real
    PreviewWidget never starts WMF playback (which deadlocks at teardown).
    Tests that assert routing override this with their own return value.
    """
    monkeypatch.setattr(gallery, "resolve_preview", lambda row, output_dir: None)


class FakeDB:
    """In-memory stand-in for Database covering the methods the view calls."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._by_id = {r["prompt_id"]: r for r in rows}
        self._meta = {}

    def list_generations(self):
        return list(self._rows)

    def get_generation(self, prompt_id):
        return self._by_id.get(prompt_id)

    def folder_meta_map(self):
        return {k: dict(v) for k, v in self._meta.items()}

    def rename_folder(self, key, custom_name):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["custom_name"] = custom_name

    def set_folder_starred(self, key, starred):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["starred"] = bool(starred)

    def add(self, row):  # test helper: simulate a new generation landing
        self._rows.insert(0, row)
        self._by_id[row["prompt_id"]] = row


def _row(prompt_id, workflow_name, params, filename, **extra):
    row = {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "workflow_version": "v1",
        "status": "completed",
        "source": "generated",
        "seed": params.get("seed"),
        "created_at": "2026-01-01",
        "positive_prompt": params.get("positive_prompt", ""),
        "negative_prompt": "",
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": filename, "subfolder": ""}]),
        "thumbnail_path": None,
    }
    row.update(extra)
    return row


def _image(prompt_id, prompt, steps, seed):
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"sdxl_t2i_{prompt_id}.png")


def _top_level(tree):
    return {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}


def _key(item):
    return item.data(0, _GROUP_ROLE).key


def test_refresh_builds_media_workflow_settings_tree(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),  # same settings, different seed
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
             "wan22_i2v_00001_.mp4"),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    top = _top_level(view._tree)
    assert set(top) == {"Images", "Videos"}

    workflow_node = top["Images"].child(0)
    assert workflow_node.text(0) == "SDXL Text-to-Image"
    # The two seed variants collapse into a single settings folder.
    assert workflow_node.childCount() == 1


def test_selecting_a_folder_shows_its_full_name_as_a_title(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    # The title carries the full breadcrumb, which the narrow tree truncates.
    assert "SDXL Text-to-Image" in view._title.text()
    assert "Images" in view._title.text()


def test_branch_shows_folder_tiles_and_leaf_shows_thumbnails(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),
        _image("i3", "a dog", 50, 1),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    # A branch folder shows its sub-folders as tiles, not loose thumbnails.
    view._tree.setCurrentItem(workflow)
    assert len(view.visible_folder_keys()) == 2
    assert view.visible_prompt_ids() == []

    # A leaf (settings) folder shows the actual item thumbnails.
    cat_leaf = workflow.child(0)
    view._tree.setCurrentItem(cat_leaf)
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}
    assert view.visible_folder_keys() == []


def test_clicking_a_folder_tile_drills_into_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    a_tile_key = view.visible_folder_keys()[0]

    view._drill_into(a_tile_key)  # same path the tile's clicked signal triggers
    assert view.visible_prompt_ids()  # now showing that folder's thumbnails


def test_renaming_a_folder_persists_and_relabels_it(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    key = _key(workflow)
    view._apply_rename(key, "Best Models")

    assert db.folder_meta_map()[key]["custom_name"] == "Best Models"
    assert _top_level(view._tree)["Images"].child(0).text(0) == "Best Models"


def test_starring_a_folder_persists_and_floats_it_to_top(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    dog_key = _key(workflow.child(1))  # cat is first, dog second
    view._toggle_star(dog_key)

    assert db.folder_meta_map()[dog_key]["starred"] is True
    workflow = _top_level(view._tree)["Images"].child(0)
    assert _key(workflow.child(0)) == dog_key          # floated above the cat
    assert workflow.child(0).text(0).startswith("★")


def test_new_generations_appear_without_manual_refresh(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    assert set(_top_level(view._tree)) == {"Images"}

    # A new video lands in the DB; a poll tick reflects it with no Refresh button.
    db.add(_row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
                "wan22_i2v_00001_.mp4"))
    view._poll()
    assert set(_top_level(view._tree)) == {"Images", "Videos"}


def test_i2v_thumbnail_links_to_source_image_and_navigates(qtbot):
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()

    # Viewing the video surfaces a link to the image it was built from.
    view._on_thumbnail_clicked("vid1")
    assert view.current_source_image_id() == "img1"
    assert "sdxl_t2i_img1.png" in view._source_link.text()

    # Activating that link navigates the gallery to the source image.
    view._on_source_link("img1")
    assert "img1" in view.visible_prompt_ids()
    assert view._selected["prompt_id"] == "img1"
    # The image itself has no input image, so the link disappears.
    assert view.current_source_image_id() is None


def test_clicking_thumbnail_shows_resolved_preview(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.show_media = MagicMock()
    resolved = (Path("C:/out/sdxl_t2i_i1.png"), "image")
    resolve = MagicMock(return_value=resolved)
    monkeypatch.setattr(gallery, "resolve_preview", resolve)

    view._on_thumbnail_clicked("i1")

    resolve.assert_called_once_with(view._selected, COMFYUI_OUTPUT_DIR)
    view._preview.show_media.assert_called_once_with(resolved[0], "image")


def test_clicking_thumbnail_without_media_clears_preview(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.clear = MagicMock()
    view._preview.show_media = MagicMock()
    monkeypatch.setattr(gallery, "resolve_preview", MagicMock(return_value=None))

    view._on_thumbnail_clicked("i1")

    view._preview.clear.assert_called_once()
    view._preview.show_media.assert_not_called()


def test_gallery_creates_a_preview_widget(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert isinstance(view._preview, PreviewWidget)


def _make_db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="p1",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt="a cat",
        negative_prompt="blurry",
        seed=7,
        params_json=json.dumps({"steps": 20}),
        workflow_json="{}",
    )
    return db


def test_reuse_emits_merged_params(qtbot, tmp_path):
    db = _make_db(tmp_path)
    view = GalleryView(db)
    qtbot.addWidget(view)

    view._on_thumbnail_clicked("p1")
    with qtbot.waitSignal(view.reuse_requested) as blocker:
        view._on_reuse()

    workflow_name, params = blocker.args
    assert workflow_name == "sdxl_t2i"
    assert params == {
        "steps": 20,
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "seed": 7,
    }
