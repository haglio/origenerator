import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QSplitter, QLabel, QLineEdit

from origenerator import evolver_export, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.folder_tree import BRANCH_STAR_ROLE
from origenerator.gui.gallery_view import GalleryView, _GROUP_ROLE
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_tile import RerollTile
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]
_WAN_I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_REROLL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}
# The two stages of a chained i2v re-roll: a fresh image, then the video on it.
_IMG_REROLL_HISTORY = {"outputs": {"7": {"images": [
    {"filename": "sdxl_new.png", "subfolder": "image", "type": "output"}]}}}
_VID_REROLL_HISTORY = {"outputs": {"19": {"images": [
    {"filename": "wan_new.mp4", "subfolder": "video", "type": "output"}]}}}

_NO_MOD = Qt.KeyboardModifier.NoModifier
_CTRL = Qt.KeyboardModifier.ControlModifier
_SHIFT = Qt.KeyboardModifier.ShiftModifier


class FakeActions:
    """Records what the view asks of its action controller."""

    def __init__(self):
        self.deleted = []   # each entry is one delete batch (list of rows)
        self.renamed = []   # (key, name) pairs
        self.undo_count = 0
        self._label = None

    def delete_rows(self, rows):
        self.deleted.append(list(rows))
        self._label = f"Delete {len(rows)} items"

    def rename_folder(self, key, name):
        self.renamed.append((key, name))
        self._label = "Rename folder"

    def undo(self):
        self.undo_count += 1
        self._label = None

    def can_undo(self):
        return self._label is not None

    def undo_label(self):
        return self._label


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

    def recent_durations(self, workflow_name, limit=10):
        return [
            r["duration_seconds"] for r in self._rows
            if r.get("workflow_name") == workflow_name
            and r.get("status") == "completed"
            and r.get("duration_seconds") is not None
        ][:limit]

    def folder_meta_map(self):
        return {k: dict(v) for k, v in self._meta.items()}

    def rename_folder(self, key, custom_name):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["custom_name"] = custom_name

    def set_folder_starred(self, key, starred):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["starred"] = bool(starred)

    def delete_generation(self, prompt_id):
        self._rows = [r for r in self._rows if r["prompt_id"] != prompt_id]
        self._by_id.pop(prompt_id, None)

    def restore_generation(self, row):
        self._rows.insert(0, row)
        self._by_id[row["prompt_id"]] = row

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


def _i2v_video(prompt_id, lora, prompt="dance", seed=1):
    """A WAN I2V video row that shares a base model but names its own LoRA, so the
    tree grows Videos -> WAN I2V -> model -> LoRA -> settings."""
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": prompt,
                 "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors",
                 "lora_high": f"{lora}_high.safetensors", "lora_low": f"{lora}_low.safetensors",
                 "seed": seed},
                f"wan22_i2v_{prompt_id}.mp4")


def _top_level(tree):
    return {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())}


def _key(item):
    return item.data(0, _GROUP_ROLE).key


def test_refresh_builds_media_workflow_model_settings_tree(qtbot):
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
    assert set(top) == {"Starred", "Images", "Videos"}

    workflow_node = top["Images"].child(0)
    assert workflow_node.text(0) == "SDXL Text-to-Image"
    # A model folder sits under the workflow; beneath it the two seed variants
    # collapse into a single settings folder.
    assert workflow_node.childCount() == 1
    assert workflow_node.child(0).childCount() == 1


def test_tree_rows_carry_a_recipe_level_badge_and_tooltip(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    videos = _top_level(view._tree)["Videos"]
    workflow = videos.child(0)
    model = workflow.child(0)
    lora = model.child(0)
    settings = lora.child(0)

    # Each recipe level shows a chip icon and names itself in the tooltip...
    assert not workflow.icon(0).isNull() and "Workflow" in workflow.toolTip(0)
    assert not model.icon(0).isNull() and "Model" in model.toolTip(0)
    assert not lora.icon(0).isNull() and "LoRA" in lora.toolTip(0)
    # ...while the media root and the settings leaf carry no badge.
    assert videos.icon(0).isNull()
    assert settings.icon(0).isNull()


def test_selecting_a_folder_shows_its_full_name_as_a_title(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    # The title carries the full breadcrumb, which the narrow tree truncates.
    assert "SDXL Text-to-Image" in view._title.display_text()
    assert "Images" in view._title.display_text()


def test_branch_shows_folder_tiles_and_leaf_shows_thumbnails(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),
        _image("i3", "a dog", 50, 1),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Images"].child(0).child(0)
    # A branch folder shows its sub-folders as tiles, not loose thumbnails.
    view._tree.setCurrentItem(model)
    assert len(view.visible_folder_keys()) == 2
    assert view.visible_prompt_ids() == []

    # A leaf (settings) folder shows the actual item thumbnails.
    cat_leaf = model.child(0)
    view._tree.setCurrentItem(cat_leaf)
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}
    assert view.visible_folder_keys() == []


def test_clicking_a_folder_tile_drills_into_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Images"].child(0).child(0)
    view._tree.setCurrentItem(model)
    a_tile_key = view.visible_folder_keys()[0]  # a settings tile under the model

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


def test_starring_a_folder_persists_without_reordering(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Images"].child(0).child(0)
    cat_key = _key(model.child(0))
    dog_key = _key(model.child(1))  # cat is first, dog second
    view._toggle_star(dog_key)

    assert db.folder_meta_map()[dog_key]["starred"] is True
    model = _top_level(view._tree)["Images"].child(0).child(0)
    # The star marks the folder in place; it does not jump above the cat.
    assert [_key(model.child(i)) for i in range(model.childCount())] == [cat_key, dog_key]
    # Starred state rides on the group (the row's star icon reads it), not a ★ text
    # prefix, so the labels stay the plain folder names.
    assert model.child(1).data(0, _GROUP_ROLE).starred is True
    assert model.child(0).data(0, _GROUP_ROLE).starred is False
    assert not model.child(1).text(0).startswith("★")


def test_starred_shelf_is_pinned_first_and_collects_starred_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Images"].child(0).child(0)
    dog_key = _key(model.child(1))
    view._toggle_star(dog_key)

    # The shelf is the very first row in the tree, above the media folders.
    assert view._tree.topLevelItem(0).text(0) == "Starred"
    # Selecting it lists a tile for each starred folder, wherever it lives.
    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_folder_keys() == [dog_key]
    assert view.visible_prompt_ids() == []


def test_starred_shelf_row_aligns_like_the_media_folders(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    shelf = view._tree.topLevelItem(0)
    # No "★ " text prefix: the star is drawn in the caret column instead, so the
    # "Starred" label lines up with "Images"/"Videos" rather than sitting a
    # chevron-width to the right of them.
    assert shelf.text(0) == "Starred"
    assert shelf.data(0, BRANCH_STAR_ROLE) is True


def test_clicking_a_starred_tile_drills_into_the_real_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Images"].child(0).child(0)
    dog_key = _key(model.child(1))
    view._toggle_star(dog_key)

    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    view._drill_into(view.visible_folder_keys()[0])  # click the starred tile
    assert set(view.visible_prompt_ids()) == {"i2"}  # now inside the dog folder


def test_starred_shelf_shows_empty_state_when_nothing_is_starred(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_folder_keys() == []   # no tiles, just the hint
    assert view.visible_prompt_ids() == []


def test_starred_shelf_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Starred"])

    view.refresh()  # a poll-driven rebuild must not knock us off the shelf

    assert view._tree.currentItem().text(0) == "Starred"


def test_starred_shelf_is_absent_until_a_folder_exists(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()
    assert "Starred" not in _top_level(view._tree)


def test_new_generations_appear_without_manual_refresh(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    assert set(_top_level(view._tree)) == {"Starred", "Images"}

    # A new video lands in the DB; a poll tick reflects it with no Refresh button.
    db.add(_row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
                "wan22_i2v_00001_.mp4"))
    view._poll()
    assert set(_top_level(view._tree)) == {"Starred", "Images", "Videos"}


def test_folders_start_collapsed(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    images = _top_level(view._tree)["Images"]
    assert images.isExpanded() is False
    assert images.child(0).isExpanded() is False


def test_selecting_a_folder_auto_selects_its_first_item(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    # Selecting a branch folder immediately previews its first item...
    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    assert view._selected["prompt_id"] == "i1"

    # ...and so does selecting a leaf folder (workflow -> model -> settings).
    view._tree.setCurrentItem(workflow.child(0).child(0))
    assert view._selected["prompt_id"] == "i1"


def test_double_clicking_a_tree_folder_renames_it_in_place(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    key = _key(workflow)

    view._begin_inline_rename(workflow, 0)   # double-click opens the editor
    workflow.setText(0, "Models")            # committing fires itemChanged

    assert db.folder_meta_map()[key]["custom_name"] == "Models"
    view.refresh()
    assert _top_level(view._tree)["Images"].child(0).text(0) == "Models"


def test_double_clicking_the_header_renames_the_selected_folder(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    key = _key(workflow)

    view._title.edit_requested.emit()  # double-clicking the header starts editing
    assert view._title._edit.text() == "SDXL Text-to-Image"  # prefilled with the name
    view._title.edited.emit("Favorites")  # commit

    assert db.folder_meta_map()[key]["custom_name"] == "Favorites"
    assert _top_level(view._tree)["Images"].child(0).text(0) == "Favorites"


def _meta_link_texts(view):
    return [l.text() for l in view._meta_panel.findChildren(QLabel)]


def test_i2v_input_image_links_to_source_image_and_navigates(qtbot):
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()

    # Viewing the video renders its input_image (among the other params) as a link
    # to the image it was built from — not a separate line of its own.
    view._on_thumbnail_clicked("vid1")
    assert any('href="img1"' in t for t in _meta_link_texts(view))

    # Activating that link navigates the gallery to the source image.
    view._meta_panel.link_activated.emit("img1")
    assert "img1" in view.visible_prompt_ids()
    assert view._selected["prompt_id"] == "img1"
    # The image itself has no input image, so nothing renders as a link.
    view._on_thumbnail_clicked("img1")
    assert not any("href=" in t for t in _meta_link_texts(view))


def test_back_and_forward_walk_the_viewed_generations(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._thumbnail_clicked("i1")
    view._thumbnail_clicked("i2")
    assert view._selected["prompt_id"] == "i2"

    view._go_back()
    assert view._selected["prompt_id"] == "i1"
    view._go_forward()
    assert view._selected["prompt_id"] == "i2"


def test_back_returns_from_a_followed_input_image_link_to_the_video(qtbot):
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    view._thumbnail_clicked("vid1")   # viewing the video
    view._on_source_link("img1")      # follow its input-image link

    assert view._selected["prompt_id"] == "img1"
    view._go_back()
    assert view._selected["prompt_id"] == "vid1"


def test_nav_buttons_enable_only_when_there_is_somewhere_to_go(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._back_btn.isEnabled() and not view._forward_btn.isEnabled()

    view._thumbnail_clicked("i1")
    view._thumbnail_clicked("i2")
    assert view._back_btn.isEnabled() and not view._forward_btn.isEnabled()

    view._go_back()
    assert not view._back_btn.isEnabled() and view._forward_btn.isEnabled()


def test_toolbar_is_a_group_of_compact_icon_buttons(qtbot):
    from PyQt6.QtWidgets import QToolButton
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    # Back, forward, undo and delete are one group of icon-only tool buttons, not
    # the oversized text buttons that split them across the header.
    for btn in (view._back_btn, view._forward_btn, view._undo_btn, view._delete_btn):
        assert isinstance(btn, QToolButton)
        assert not btn.icon().isNull()
        assert btn.text() == ""


def test_delete_button_enables_for_a_selection_or_a_deletable_folder(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    images = _top_level(view._tree)["Images"]  # a media group — not deletable, nothing picked
    view._tree.setCurrentItem(images)
    assert not view._delete_btn.isEnabled()

    _select_first_leaf(view)                    # a settings folder — deletable
    assert view._delete_btn.isEnabled()

    view._thumbnail_clicked("i1")               # a picked thumbnail — deletable
    assert view._delete_btn.isEnabled()


def test_delete_button_deletes_the_picked_thumbnails(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._thumbnail_clicked("i1")

    view._delete_btn.click()

    assert actions.deleted and {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


def test_undo_of_a_folder_delete_returns_to_that_folder(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    for pid, prompt, steps in (("a", "alpha", 10), ("b", "beta", 20)):  # two settings folders
        db.insert_generation(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, seed=1,
                             params_json=json.dumps({"positive_prompt": prompt, "seed": 1, "steps": steps}),
                             workflow_json="{}")
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"{pid}.png", "subfolder": ""}]))
    actions = GalleryActions(db, tmp_path / "out", Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["a"])  # the folder holding "a"
    view._confirm = lambda text: True
    view._delete_folder(view._current_deletable_folder())
    assert db.get_generation("a") is None
    assert view._selected["prompt_id"] != "a"          # navigated off the emptied folder

    view._undo()
    assert db.get_generation("a") is not None            # restored
    assert view._selected["prompt_id"] == "a"            # and back where we deleted from


def test_back_after_following_a_link_returns_to_the_initial_view(qtbot):
    # The gallery opens on a generation the user never "clicked"; Back must still
    # return there after their first move is following a link.
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    assert view._selected["prompt_id"] == "vid1"  # opened here, unprompted

    view._on_source_link("img1")                  # first move: follow the link
    assert view._selected["prompt_id"] == "img1"
    view._go_back()
    assert view._selected["prompt_id"] == "vid1"  # Back to where it opened


def test_history_spans_folder_navigation(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])  # browse to the video folder
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # then to the image folder
    assert view._selected["prompt_id"] == "i1"

    view._go_back()
    assert view._selected["prompt_id"] == "v1"  # Back walks folder moves, not just clicks


def test_selecting_an_image_lists_the_videos_it_was_animated_into(qtbot):
    from origenerator.gui.animated_strip import _VideoTile
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, video]))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("img1")
    assert not view._animated_strip.isHidden()
    assert len(view._animated_strip.findChildren(_VideoTile)) == 1

    # Clicking the preview navigates to that video.
    view._animated_strip.video_activated.emit("vid1")
    assert view._selected["prompt_id"] == "vid1"


def test_animation_strip_is_hidden_for_a_video_or_an_unanimated_image(qtbot):
    from origenerator.gui.animated_strip import _VideoTile
    image = _image("img1", "a cat", 50, 1)
    lonely = _image("img2", "a dog", 50, 2)  # never animated
    video = _row("vid1", "wan22_i2v",
                 {"input_image": "sdxl_t2i_img1.png"}, "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, lonely, video]))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("vid1")   # a video isn't "animated into" anything
    assert view._animated_strip.isHidden()

    view._on_thumbnail_clicked("img2")   # an image nothing was made from
    assert view._animated_strip.isHidden()
    assert view._animated_strip.findChildren(_VideoTile) == []


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


def test_gallery_panes_sit_in_a_draggable_splitter(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    splitter = view._panes

    # The three panes share one horizontal splitter, so the dividers drag-resize.
    assert isinstance(splitter, QSplitter)
    assert splitter.count() == 3                            # TOC, browser, info pane
    assert not splitter.childrenCollapsible()               # none can be dragged shut
    assert splitter.widget(0).isAncestorOf(view._tree)      # TOC pane holds the folder tree
    assert splitter.widget(1).isAncestorOf(view._scroll)    # browser holds the contents
    assert splitter.widget(2).isAncestorOf(view._preview)   # info pane holds the preview


def test_info_pane_keeps_a_comfortable_minimum_width(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    # Long metadata values wrap rather than scroll sideways, so this floor keeps
    # the info pane readable without a sideways scrollbar. It's lower than it once
    # was so the whole window can still tile into a narrow monitor slot, but it
    # must never collapse to a cramped strip.
    assert view._panes.widget(2).minimumWidth() >= 280


def test_selected_folder_returns_current_folder_key(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    assert view.selected_folder() == _key(workflow)


def test_select_folder_restores_choice_in_a_fresh_view(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    saved = GalleryView(db)
    qtbot.addWidget(saved)
    saved.refresh()
    # Images -> SDXL workflow -> model -> dog settings leaf (cat is sibling 0).
    dog_leaf = _top_level(saved._tree)["Images"].child(0).child(0).child(1)
    saved._tree.setCurrentItem(dog_leaf)
    saved_key = saved.selected_folder()
    chosen = set(saved.visible_prompt_ids())

    # A brand-new view told to restore that key lands on the same folder.
    restored = GalleryView(db)
    qtbot.addWidget(restored)
    restored.select_folder(saved_key)
    restored.refresh()
    assert restored.selected_folder() == saved_key
    assert set(restored.visible_prompt_ids()) == chosen


def test_select_folder_falls_back_to_default_when_key_gone(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("video/ghost")  # nothing in the tree matches
    view.refresh()
    assert view.selected_folder() is not None  # default folder, not a crash


def test_selected_folder_reports_pending_target_before_first_show(qtbot):
    # The window restores a folder, but the user never opens the Gallery tab;
    # selected_folder must still report it so closeEvent can persist it again.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("image/sdxl_t2i")
    assert view.selected_folder() == "image/sdxl_t2i"


def test_selected_generation_tracks_thumbnail_click(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # folder holding i1 and i2
    view._on_thumbnail_clicked("i2")
    assert view.selected_generation() == "i2"


def test_select_generation_restored_with_folder_after_refresh(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    probe = GalleryView(db)
    qtbot.addWidget(probe)
    probe.refresh()
    probe._tree.setCurrentItem(probe._leaf_by_id["i1"])
    folder_key = probe.selected_folder()

    # A fresh view restoring that folder + selection lands on the same image.
    fresh = GalleryView(db)
    qtbot.addWidget(fresh)
    fresh.select_folder(folder_key)
    fresh.select_generation("i2")
    fresh.refresh()
    assert fresh.selected_generation() == "i2"
    assert fresh._selected["prompt_id"] == "i2"


def test_selected_generation_survives_a_rebuild(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    view._on_thumbnail_clicked("i2")

    db.add(_image("i3", "a dog", 50, 9))  # new generation → a poll rebuild
    view._poll()

    assert view.selected_generation() == "i2"  # not cleared by the rebuild
    assert view._selected["prompt_id"] == "i2"


def test_selected_generation_reports_pending_before_show(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("i1")
    assert view.selected_generation() == "i1"


def test_select_generation_missing_id_is_dropped(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("ghost")  # no such generation
    view.refresh()
    # Quietly dropped (not restored) without crashing; the view falls back to
    # the folder's own default selection rather than the stale id.
    assert view.selected_generation() != "ghost"


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


def test_double_clicking_a_thumbnail_reuses_its_parameters(qtbot, tmp_path):
    db = _make_db(tmp_path)
    view = GalleryView(db)
    qtbot.addWidget(view)

    # Double-clicking is the same "open it as a Generate tab" gesture as picking
    # the item and clicking Reuse Parameters.
    with qtbot.waitSignal(view.reuse_requested) as blocker:
        view._thumbnail_double_clicked("p1")

    workflow_name, params = blocker.args
    assert workflow_name == "sdxl_t2i"
    assert params == {
        "steps": 20,
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "seed": 7,
    }


def test_double_clicking_an_unregistered_thumbnail_does_not_reuse(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="unreg", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    view = GalleryView(db)
    qtbot.addWidget(view)
    fired = []
    view.reuse_requested.connect(lambda *a: fired.append(a))

    # No template exists for this workflow, so the gesture is inert — the same
    # gate that greys out the Reuse button.
    view._thumbnail_double_clicked("unreg")

    assert fired == []


def test_reuse_disabled_for_unregistered_workflow_with_hint(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="reg", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", params_json=json.dumps({"steps": 20}),
        workflow_json="{}",
    )
    db.insert_generation(
        prompt_id="unreg", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    view = GalleryView(db)
    qtbot.addWidget(view)

    view._on_thumbnail_clicked("reg")  # a built-in workflow → reusable
    assert view._reuse_btn.isEnabled() is True

    view._on_thumbnail_clicked("unreg")  # no template for it → greyed out
    assert view._reuse_btn.isEnabled() is False
    # The hint rides on the wrapper, since a disabled button shows no tooltip.
    assert "claude" in view._reuse_wrap.toolTip().lower()


def _video_resolver(video_path):
    """A resolve_preview stub: a real video file for video rows, a still else."""
    def resolve(row, output_dir):
        if gallery.media_type_of_row(row) == "video":
            return (video_path, "video")
        return (Path("C:/out/still.png"), "image")
    return resolve


def test_send_to_evolver_button_shows_only_for_a_video(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.show_media = MagicMock()  # don't start real WMF playback
    monkeypatch.setattr(gallery, "resolve_preview",
                        _video_resolver(Path("C:/out/wan22_i2v_v1.mp4")))

    view._on_thumbnail_clicked("v1")   # a video with a file on disk
    assert view._evolver_btn.isHidden() is False

    view._on_thumbnail_clicked("i1")   # an image — Evolver is a video pipeline
    assert view._evolver_btn.isHidden() is True


def test_send_to_evolver_button_hidden_when_the_video_file_is_gone(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    # No displayable file resolves (the output was deleted): nothing to send.
    monkeypatch.setattr(gallery, "resolve_preview", lambda row, output_dir: None)

    view._on_thumbnail_clicked("v1")
    assert view._evolver_btn.isHidden() is True


def test_send_to_evolver_copies_the_selected_video_to_the_inbox(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.show_media = MagicMock()  # don't start real WMF playback
    video_path = Path("C:/out/wan22_i2v_v1.mp4")
    monkeypatch.setattr(gallery, "resolve_preview", _video_resolver(video_path))
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / EVOLVER_SOURCE / "wan22_i2v_v1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    view._on_thumbnail_clicked("v1")
    view._on_send_to_evolver()

    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)


def test_send_to_evolver_warns_and_survives_a_failed_copy(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.show_media = MagicMock()  # don't start real WMF playback
    monkeypatch.setattr(gallery, "resolve_preview",
                        _video_resolver(Path("C:/out/wan22_i2v_v1.mp4")))
    monkeypatch.setattr(evolver_export, "export_video",
                        MagicMock(side_effect=OSError("inbox unreachable")))
    warn = MagicMock()
    monkeypatch.setattr(gallery_view_module.QMessageBox, "warning", warn)

    view._on_thumbnail_clicked("v1")
    view._on_send_to_evolver()  # must not raise

    warn.assert_called_once()


def test_selecting_generation_shows_typical_time_for_its_workflow(qtbot):
    rows = [
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("v1")
    assert view._estimate_label.text() == "Typical time: ~12 min (based on 3 runs)"


def test_clicking_thumbnail_routes_the_row_into_the_metadata_panel(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._meta_panel.show_row = MagicMock()

    view._on_thumbnail_clicked("i1")

    view._meta_panel.show_row.assert_called_once()
    row = view._meta_panel.show_row.call_args.args[0]
    assert row["prompt_id"] == "i1"


def test_refresh_clears_the_metadata_panel(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._meta_panel.clear = MagicMock()

    view.refresh()

    view._meta_panel.clear.assert_called()


def test_selecting_a_folder_shows_average_time_across_its_items(qtbot):
    rows = [
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Videos"].child(0)
    view._tree.setCurrentItem(workflow)
    assert view._avg_label.text() == "Average time: ~12 min (across 3 runs)"


def test_folder_without_timed_items_shows_no_average(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))  # no duration
    qtbot.addWidget(view)
    view.refresh()

    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    assert view._avg_label.text() == ""


def _find_settings_node(view, predicate):
    """First settings-group tree node (at any depth) whose group matches."""
    def walk(item):
        group = item.data(0, _GROUP_ROLE)
        if isinstance(group, gallery.SettingsGroup) and predicate(group):
            return item
        for i in range(item.childCount()):
            hit = walk(item.child(i))
            if hit is not None:
                return hit
        return None
    root = view._tree.invisibleRootItem()
    for i in range(root.childCount()):
        hit = walk(root.child(i))
        if hit is not None:
            return hit
    return None


def test_untimed_prompt_folder_falls_back_to_workflow_time(qtbot):
    rows = [
        # A video prompt nobody has timed yet (its own settings group).
        _row("v_untimed", "wan22_i2v", {"steps": 30, "seed": 2}, "wan22_i2v_2.mp4"),
        # A different, timed prompt in the same workflow.
        _row("v_timed", "wan22_i2v", {"steps": 20, "seed": 1}, "wan22_i2v_1.mp4",
             duration_seconds=1390.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    node = _find_settings_node(
        view, lambda g: all(r.get("duration_seconds") is None for r in g.rows)
    )
    assert node is not None
    view._tree.setCurrentItem(node)
    # No timed items of its own → it falls back to the workflow's typical time.
    assert view._avg_label.text() == "Average time: ~23 min (across 1 run)"


def test_timed_prompt_folder_uses_its_own_average_not_the_workflow(qtbot):
    rows = [
        _row("v_slow", "wan22_i2v", {"steps": 30, "seed": 9}, "wan22_i2v_9.mp4",
             duration_seconds=1390.0),  # a different, slower prompt in the workflow
        _row("v1", "wan22_i2v", {"steps": 20, "seed": 1}, "wan22_i2v_1.mp4",
             duration_seconds=60.0),
        _row("v2", "wan22_i2v", {"steps": 20, "seed": 2}, "wan22_i2v_2.mp4",
             duration_seconds=80.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    node = _find_settings_node(view, lambda g: {r["prompt_id"] for r in g.rows} == {"v1", "v2"})
    assert node is not None
    view._tree.setCurrentItem(node)
    # Its own two runs average 70s (a coarse "~1 min") — the workflow's slow
    # outlier doesn't leak in.
    assert view._avg_label.text() == "Average time: ~1 min (across 2 runs)"


def test_emptying_the_gallery_clears_a_stale_estimate(qtbot):
    rows = [_image("i1", "a cat", 50, 1)]
    rows[0]["duration_seconds"] = 6.0
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("i1")
    assert view._estimate_label.text()  # estimate is showing

    db._rows.clear()
    db._by_id.clear()
    view.refresh()  # no folders, so nothing to preview
    assert view._estimate_label.text() == ""


# --- deletion & undo ------------------------------------------------------

def _open_leaf(view):
    """Select the first settings-group leaf so its thumbnails are showing."""
    workflow = _top_level(view._tree)["Images"].child(0)
    leaf = workflow.child(0).child(0)  # workflow -> model -> settings
    view._tree.setCurrentItem(leaf)
    return leaf


def test_delete_key_deletes_the_selected_thumbnail(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._apply_selection("i1", _NO_MOD)
    view._delete_selection()

    assert len(actions.deleted) == 1
    assert [r["prompt_id"] for r in actions.deleted[0]] == ["i1"]


def test_ctrl_click_extends_selection_and_delete_takes_all_picked(qtbot):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i3", _CTRL)
    assert set(view.selected_prompt_ids()) == {"i1", "i3"}

    view._delete_selection()
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i3"}


def test_ctrl_click_again_deselects_a_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i2", _CTRL)
    view._apply_selection("i2", _CTRL)  # toggle i2 back off
    assert view.selected_prompt_ids() == ["i1"]


def test_shift_click_selects_the_contiguous_range(qtbot):
    rows = [_image(f"i{i}", "a cat", 50, i) for i in range(1, 5)]  # i1..i4
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    order = view.visible_prompt_ids()  # newest-first display order

    view._apply_selection(order[0], _NO_MOD)
    view._apply_selection(order[2], _SHIFT)
    assert view.selected_prompt_ids() == order[:3]


def test_plain_click_replaces_the_whole_selection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i2", _CTRL)     # now both selected
    view._apply_selection("i2", _NO_MOD)   # plain click collapses to one
    assert view.selected_prompt_ids() == ["i2"]


def test_changing_folders_clears_the_selection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    cat_leaf = _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    assert view.selected_prompt_ids() == ["i1"]

    # Drilling to the sibling settings folder must not carry the pick over.
    dog_leaf = cat_leaf.parent().child(1)
    view._tree.setCurrentItem(dog_leaf)
    assert view.selected_prompt_ids() == []


def test_delete_on_a_settings_folder_with_no_pick_deletes_the_whole_folder(qtbot):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)  # leaf selected, nothing picked
    view._confirm = lambda text: True

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_deleting_a_folder_can_be_cancelled_at_the_prompt(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._confirm = lambda text: False  # user says no

    view._delete_selection()

    assert actions.deleted == []


def test_delete_key_on_a_workflow_folder_does_nothing(qtbot):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)  # a whole-workflow folder
    view._confirm = lambda text: True    # even if it asked, it must not

    view._delete_selection()

    assert actions.deleted == []  # workflow folders are off-limits


def test_a_failed_delete_is_surfaced_not_swallowed(qtbot, monkeypatch):
    class BoomActions(FakeActions):
        def delete_rows(self, rows):
            raise OSError("the file is held by another process")

    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=BoomActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    warned = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMessageBox.warning",
        lambda *a, **k: warned.append(a),
    )

    view._delete_selection()  # must not raise

    assert warned  # the user is told the delete failed instead of nothing happening


def test_right_clicking_an_unpicked_thumbnail_selects_it(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: None)

    view._thumbnail_context_menu("i2", QPoint(0, 0))

    assert view.selected_prompt_ids() == ["i2"]


def test_right_click_delete_removes_the_picked_thumbnails(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    # Choosing the menu's only entry ("Delete").
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[-1]
    )

    view._thumbnail_context_menu("i1", QPoint(0, 0))

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


def test_right_click_delete_acts_on_the_whole_multi_selection(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i3", _CTRL)  # i1 + i3 selected
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[-1]
    )

    # Right-clicking a tile already in the selection keeps the whole set.
    view._thumbnail_context_menu("i3", QPoint(0, 0))

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i3"}


def test_right_clicking_a_selected_tile_preserves_the_multi_selection(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i3", _CTRL)  # i1 + i3
    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: None)

    # A real right-press on a selected tile must not collapse the selection to one.
    qtbot.mouseClick(view._thumb_widgets["i3"], Qt.MouseButton.RightButton)

    assert set(view.selected_prompt_ids()) == {"i1", "i3"}


def test_deleting_a_folder_lands_on_the_parent_not_the_top(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    for pid, prompt in [("i1", "a cat"), ("i2", "a dog")]:  # two settings groups, one model
        db.insert_generation(
            prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v1",
            positive_prompt=prompt,
            params_json=json.dumps({"positive_prompt": prompt, "steps": 20}),
            workflow_json="{}",
        )
        (out / f"sdxl_t2i_{pid}.png").write_bytes(b"x")
        db.update_generation(
            pid, status="completed",
            output_files=json.dumps([{"filename": f"sdxl_t2i_{pid}.png", "subfolder": ""}]),
        )
    actions = GalleryActions(db, out, Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    model = _top_level(view._tree)["Images"].child(0).child(0)
    view._tree.setCurrentItem(model.child(0))  # one of the two settings leaves
    view._confirm = lambda text: True

    view._delete_selection()  # deletes that settings folder

    # The model (parent) survives via its sibling; the tree stays on it.
    current = view._tree.currentItem().data(0, _GROUP_ROLE)
    assert isinstance(current, gallery.ModelGroup)


def test_delete_folder_refuses_workflow_and_media_groups(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    images = _top_level(view._tree)["Images"]
    view._confirm = lambda text: True

    view._delete_folder(images.data(0, _GROUP_ROLE))       # the Images media group
    view._delete_folder(images.child(0).data(0, _GROUP_ROLE))  # the workflow group

    assert actions.deleted == []  # only folders inside a workflow may go


def test_a_model_folder_deletes_all_its_settings_groups(qtbot):
    actions = FakeActions()
    # Two settings groups (cat, dog) share one model -> a single model folder.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    model = _top_level(view._tree)["Images"].child(0).child(0)
    view._tree.setCurrentItem(model)  # a model folder, nested in the workflow
    view._confirm = lambda text: True

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_a_lora_folder_is_deletable_and_takes_only_its_own_rows(qtbot):
    actions = FakeActions()
    # One base model, two LoRA folders (styleA, styleB). Deleting the styleA LoRA
    # folder must remove only its video, leaving the styleB sibling intact.
    rows = [_i2v_video("v1", "styleA"), _i2v_video("v2", "styleB")]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    # Videos -> WAN I2V -> model -> LoRA (styleA is first by appearance).
    lora = _top_level(view._tree)["Videos"].child(0).child(0).child(0)
    assert isinstance(lora.data(0, _GROUP_ROLE), gallery.LoraGroup)
    view._tree.setCurrentItem(lora)
    view._confirm = lambda text: True

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"v1"}


def test_undo_button_reflects_pending_action_and_triggers_undo(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    assert not view._undo_btn.isEnabled()  # nothing to undo at rest

    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view._delete_selection()
    assert view._undo_btn.isEnabled()
    assert "Delete" in view._undo_btn.toolTip()

    view._undo_btn.click()
    assert actions.undo_count == 1
    assert not view._undo_btn.isEnabled()


def test_renaming_goes_through_the_undoable_actions(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    key = _key(_top_level(view._tree)["Images"].child(0))

    view._apply_rename(key, "Best Models")

    assert actions.renamed == [(key, "Best Models")]
    assert view._undo_btn.isEnabled()  # the rename is now undoable


def test_inline_rename_is_undoable(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    workflow = _top_level(view._tree)["Images"].child(0)
    key = _key(workflow)

    view._editing_key = key            # an in-place edit is underway
    workflow.setText(0, "Renamed")     # committing it routes through actions

    assert actions.renamed == [(key, "Renamed")]
    assert view._undo_btn.isEnabled()


def test_delete_then_undo_through_the_view_round_trips(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    output_dir = tmp_path / "output"
    db.insert_generation(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"steps": 50}), workflow_json="{}",
    )
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"img")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryActions(db, output_dir, Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view._delete_selection()
    assert db.get_generation("i1") is None
    assert not file_path.exists()

    view._undo()
    assert db.get_generation("i1") is not None
    assert file_path.exists()


# --- re-roll ("+") tile -----------------------------------------------------


def _reroll_client():
    client = ComfyUIClient()
    client.submit_job = MagicMock(return_value="comfy-X")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    return client


def _png_bytes(color=(10, 120, 200)):
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def _reroll_tile(view):
    tiles = view._scroll.widget().findChildren(RerollTile)
    return tiles[0] if tiles else None


def _select_first_leaf(view):
    # media -> workflow -> model -> settings (the thumbnail leaf)
    leaf = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    view._tree.setCurrentItem(leaf)
    return leaf.data(0, _GROUP_ROLE).key


def _seeded_db(tmp_path, seed=7):
    """A DB holding one completed SDXL image with full, re-rollable params."""
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="orig",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt="a cat",
        negative_prompt="",
        seed=seed,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=seed, positive_prompt="a cat")),
        workflow_json="{}",
    )
    db.update_generation(
        "orig", status="completed",
        output_files=json.dumps([{"filename": "sdxl_orig.png", "subfolder": ""}]),
    )
    return db


def test_leaf_shows_add_tile_when_client_present(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is not None


def test_main_view_reflows_to_fill_extra_width(qtbot):
    # The main view flows tiles to fill the pane: a wide pane packs more per row
    # and so is shorter than a narrow one. The old fixed 4-column grid ignored
    # the available width, so its height never changed.
    rows = [_image(f"i{n}", "a cat", 50, n) for n in range(1, 9)]  # eight tiles
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    layout = view._scroll.widget().layout()
    assert layout.heightForWidth(2000) < layout.heightForWidth(300)


def test_add_tile_sits_first_beside_the_newest(qtbot):
    # Thumbnails are newest-first, so the "new variation" box leads the flow,
    # beside the newest item, not trailing the oldest.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    layout = view._scroll.widget().layout()
    assert isinstance(layout.itemAt(0).widget(), RerollTile)


def test_leaf_has_no_add_tile_without_a_client(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is None


def test_no_add_tile_for_unknown_workflow(qtbot):
    rows = [_row("x1", "unknown", {"seed": 1}, "x1.png")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is None


def test_add_tile_shows_for_imported_with_known_workflow(qtbot):
    # Re-roll works anywhere Reuse Parameters does, imports included — the
    # workflow's defaults fill in whatever sparse metadata an import lacks.
    rows = [_row("imp", "sdxl_t2i", {"seed": 1}, "imp.png", source="imported")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is not None


def test_reroll_of_sparse_import_fills_params_from_defaults(qtbot, tmp_path):
    # An import keeps only sparse metadata (no checkpoint/vae); re-roll must
    # still build a valid payload by borrowing the workflow's defaults.
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="imp", workflow_name="sdxl_t2i", workflow_version="imported",
        positive_prompt="a cat", seed=1,
        params_json=json.dumps({"positive_prompt": "a cat", "seed": 1}),  # sparse
        workflow_json="{}", source="imported",
    )
    db.update_generation("imp", status="completed",
                         output_files=json.dumps([{"filename": "imp.png", "subfolder": ""}]))
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    job = view._reroll_jobs[key]
    assert job.params["checkpoint"] == _SDXL.default_params()["checkpoint"]  # filled in
    assert job.params["seed"] != 1  # re-rolled
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)  # built without error


def test_clicking_add_starts_a_reroll_with_a_new_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert key in view._reroll_jobs
    job = view._reroll_jobs[key]
    assert job.workflow.name == "sdxl_t2i"
    assert job.params["seed"] != 7  # same settings, fresh seed
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)


def test_starting_a_reroll_swaps_the_tile_to_active(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert not _reroll_tile(view)._cancel.isHidden()  # now the live, cancelable tile


def test_clicking_add_twice_starts_only_one_job(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._start_reroll(key)
    view._start_reroll(key)

    client.submit_job.assert_called_once()


def _insert_running_reroll(db, prompt_id="rr", seed=99):
    """A re-roll left running by a prior session: same settings folder as
    _seeded_db's 'orig', no output yet, status running."""
    params = dict(_SDXL.default_params(), seed=seed, positive_prompt="a cat")
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=seed,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="running")


def test_reconnect_running_rerolls_rebinds_a_live_job(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "rr")
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)

    view.reconnect_running_rerolls()

    key = gallery.settings_folder_key(db.get_generation("rr"))
    assert key in view._reroll_jobs
    assert view._reroll_jobs[key].prompt_id == "rr"
    client.submit_job.assert_not_called()  # reconnected, never resubmitted


def test_reconnected_reroll_shows_live_tile_then_finalizes(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "rr")
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.reconnect_running_rerolls()
    view.refresh()
    _select_first_leaf(view)
    assert not _reroll_tile(view)._cancel.isHidden()  # the live, cancelable tile

    client.job_completed.emit("rr", _REROLL_HISTORY)

    row = db.get_generation("rr")
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert view._reroll_jobs == {}


def test_reconnect_skips_a_reroll_claimed_by_a_generate_tab(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    _insert_running_reroll(db, "rr")
    view = GalleryView(db, client=_reroll_client(), claimed_ids=lambda: {"rr"})
    qtbot.addWidget(view)

    view.reconnect_running_rerolls()

    assert view._reroll_jobs == {}  # a Generate tab owns it; the gallery leaves it


def test_starting_a_reroll_records_a_running_row(qtbot, tmp_path):
    # A re-roll persists a running row the moment it's submitted, so a restart
    # mid-generation can find it again (reconnect) instead of losing all trace.
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    job = view._reroll_jobs[key]
    row = db.get_generation(job.prompt_id)  # keyed by the same id ComfyUI runs it under
    assert row is not None
    assert row["status"] == "running"
    assert row["workflow_name"] == "sdxl_t2i"
    assert gallery.row_output_files(row) == []  # no output yet: stays out of the tree


def test_reroll_completion_finalizes_the_running_row(qtbot, tmp_path):
    client = _reroll_client()
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._reroll_jobs[key].prompt_id

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    rows = db.list_generations()
    assert len(rows) == 2  # the running row was updated in place, not duplicated
    new = db.get_generation(prompt_id)
    assert new["status"] == "completed"
    assert "a.png" in new["output_files"]
    assert new["seed"] != 7
    assert view._reroll_jobs == {}


def test_canceling_a_reroll_removes_its_running_row(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._reroll_jobs[key].prompt_id
    assert db.get_generation(prompt_id) is not None

    _reroll_tile(view).cancel_requested.emit()

    assert db.get_generation(prompt_id) is None  # the abandoned run leaves no trace


def test_failed_reroll_marks_its_running_row_error(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    job = view._reroll_jobs[key]

    view._client.job_error.emit(job.prompt_id, "boom")

    assert db.get_generation(job.prompt_id)["status"] == "error"
    assert key not in view._reroll_jobs


def test_cancel_running_reroll_interrupts(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()

    client.node_executing.emit(view._reroll_jobs[key].prompt_id, "5")  # job is now executing
    _reroll_tile(view).cancel_requested.emit()

    client.interrupt.assert_called_once()
    client.cancel_prompt.assert_not_called()
    assert key not in view._reroll_jobs
    assert _reroll_tile(view)._cancel.isHidden()  # reverted to the idle + box


def test_cancel_queued_reroll_dequeues(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._reroll_jobs[key].prompt_id

    _reroll_tile(view).cancel_requested.emit()  # still queued, not executing

    client.cancel_prompt.assert_called_once_with(prompt_id)
    client.interrupt.assert_not_called()
    assert key not in view._reroll_jobs


def test_active_reroll_survives_a_refresh(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()

    view.refresh()  # a poll-driven rebuild must not drop the running job

    assert key in view._reroll_jobs
    assert not _reroll_tile(view)._cancel.isHidden()  # still the live tile


# --- re-roll preview mirrored into the info pane ----------------------------


def _running_reroll(view):
    """Start a re-roll and return (key, job) for the freshly launched job."""
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    return key, view._reroll_jobs[key]


def test_selecting_a_running_reroll_shows_its_live_preview_in_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)  # a frame arrives, cached on the job
    view._preview.show_frame = MagicMock()

    _reroll_tile(view).selected.emit()  # user clicks the running tile

    view._preview.show_frame.assert_called_once_with(frame)


def test_new_frames_route_to_the_info_pane_while_the_reroll_is_selected(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _reroll_tile(view).selected.emit()
    view._preview.show_frame = MagicMock()

    client.preview_image.emit(job.prompt_id, _png_bytes())  # a later frame

    view._preview.show_frame.assert_called_once_with(_png_bytes())


def test_selecting_a_thumbnail_stops_the_reroll_from_driving_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)  # starting the re-roll selects it
    view._on_thumbnail_clicked("orig")  # user views a finished item instead

    view._preview.show_frame = MagicMock()
    client.preview_image.emit(job.prompt_id, _png_bytes())  # tile updates, info pane does not

    view._preview.show_frame.assert_not_called()
    assert view._selected_reroll_key is None


def test_selecting_the_reroll_highlights_its_tile_and_drops_thumbnail_picks(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    view._apply_selection("orig", _NO_MOD)  # a thumbnail is picked while it runs
    assert view.selected_prompt_ids() == ["orig"]

    _reroll_tile(view).selected.emit()

    assert _reroll_tile(view).is_selected()
    assert view.selected_prompt_ids() == []  # the thumbnail pick is cleared


def test_finishing_a_selected_reroll_clears_the_reroll_selection(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _reroll_tile(view).selected.emit()

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._selected_reroll_key is None


def test_canceling_a_selected_reroll_releases_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _reroll_tile(view).selected.emit()

    view._cancel_reroll(key)

    assert view._selected_reroll_key is None


def test_clicking_add_selects_the_reroll_so_its_preview_shows_at_once(qtbot, tmp_path):
    # One click on "+" both starts the re-roll and selects it, so the info pane
    # shows its live preview without a second click on the now-running tile.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert view._selected_reroll_key == key
    assert _reroll_tile(view).is_selected()


def test_selecting_a_reroll_before_any_frame_avoids_the_idle_placeholder(qtbot, tmp_path):
    # "Select a generation to preview" would misdescribe a running re-roll, so a
    # queued one with no frame yet shows a waiting note instead of clearing.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)  # no preview frame has arrived yet
    view._preview.clear = MagicMock()
    view._preview.show_message = MagicMock()

    _reroll_tile(view).selected.emit()

    view._preview.clear.assert_not_called()
    view._preview.show_message.assert_called_once()


def test_selected_reroll_survives_the_rebuild_its_running_row_triggers(qtbot, tmp_path):
    # Submitting a re-roll inserts a running row, so the next poll rebuilds the
    # tree — the selected re-roll must keep driving the info pane across it.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})  # reconcile finds nothing done
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)
    _reroll_tile(view).selected.emit()
    view._preview.show_frame = MagicMock()

    view._poll()  # the rebuild the new running row triggers

    assert view._selected_reroll_key == key
    assert _reroll_tile(view).is_selected()
    view._preview.show_frame.assert_called_with(frame)


def test_i2v_video_stage_keeps_the_last_image_frame_until_it_previews(qtbot, tmp_path):
    # Re-rolling an i2v runs a fresh image, then the video. When it moves onto the
    # video — which has no preview of its own yet — the info pane must keep showing
    # the image frame rather than going blank across the rebuild that the finished
    # image row triggers.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})
    view = GalleryView(_seeded_i2v_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _reroll_tile(view).add_requested.emit()  # image stage starts
    img_job = view._reroll_jobs[key]
    _reroll_tile(view).selected.emit()
    image_frame = _png_bytes()
    client.preview_image.emit(img_job.prompt_id, image_frame)

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)  # image done -> video starts
    assert view._reroll_jobs[key].workflow.name == "wan22_i2v"
    view._preview.show_frame = MagicMock()

    view._poll()  # the rebuild the finished image row triggers

    assert view._selected_reroll_key == key
    view._preview.show_frame.assert_called_with(image_frame)


def _seeded_i2v_db(tmp_path):
    """A DB with a re-rollable SDXL image and a WAN i2v video built on it."""
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", negative_prompt="", seed=7,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=7, positive_prompt="a cat")),
        workflow_json="{}",
    )
    db.update_generation(
        "img", status="completed",
        output_files=json.dumps([{"filename": "sdxl_src.png", "subfolder": "image"}]),
    )
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="sdxl_src.png")),
        workflow_json="{}",
    )
    db.update_generation(
        "vid", status="completed",
        output_files=json.dumps([{"filename": "wan_src.mp4", "subfolder": "video"}]),
    )
    return db


def _select_leaf_of(view, prompt_id):
    item = view._leaf_by_id[prompt_id]
    view._tree.setCurrentItem(item)
    return item.data(0, _GROUP_ROLE).key


def test_i2v_reroll_regenerates_its_input_image_then_the_video(qtbot, tmp_path):
    # Re-rolling an i2v whose input image is a known, re-buildable generation
    # first makes a fresh image (its settings, new seed), then runs the video on
    # that image — both persisted, and the new video links back to the new image.
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _reroll_tile(view).add_requested.emit()

    # Stage 1: the image re-roll runs first, with the source image's settings.
    img_job = view._reroll_jobs[key]
    assert img_job.workflow.name == "sdxl_t2i"
    assert img_job.params["seed"] != 7  # fresh seed

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)

    # Stage 2: the video now runs on the just-generated image, its own seeds fresh.
    vid_job = view._reroll_jobs[key]
    assert vid_job.workflow.name == "wan22_i2v"
    assert vid_job.params["input_image"] == "image/sdxl_new.png [output]"
    assert vid_job.params["noise_seed"] != 9 and vid_job.params["seed"] != 3

    client.job_completed.emit(vid_job.prompt_id, _VID_REROLL_HISTORY)

    assert view._reroll_jobs == {}
    rows = db.list_generations()
    new_image = next(r for r in rows
                     if r["workflow_name"] == "sdxl_t2i" and r["prompt_id"] != "img")
    new_video = next(r for r in rows
                     if r["workflow_name"] == "wan22_i2v" and r["prompt_id"] != "vid")
    assert "sdxl_new.png" in new_image["output_files"]
    assert "wan_new.mp4" in new_video["output_files"]
    # The new video's stored input image resolves back to the new image (feature 1).
    image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
    assert gallery.find_source_image_id(new_video, image_rows) == new_image["prompt_id"]


def test_poll_reconciles_a_reroll_whose_completion_signal_was_missed(qtbot, tmp_path):
    # If ComfyUI's one-shot completion frame is missed, the periodic poll pulls
    # /history as a backstop so the finished generation still lands in the gallery
    # without a restart.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value=_REROLL_HISTORY)
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    # The live job_completed is never delivered — only the poll runs.

    view._poll()

    rows = db.list_generations()
    assert len(rows) == 2  # the re-roll persisted without a restart
    assert view._reroll_jobs == {}
    assert key not in view._reroll_jobs


def test_i2v_reroll_without_a_known_source_image_reuses_the_input(qtbot, tmp_path):
    # No image generation matches the video's input, so the re-roll can't rebuild
    # a fresh frame — it re-rolls the video alone, keeping the same input image.
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="outside.png")),
        workflow_json="{}",
    )
    db.update_generation(
        "vid", status="completed",
        output_files=json.dumps([{"filename": "wan_src.mp4", "subfolder": "video"}]),
    )
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _reroll_tile(view).add_requested.emit()

    job = view._reroll_jobs[key]
    assert job.workflow.name == "wan22_i2v"          # no image stage
    assert job.params["input_image"] == "outside.png"  # same input, re-used
    client.submit_job.assert_called_once()


def _shown_view_with_one_image(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    output_dir = tmp_path / "output"
    db.insert_generation(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"steps": 50}), workflow_json="{}",
    )
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"img")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryActions(db, output_dir, Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    view.refresh()
    return view, db, file_path


def test_pressing_delete_after_clicking_a_thumbnail_removes_it(qtbot, tmp_path):
    view, db, file_path = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    thumb = view._thumb_widgets["i1"]

    qtbot.mouseClick(thumb, Qt.MouseButton.LeftButton)  # select, the way a user does
    qtbot.keyClick(thumb, Qt.Key.Key_Delete)            # the event filter catches it

    assert db.get_generation("i1") is None
    assert not file_path.exists()


def test_delete_works_with_gallery_embedded_in_tabs(qtbot, tmp_path):
    # Mirror the real app: the gallery lives in a QTabWidget inside a QMainWindow.
    from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    db.insert_generation(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v1",
        positive_prompt="a cat",
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 20}),
        workflow_json="{}",
    )
    (out / "sdxl_t2i_i1.png").write_bytes(b"x")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryActions(db, out, Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    win = QMainWindow()
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Generate")
    tabs.addTab(view, "Gallery")
    win.setCentralWidget(tabs)
    tabs.setCurrentWidget(view)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Images"].child(0).child(0).child(0))
    view._apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_delete_works_without_a_thumbnail_holding_focus(qtbot, tmp_path):
    # The real-app failure: a selected item, but focus is on the tree (or nowhere
    # in the gallery), so a focus-scoped handler never fired. The app-wide filter
    # must still delete because the Gallery tab is the one on screen.
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_insert_key_also_deletes(qtbot, tmp_path):
    # Some keyboards send Insert where Delete is expected; the gallery treats
    # both the same (see the event filter).
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Insert)

    assert db.get_generation("i1") is None


def test_ctrl_z_undoes_a_delete(qtbot, tmp_path):
    view, db, file_path = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    qtbot.keyClick(view, Qt.Key.Key_Delete)
    assert db.get_generation("i1") is None

    qtbot.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert db.get_generation("i1") is not None
    assert file_path.exists()


def test_delete_on_a_tree_folder_removes_it_via_the_keyboard(qtbot, tmp_path):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)  # the settings folder is the current tree item
    view._confirm = lambda text: True

    qtbot.keyClick(view._tree, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_delete_is_ignored_when_the_gallery_tab_is_not_showing(qtbot, tmp_path):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view.hide()  # another tab is active

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is not None  # the gallery doesn't grab the key


def test_delete_passes_through_to_a_focused_text_field(qtbot, tmp_path, monkeypatch):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    # A text editor (e.g. an inline rename box) has focus: Delete edits text.
    editor = QLineEdit()
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QApplication.focusWidget", lambda: editor
    )

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is not None
