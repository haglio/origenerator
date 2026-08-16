import json
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QRect, QObject, QEvent, pyqtSignal
from PyQt6.QtGui import QIcon, QMovie, QKeyEvent
from PyQt6.QtWidgets import QSplitter, QLineEdit, QWidget

from origenerator import gallery
from origenerator.branch_session import ENV_FLAG
from origenerator.gallery import detail_parts
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.auto_generate_view import AutoGenerateView
from origenerator.gui.folder_tree import BRANCH_ICON_ROLE
from origenerator.gui.gallery_view import GalleryView, _GROUP_ROLE
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_prompt import REROLL_IMAGE, REROLL_VIDEO
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.recovery import RETENTION_DAYS
from origenerator.stroke_engine import Stroke
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
        self.rejected = []  # experiment rows handed to reject_experiment
        self.restored = []  # each entry is one restore_deleted call's ids
        self.purged = []    # each entry is one purge_deleted call's ids
        self.undo_count = 0
        self._label = None

    def delete_rows(self, rows):
        self.deleted.append(list(rows))
        self._label = f"Delete {len(rows)} items"

    def restore_deleted(self, prompt_ids):
        ids = list(prompt_ids)
        self.restored.append(ids)
        return ids[0] if ids else None

    def purge_deleted(self, prompt_ids):
        self.purged.append(list(prompt_ids))

    def reject_experiment(self, row):
        self.rejected.append(row)
        self._label = "Reject experiment"

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


class _FakeVoiceSteering(QObject):
    """Stands in for VoiceSteering so gallery tests never open a real microphone;
    ``say`` simulates a heard-and-rewritten utterance steering the loop's prompt,
    ``speak_command`` one the matcher recognizes while a surface is listening."""

    error = pyqtSignal(str)
    heard = pyqtSignal(str)
    edited = pyqtSignal(str)

    def __init__(self, *, command_matcher=None):
        super().__init__()
        self.started = False
        self.stopped = False
        self.commands_on = False
        self._matcher = command_matcher
        self._execute = None
        self._set = None

    def start(self, get_prompt, set_prompt):
        self.started = True
        self._set = set_prompt

    def stop(self):
        self.stopped = True

    def start_commands(self, execute):
        self.commands_on = True
        self._execute = execute

    def stop_commands(self):
        self.commands_on = False
        self._execute = None

    def say(self, new_prompt):
        self._set(new_prompt)

    def speak_command(self, text):
        """One spoken utterance while commands are armed: matched → executed."""
        matched = self._matcher(text) if self.commands_on and self._matcher else None
        if matched is not None:
            self._execute(matched)
        return matched


@pytest.fixture(autouse=True)
def _no_real_mic(monkeypatch):
    """Default every GalleryView's voice steering to the inert fake above, so
    toggling Auto in a test never opens the microphone."""
    monkeypatch.setattr(gallery_view_module, "VoiceSteering", _FakeVoiceSteering)


class FakeDB:
    """In-memory stand-in for Database covering the methods the view calls."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._by_id = {r["prompt_id"]: r for r in rows}
        self._meta = {}
        self._custom = {}       # folder id -> {"name", "members": {key: (level, ref)}}
        self._next_custom = 1
        self._deletions = {}    # prompt_id -> the held-deletion record, newest last

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

    def folder_enhance_map(self):
        return {k: v["enhance_json"] for k, v in self._meta.items()
                if v.get("enhance_json")}

    def set_folder_enhance(self, key, enhance_json):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["enhance_json"] = enhance_json

    def rename_folder(self, key, custom_name):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["custom_name"] = custom_name

    def set_folder_starred(self, key, starred):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["starred"] = bool(starred)

    def set_generation_starred(self, prompt_id, starred):
        row = self._by_id.get(prompt_id)
        if row is not None:
            row["starred"] = 1 if starred else 0

    def set_experiment_verdict(self, prompt_id, verdict):
        row = self._by_id.get(prompt_id)
        if row is not None:
            row["experiment_verdict"] = verdict

    def delete_generation(self, prompt_id):
        self._rows = [r for r in self._rows if r["prompt_id"] != prompt_id]
        self._by_id.pop(prompt_id, None)

    def restore_generation(self, row):
        self._rows.insert(0, row)
        self._by_id[row["prompt_id"]] = row

    # --- the recovery bin (deletions held for the Trash shelf) -------------

    def record_deletion(self, prompt_id, row, batch):
        self._deletions.pop(prompt_id, None)  # a re-delete goes to the back
        self._deletions[prompt_id] = {
            "prompt_id": prompt_id, "row": row, "batch": batch,
            "deleted_at": "2026-08-15 03:00:00",
        }

    def list_deletions(self):
        return list(reversed(self._deletions.values()))  # newest first

    def get_deletion(self, prompt_id):
        return self._deletions.get(prompt_id)

    def forget_deletion(self, prompt_id):
        self._deletions.pop(prompt_id, None)

    # --- custom folders (the groupings the user composes) ------------------

    def create_custom_folder(self, name, folder_id=None):
        if folder_id is None:
            folder_id = self._next_custom
        self._next_custom = max(self._next_custom, folder_id) + 1
        self._custom[folder_id] = {"name": name, "members": {}}
        return folder_id

    def rename_custom_folder(self, folder_id, name):
        self._custom[folder_id]["name"] = name

    def delete_custom_folder(self, folder_id):
        self._custom.pop(folder_id, None)

    def add_custom_folder_members(self, folder_id, members):
        for folder_key, level, ref in members:
            self._custom[folder_id]["members"][folder_key] = (level, ref)

    def remove_custom_folder_member(self, folder_id, folder_key):
        self._custom[folder_id]["members"].pop(folder_key, None)

    def list_custom_folders(self):
        return [{"id": fid, "name": f["name"], "members": list(f["members"])}
                for fid, f in sorted(self._custom.items())]

    def custom_folder_members_full(self):
        return [{"folder_id": fid, "folder_key": key, "level": level, "ref_prompt_id": ref}
                for fid, f in self._custom.items()
                for key, (level, ref) in f["members"].items()]

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
    tree grows Videos -> WAN I2V -> model -> LoRA -> source image -> settings."""
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
    assert set(top) == {"Recents", "Starred", "Experiments", "Trash", "Images", "Videos"}

    workflow_node = top["Images"].child(0)
    assert workflow_node.text(0) == "SDXL Text-to-Image"
    # workflow -> one model -> its "(no LoRA)" level -> one settings folder, into
    # which the two seed variants collapse.
    assert workflow_node.childCount() == 1                    # one model
    assert workflow_node.child(0).childCount() == 1           # its single "(no LoRA)" level
    assert workflow_node.child(0).child(0).childCount() == 1  # the two seeds collapse


def test_tree_rows_carry_a_recipe_level_badge_and_tooltip(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    videos = _top_level(view._tree)["Videos"]
    workflow = videos.child(0)
    model = workflow.child(0)
    lora = model.child(0)
    source = lora.child(0)
    settings = source.child(0)

    # Each level below the media root shows a chip icon and names itself in the
    # tooltip...
    assert not workflow.icon(0).isNull() and "Workflow" in workflow.toolTip(0)
    assert not model.icon(0).isNull() and "Model" in model.toolTip(0)
    assert not lora.icon(0).isNull() and "LoRA" in lora.toolTip(0)
    assert not source.icon(0).isNull() and "Source Image" in source.toolTip(0)
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

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    # A branch folder shows its sub-folders as tiles, not loose thumbnails.
    view._tree.setCurrentItem(lora)
    assert len(view.visible_folder_keys()) == 2
    assert view.visible_prompt_ids() == []

    # A leaf (settings) folder shows the actual item thumbnails.
    cat_leaf = lora.child(0)
    view._tree.setCurrentItem(cat_leaf)
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}
    assert view.visible_folder_keys() == []


def test_clicking_a_folder_tile_drills_into_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    view._tree.setCurrentItem(lora)
    a_tile_key = view.visible_folder_keys()[0]  # a settings tile under the LoRA folder

    view._drill_into(a_tile_key)  # same path the tile's clicked signal triggers
    assert view.visible_prompt_ids()  # now showing that folder's thumbnails


def _children_by_label(item):
    return {item.child(i).text(0): item.child(i) for i in range(item.childCount())}


def test_toc_filter_hides_folders_whose_label_does_not_match(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    images = _top_level(view._tree)["Images"]
    lora = images.child(0).child(0).child(0)  # "(no LoRA)"
    leaves = _children_by_label(lora)

    view._filter_edit.setText("cat")

    assert not leaves["a cat"].isHidden()   # the match stays
    assert leaves["a dog"].isHidden()       # the non-match drops out
    # its ancestors stay visible and expand, so the match is actually on screen.
    assert not lora.isHidden() and lora.isExpanded()
    assert not images.isHidden() and images.isExpanded()


def test_toc_filter_match_on_a_folder_keeps_its_whole_subtree(qtbot):
    rows = [_i2v_video("v1", "styleA"), _i2v_video("v2", "styleB")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    model = _top_level(view._tree)["Videos"].child(0).child(0)
    loras = _children_by_label(model)
    style_a = next(v for k, v in loras.items() if "styleA" in k)
    style_b = next(v for k, v in loras.items() if "styleB" in k)

    view._filter_edit.setText("styleA")

    assert style_b.isHidden()               # the sibling LoRA drops out
    assert not style_a.isHidden()
    # matching the LoRA folder keeps everything beneath it (source image -> settings).
    source = style_a.child(0)
    assert not source.isHidden()
    assert not source.child(0).isHidden()   # the settings leaf under it


def test_clearing_the_toc_filter_restores_visibility_and_prior_expansion(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    images = _top_level(view._tree)["Images"]
    images.setExpanded(True)                 # a folder the user had open...
    workflow = images.child(0)               # ...its child left collapsed
    lora = workflow.child(0).child(0)
    dog = _children_by_label(lora)["a dog"]

    view._filter_edit.setText("cat")
    assert dog.isHidden()
    assert workflow.isExpanded()             # the filter opened the path to the match

    view._filter_edit.setText("")            # clear the filter
    assert not dog.isHidden()                # everything is back
    assert images.isExpanded()               # the folder the user had open stays open
    assert not workflow.isExpanded()         # the path the filter opened collapses back


def test_toc_filter_stays_applied_across_a_rebuild(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._filter_edit.setText("cat")
    db.add(_image("i3", "a bird", 50, 9))    # a new generation lands...
    view.refresh()                           # ...triggering a rebuild

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    leaves = _children_by_label(lora)
    assert not leaves["a cat"].isHidden()
    assert leaves["a dog"].isHidden()        # still filtered after the rebuild
    assert leaves["a bird"].isHidden()       # and the newcomer is filtered too


def test_toc_pane_holds_a_filter_field_above_the_tree(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    toc = view._panes.widget(0)
    assert isinstance(view._filter_edit, QLineEdit)
    assert toc.isAncestorOf(view._filter_edit)
    # it leads the pane, above the folder tree it filters.
    layout = toc.layout()
    assert layout.indexOf(view._filter_edit) < layout.indexOf(view._tree)


def test_toc_filter_matches_a_generation_by_its_seed(qtbot):
    # The two seed variants collapse into one "a cat" leaf; "a dog" is a sibling.
    rows = [
        _image("i1", "a cat", 50, 778899),
        _image("i2", "a cat", 50, 112233),
        _image("i3", "a dog", 50, 445566),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    leaves = _children_by_label(lora)

    view._filter_edit.setText("778899")     # a seed, carried by no folder label

    assert not leaves["a cat"].isHidden()   # the folder holding that seed stays
    assert leaves["a dog"].isHidden()       # every other folder drops out


def test_a_unique_seed_filter_jumps_to_that_generation(qtbot):
    rows = [
        _image("i1", "a cat", 50, 778899),
        _image("i2", "a cat", 50, 112233),
        _image("i3", "a dog", 50, 445566),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._filter_edit.setText("778899")

    # Filtering opened the folder and selected the one item with that seed.
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}  # its folder is showing
    assert view.selected_generation() == "i1"


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

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    cat_key = _key(lora.child(0))
    dog_key = _key(lora.child(1))  # cat is first, dog second
    view._toggle_star(dog_key)

    assert db.folder_meta_map()[dog_key]["starred"] is True
    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    # The star marks the folder in place; it does not jump above the cat.
    assert [_key(lora.child(i)) for i in range(lora.childCount())] == [cat_key, dog_key]
    # Starred state rides on the group (the row's star icon reads it), not a ★ text
    # prefix, so the labels stay the plain folder names.
    assert lora.child(1).data(0, _GROUP_ROLE).starred is True
    assert lora.child(0).data(0, _GROUP_ROLE).starred is False
    assert not lora.child(1).text(0).startswith("★")


def test_starred_shelf_is_pinned_first_and_collects_starred_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    dog_key = _key(lora.child(1))
    view._toggle_star(dog_key)

    # The Starred shelf sits just below Recents, above the media folders.
    assert view._tree.topLevelItem(0).text(0) == "Recents"
    assert view._tree.topLevelItem(1).text(0) == "Starred"
    # Selecting it lists a tile for each starred folder, wherever it lives.
    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_folder_keys() == [dog_key]
    assert view.visible_prompt_ids() == []


def test_starred_shelf_row_aligns_like_the_media_folders(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Starred"]
    # No "★ " text prefix: the star is drawn in the caret column instead, so the
    # "Starred" label lines up with "Images"/"Videos" rather than sitting a
    # chevron-width to the right of them.
    assert shelf.text(0) == "Starred"
    assert isinstance(shelf.data(0, BRANCH_ICON_ROLE), QIcon)


def _experiment_row(prompt_id, verdict=None, prompt="a cat", steps=50, seed=9, **extra):
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"sdxl_t2i_{prompt_id}.png",
                source="experiment", experiment_verdict=verdict, **extra)


def test_experiments_shelf_is_always_reachable(qtbot):
    # The shelf hosts the feature's on/off switch, so it must exist before any
    # experiment does — an empty gallery included.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Experiments"]
    assert shelf.text(0) == "Experiments"
    assert isinstance(shelf.data(0, BRANCH_ICON_ROLE), QIcon)


def test_experiments_shelf_label_counts_the_unreviewed(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _experiment_row("e1"),
        _experiment_row("e2", seed=10),
        _experiment_row("e3", verdict="up", seed=11),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    assert _top_level(view._tree)["Experiments (2)"] is not None


def test_experiments_shelf_offers_keep_and_reject_on_each_tile(qtbot):
    view = GalleryView(FakeDB([_experiment_row("e1")]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._experiments_item)
    assert view.visible_prompt_ids() == ["e1"]
    tile = view._thumb_widgets["e1"]
    tooltips = [b.toolTip() for b in tile._corner_buttons]
    assert any("Keep" in t for t in tooltips)
    assert any("Reject" in t for t in tooltips)


def test_double_clicking_an_experiment_opens_it_selected_in_its_own_folder(qtbot):
    # An experiment has a folder like anything else, so the shelf's double-click
    # is the same jump Recents and Starred make — no verdict needed first.
    experiment = _experiment_row("e1", steps=30)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), experiment]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._experiments_item)
    view._thumb_widgets["e1"].double_clicked.emit("e1")

    assert view._selected_folder_key() == gallery.settings_folder_key(experiment)
    assert view.visible_prompt_ids() == ["e1"]  # its own settings folder, not i1's
    assert view.selected_prompt_ids() == ["e1"]  # landed selected
    assert view._thumb_widgets["e1"].is_selected()


def test_keeping_an_experiment_clears_it_from_the_review_queue(qtbot):
    db = FakeDB([_experiment_row("e1")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    # Unreviewed, but already filed in the tree — the shelf is a queue over it,
    # not a holding pen outside it.
    assert "Images" in _top_level(view._tree)

    view._on_experiment_verdict("e1", "keep")

    assert db.get_generation("e1")["experiment_verdict"] == "up"
    view._tree.setCurrentItem(view._experiments_item)
    assert view.visible_prompt_ids() == []          # reviewed: off the shelf...
    assert "Images" in _top_level(view._tree)       # ...and still in its folder


def test_rejecting_an_experiment_goes_through_the_undoable_action(qtbot):
    db = FakeDB([_experiment_row("e1")])
    actions = FakeActions()
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._on_experiment_verdict("e1", "reject")

    assert [r["prompt_id"] for r in actions.rejected] == ["e1"]
    assert view._undo_btn.isEnabled()


def test_an_experiment_completion_never_hijacks_the_front_tab(qtbot, monkeypatch):
    db = FakeDB([_experiment_row("e1"), _image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(view, "_show_reroll_result_in_tab", shown.append)

    view._on_reroll_finished("some-key", "e1")   # a background experiment landing
    assert shown == []                           # the user's tab is left alone

    view._on_reroll_finished("some-key", "i1")   # the user's own re-roll landing
    assert [r["prompt_id"] for r in shown] == ["i1"]  # handed the finished row itself


def test_the_experiments_switch_reports_what_each_position_means(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()

    view.set_experiments_enabled(True)           # a restored session turns it on
    assert view.experiments_enabled() is True
    assert view._experiments_cb.isChecked()      # the shelf's switch reflects it
    # The switch is a promise about the closed app, and says so.
    assert "close the app" in view._experiments_status.text()

    view._experiments_cb.setChecked(False)       # the user clicks it off
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()


def test_an_open_app_queues_no_experiments_however_the_switch_is_set(qtbot):
    # The whole point of the switch's new meaning: turning it on mid-session
    # must not put anything on the GPU while the user is sitting right there.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)

    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_schedules_no_experiments_at_all(qtbot, monkeypatch):
    # Scheduling an absence is the live install's alone. A preview instance
    # shares the same ComfyUI, so a batch queued as it closes outlives it as
    # work the live app can neither see nor cancel — and the user's next
    # Generate waits behind jobs "from another app" that were his own preview's.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)  # the switch a seeded session restores

    assert view.experiments_enabled() is False   # forced off, however it was saved
    assert not view._experiments_cb.isEnabled()  # greyed, with the reason beneath
    assert "live app" in view._experiments_status.text()

    view._experiments_cb.setChecked(True)  # and the gate holds even forced on

    assert view.queue_experiments_for_absence() == 0
    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_holds_no_experiment_review_queue(qtbot, monkeypatch):
    # A preview's database is a copy of the live one, so it inherits the live
    # app's unreviewed experiments — but a verdict recorded here is written to
    # that throwaway copy and never reaches the live app, which goes on offering
    # the same items for review. Reviewing is the live install's; a preview's
    # shelf offers none of it, and its count doesn't nag from the tree.
    monkeypatch.setenv(ENV_FLAG, "1")
    view = GalleryView(FakeDB([_experiment_row("e1"), _experiment_row("e2", seed=10)]))
    qtbot.addWidget(view)
    view.refresh()

    top = _top_level(view._tree)
    assert "Experiments" in top          # the shelf itself stays, unnumbered
    view._tree.setCurrentItem(view._experiments_item)
    assert view.visible_prompt_ids() == []


def test_a_branch_session_does_not_open_on_the_experiments_shelf(qtbot, monkeypatch):
    # The live app opens on the shelf when verdicts are waiting. A preview
    # inherits those same rows in its seeded copy, so it would greet every launch
    # with a review queue it cannot answer — and did, which is where the reviewing
    # that destroyed the live app's files happened.
    monkeypatch.setenv(ENV_FLAG, "1")
    view = GalleryView(FakeDB([_experiment_row("e1"), _image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)

    view.present_pending_experiments()
    view.refresh()

    assert view._tree.currentItem() is not view._experiments_item


def test_a_branch_session_says_why_its_experiments_shelf_is_empty(qtbot, monkeypatch):
    # Empty with no explanation would read as "nothing came up while you were
    # away" — when in fact the results are on the live app's shelf, where the
    # verdicts count. The switch above it says the same about scheduling.
    monkeypatch.setenv(ENV_FLAG, "1")
    view = GalleryView(FakeDB([_experiment_row("e1")]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._experiments_item)

    assert "live app" in view._browser._experiments_empty_hint()


# --- the Trash shelf: deleted items, still recoverable ----------------------


def _bin_db(rows=(), held=(), inherited=()):
    """A gallery whose bin already holds ``held`` — ``(prompt_id, row)`` pairs,
    oldest first — the way a previous session's deletes would have left it.

    ``inherited`` takes the same shape but files each as a delete that moved real
    files: what a preview's copied database carries over from the live install,
    and the only thing a preview may not touch.
    """
    db = FakeDB(list(rows))
    for prompt_id, row in held:
        db.record_deletion(prompt_id, row, {"moves": [], "subdir": None})
    for prompt_id, row in inherited:
        db.record_deletion(prompt_id, row, {
            "moves": [[f"out/{prompt_id}.png", f"trash/{prompt_id}/0_{prompt_id}.png"]],
            "subdir": f"trash/{prompt_id}",
        })
    return db


def test_the_trash_shelf_is_always_reachable(qtbot):
    # A bin you can only find once you have something to recover is no use: the
    # point is knowing, before you delete, that deleting is not the end.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Trash"]
    assert shelf.text(0) == "Trash"
    assert isinstance(shelf.data(0, BRANCH_ICON_ROLE), QIcon)


def test_the_trash_shelf_label_counts_what_it_holds(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    assert _top_level(view._tree)["Trash (2)"] is not None


def test_the_trash_shelf_lists_deleted_items_newest_first(qtbot):
    view = GalleryView(_bin_db(held=[("old", _image("old", "a cat", 50, 1)),
                                     ("new", _image("new", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    assert view.visible_prompt_ids() == ["new", "old"]


def test_a_deleted_item_reaches_the_shelf_the_moment_it_is_deleted(qtbot, tmp_path):
    # End to end through the real GalleryActions: delete a tile, and the item is
    # standing on the Trash shelf rather than gone.
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, tmp_path / "out",
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()

    view._delete_rows([db.get_generation("p1")])

    view._tree.setCurrentItem(view._trash_item)
    assert view.visible_prompt_ids() == ["p1"]


def test_each_trash_tile_offers_restore_and_permanent_delete(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    tooltips = [b.toolTip() for b in view._thumb_widgets["d1"]._corner_buttons]
    assert any("Restore" in t for t in tooltips)
    assert any("permanently" in t for t in tooltips)


def test_a_trash_tile_says_how_long_it_has_left(qtbot):
    # The one fact a gallery caption can't carry and this shelf can't do without.
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    caption = view._thumb_widgets["d1"]._text_label.text()
    assert "seed 1" in caption   # still says which item it is...
    assert "d left" in caption   # ...and, only here, how long it stays one


def test_the_shelf_states_the_retention_promise_while_it_holds_anything(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    assert str(RETENTION_DAYS) in view._avg_label.text()


def test_an_empty_trash_shelf_explains_what_it_is_for(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    assert str(RETENTION_DAYS) in view._browser._trash_empty_hint()
    assert view._avg_label.text() == ""  # the hint already says it; don't say it twice


def test_restoring_from_a_tile_hands_the_id_to_the_action(qtbot):
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._trash_item)

    view._thumb_widgets["d1"].corner_action_triggered.emit("d1", "restore")

    assert actions.restored == [["d1"]]


def test_a_restore_puts_the_item_back_in_its_own_folder(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1",
                         params_json=json.dumps({"steps": 20}), workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, tmp_path / "out",
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("p1")])
    assert "Images" not in _top_level(view._tree)  # the folder emptied out with it

    view.restore_from_trash(["p1"])

    assert "Images" in _top_level(view._tree)      # back in the tree...
    assert view.visible_prompt_ids() == ["p1"]     # ...and landed on, not left on the shelf
    assert view._db.list_deletions() == []


def test_purging_asks_before_it_ends_anything(qtbot, monkeypatch):
    # The one gallery action with no undo and no second copy behind it.
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._trash_item)
    asked = []
    monkeypatch.setattr(view, "_confirm", lambda text: asked.append(text) or False)

    view._thumb_widgets["d1"].corner_action_triggered.emit("d1", "purge")

    assert actions.purged == []                      # declined: nothing ended
    assert "cannot be undone" in asked[0]

    monkeypatch.setattr(view, "_confirm", lambda text: True)
    view._thumb_widgets["d1"].corner_action_triggered.emit("d1", "purge")
    assert actions.purged == [["d1"]]


def test_delete_on_the_trash_shelf_means_permanently(qtbot, monkeypatch):
    # The picked items are already deleted, so the button's one remaining
    # meaning is "for good" — rather than a live-looking control doing nothing.
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._trash_item)
    view._apply_selection("d1", _NO_MOD)
    monkeypatch.setattr(view, "_confirm", lambda text: True)

    assert "Permanently delete 1 item" in view._delete_btn.toolTip()
    view._delete_selection()

    assert actions.purged == [["d1"]]
    assert actions.deleted == []  # and never the ordinary delete path


def test_the_delete_button_is_dark_on_an_unpicked_trash_shelf(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)

    assert not view._delete_btn.isEnabled()


def test_a_purge_clears_the_item_off_the_shelf(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, tmp_path / "out",
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("p1")])
    monkeypatch.setattr(view, "_confirm", lambda text: True)

    view.purge_from_trash(["p1"])

    view._tree.setCurrentItem(view._trash_item)
    assert view.visible_prompt_ids() == []
    assert db.list_deletions() == []


def test_the_trash_shelf_is_a_place_back_returns_to(qtbot):
    view = GalleryView(_bin_db([_image("i1", "a cat", 50, 1)],
                               held=[("d1", _image("d1", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    view._tree.setCurrentItem(view._recents_item)
    view._go_back()

    assert view._tree.currentItem() is view._trash_item


def test_a_preview_hides_the_deletions_it_inherited(qtbot, monkeypatch):
    # A preview's database is a copy, so the deletions it inherits point into the
    # LIVE install's trash: restoring would move the live app's files out from
    # under rows it is still showing, and purging would destroy its only copies.
    monkeypatch.setenv(ENV_FLAG, "1")
    view = GalleryView(_bin_db(inherited=[("live", _image("live", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)

    assert view.visible_prompt_ids() == []
    assert "Nothing deleted in this preview" in view._browser._trash_empty_hint()


def test_a_preview_still_recovers_what_it_deleted_itself(qtbot, monkeypatch):
    # Judging the shelf means using it. A preview's own delete takes no files at
    # all, so its held deletion holds nothing of the live install's: listing it
    # is safe, and restoring it only puts the row back in the throwaway copy.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = _bin_db(held=[("mine", _image("mine", "a dog", 50, 2))],
                 inherited=[("live", _image("live", "a cat", 50, 1))])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._trash_item)
    assert view.visible_prompt_ids() == ["mine"]  # its own, and only its own

    view.restore_from_trash(["mine"])

    assert db.get_generation("mine") is not None
    assert db.get_deletion("mine") is None
    assert db.get_deletion("live") is not None  # the live app's is left where it is


def test_clicking_a_starred_tile_drills_into_the_real_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    dog_key = _key(lora.child(1))
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


def test_starred_shelf_collects_starred_items_as_thumbnails(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_starred("i2", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_prompt_ids() == ["i2"]  # the starred item, on the shelf
    assert view._thumb_widgets["i2"].is_starred() is True


def test_starred_shelf_shows_both_starred_items_and_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_starred("i1", True)  # a starred item
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    dog_key = _key(lora.child(1))
    view._toggle_star(dog_key)  # and a starred folder

    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_prompt_ids() == ["i1"]      # the item
    assert view.visible_folder_keys() == [dog_key]  # the folder


def test_unstarring_an_item_from_the_shelf_removes_it(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    db = FakeDB(rows)
    db.set_generation_starred("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    shelf = _top_level(view._tree)["Starred"]
    view._tree.setCurrentItem(shelf)
    assert view.visible_prompt_ids() == ["i1"]
    # Right-click the shelf tile → Unstar (the menu's first entry).
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[0]
    )
    _right_click(view, "i1")

    assert not db.get_generation("i1")["starred"]
    assert view.visible_prompt_ids() == []  # gone from the shelf after the rebuild


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
    top = _top_level(view._tree)
    assert "Recents" not in top
    assert "Starred" not in top


def test_recents_shelf_is_pinned_first_and_lists_recent_items(qtbot):
    rows = [_image("i2", "a dog", 50, 2), _image("i1", "a cat", 50, 1)]  # newest first
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    # Recents is the very first row, above Starred and the media folders.
    assert view._tree.topLevelItem(0).text(0) == "Recents"
    # Selecting it lists every recently generated item, newest first — not folders.
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert view.visible_prompt_ids() == ["i2", "i1"]
    assert view.visible_folder_keys() == []


def test_recents_shelf_excludes_imported_files(qtbot):
    # An import still builds the tree (so the shelf exists) but is not a recent
    # generation, so it never appears on the Recents shelf.
    generated = _image("gen", "a cat", 50, 1)
    imported = _row("imp", "sdxl_t2i", {"seed": 9}, "imp.png", source="imported")
    view = GalleryView(FakeDB([imported, generated]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert view.visible_prompt_ids() == ["gen"]


def test_clicking_a_recent_item_previews_it_without_leaving_the_shelf(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    view._thumb_widgets["i2"].clicked.emit("i2")  # click the recent tile for the dog
    # Its details fill the info pane, but the shelf stays put — no navigation, so
    # every recent item is still listed.
    assert view.selected_generation() == "i2"
    assert view._showing_recents()
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}


def test_double_clicking_a_recent_item_opens_it_selected_in_its_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    # Double-clicking a recent tile is the whole jump — no button stands in for it.
    view._thumb_widgets["i2"].double_clicked.emit("i2")
    assert view.selected_generation() == "i2"
    assert view._showing_recents() is False             # off the shelf...
    assert set(view.visible_prompt_ids()) == {"i2"}     # ...into the dog's own folder
    # The item lands selected — its tile picked and highlighted, not merely
    # previewed — as if we'd navigated in and clicked it.
    assert view.selected_prompt_ids() == ["i2"]         # landed selected
    assert view._thumb_widgets["i2"].is_selected()


def _right_click(view, prompt_id):
    """Right-click a tile the way Qt does — through the widget's own custom-context
    signal — so a menu the pane never connected registers as no menu at all."""
    view._thumb_widgets[prompt_id].customContextMenuRequested.emit(QPoint(0, 0))


def test_right_clicking_a_recent_item_offers_star_enhance_and_delete(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    labels = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda menu, *a: labels.extend(act.text() for act in menu.actions()),
    )

    _right_click(view, "i2")

    # The shelf's tiles carry the same menu a folder's tiles do.
    assert labels == ["Star 1 item", "Enhance 1 image", "Delete 1 item"]
    assert view.selected_prompt_ids() == ["i2"]  # right-clicking picked it


def test_right_click_delete_on_the_recents_shelf_removes_the_item(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    monkeypatch.setattr(  # Delete is the menu's last entry
        "origenerator.gui.gallery_view.QMenu.exec", lambda menu, *a: menu.actions()[-1]
    )

    _right_click(view, "i1")

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


def test_right_click_star_on_the_recents_shelf_bookmarks_the_item(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    monkeypatch.setattr(  # Star/Unstar is the menu's first entry
        "origenerator.gui.gallery_view.QMenu.exec", lambda menu, *a: menu.actions()[0]
    )

    _right_click(view, "i1")

    assert db.get_generation("i1")["starred"]                # persisted
    assert view._showing_recents()                           # still on the shelf
    assert view._thumb_widgets["i1"].is_starred() is True    # tile updated on rebuild


def test_right_click_enhance_on_the_recents_shelf_queues_the_image(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    monkeypatch.setattr(  # Enhance sits between Star and Delete
        "origenerator.gui.gallery_view.QMenu.exec", lambda menu, *a: menu.actions()[1]
    )

    _right_click(view, "g0")

    (job,) = view._reroll_jobs.values()
    assert job.workflow.name == "image_enhance"


def test_recents_shelf_shows_empty_state_when_only_imports_exist(qtbot):
    imported = _row("imp", "sdxl_t2i", {"seed": 9}, "imp.png", source="imported")
    view = GalleryView(FakeDB([imported]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert view.visible_prompt_ids() == []  # nothing generated: just the hint


def test_recents_shelf_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])

    view.refresh()  # a poll-driven rebuild must not knock us off the shelf

    assert view._tree.currentItem().text(0) == "Recents"


def _many_recents(count):
    """``count`` generated images, newest first, so the shelf runs past one page."""
    return [_image(f"i{n}", "a cat", 50, n) for n in reversed(range(count))]


def _scroll_bar(view):
    return view._scroll.verticalScrollBar()


def test_recents_opens_on_one_page_however_far_back_it_goes(qtbot):
    # The shelf lists every generation ever made, so it draws a page of tiles at a
    # time rather than all 120 at once.
    view = GalleryView(FakeDB(_many_recents(120)))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert len(view.visible_prompt_ids()) == 50
    # And it's the newest page — the shelf still reads newest-first.
    assert view.visible_prompt_ids()[0] == "i119"


def test_scrolling_to_the_end_of_recents_draws_the_next_page(qtbot):
    view = GalleryView(FakeDB(_many_recents(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])

    bar = _scroll_bar(view)
    bar.setRange(0, 5000)          # a laid-out shelf with room to scroll
    assert len(view.visible_prompt_ids()) == 50   # ...and no growth up at the top

    bar.setValue(bar.maximum())    # scroll to the end: the next page follows
    assert len(view.visible_prompt_ids()) == 100
    bar.setRange(0, 9000)
    bar.setValue(bar.maximum())
    assert view.visible_prompt_ids() == [f"i{n}" for n in reversed(range(120))]

    bar.setValue(bar.maximum())    # the true end of the shelf: nothing more to draw
    assert len(view.visible_prompt_ids()) == 120


def test_a_rebuild_keeps_the_pages_recents_had_been_scrolled_into(qtbot):
    # A generation landing rebuilds the gallery under the open shelf. That must not
    # collapse it back to one page and throw away everything the user scrolled
    # down through — the new item just joins the top of what's already drawn.
    db = FakeDB(_many_recents(120))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    bar = _scroll_bar(view)
    bar.setRange(0, 5000)
    bar.setValue(bar.maximum())
    assert len(view.visible_prompt_ids()) == 100

    db._rows.insert(0, _image("fresh", "a dog", 50, 999))  # a generation lands
    view.refresh()

    assert len(view.visible_prompt_ids()) == 100      # the two pages stay open...
    assert view.visible_prompt_ids()[0] == "fresh"    # ...led by the new arrival


def test_recents_media_filter_checkboxes_default_on_and_only_show_on_the_shelf(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    # Both boxes start checked, so the shelf opens listing every media type.
    assert view._recents_image_cb.isChecked()
    assert view._recents_video_cb.isChecked()

    # The filter belongs to the Recents shelf: hidden on a media folder...
    view._tree.setCurrentItem(_top_level(view._tree)["Images"])
    assert view._recents_filter_bar.isHidden()
    # ...and shown the moment the shelf is open.
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert not view._recents_filter_bar.isHidden()


def test_recents_media_filter_hides_the_unchecked_media_type(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert set(view.visible_prompt_ids()) == {"i1", "v1"}  # both by default

    view._recents_video_cb.setChecked(False)          # hide videos
    assert view.visible_prompt_ids() == ["i1"]

    view._recents_video_cb.setChecked(True)
    view._recents_image_cb.setChecked(False)          # hide images instead
    assert view.visible_prompt_ids() == ["v1"]

    view._recents_video_cb.setChecked(False)          # both off: nothing to show
    assert view.visible_prompt_ids() == []


def test_a_new_media_filter_reopens_recents_on_its_first_page(qtbot):
    # A filter change is a new listing, not a redraw of the old one, so the shelf
    # starts over at its newest item instead of holding the pages already scrolled.
    view = GalleryView(FakeDB(_many_recents(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    bar = _scroll_bar(view)
    bar.setRange(0, 5000)
    bar.setValue(bar.maximum())
    assert len(view.visible_prompt_ids()) == 100

    view._recents_video_cb.setChecked(False)  # images only — still all 120 of them

    assert len(view.visible_prompt_ids()) == 50
    assert view.visible_prompt_ids()[0] == "i119"


def test_recents_media_filter_also_hides_inflight_cards_of_the_unchecked_type(qtbot):
    # The filter narrows the whole shelf, so an in-flight card of a hidden type
    # drops out alongside the finished thumbnails.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", workflow="wan22_i2v"))  # a running video
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert "rr1" in view._inflight_cards               # shown by default

    view._recents_video_cb.setChecked(False)           # hide videos
    assert "rr1" not in view._inflight_cards


def _write_looping_webp(path, size=(64, 48)):
    """A tiny two-frame looping WebP standing in for a video's moving preview."""
    from PIL import Image as _Image
    frames = [_Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def test_recents_video_tiles_animate_while_images_stay_still(qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    rows = [
        _image("i1", "a cat", 50, 1),
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4"),
    ]
    calls = []

    def fake_anim(row, output_dir, thumb_dir):
        calls.append((row["prompt_id"], output_dir, thumb_dir))
        return str(webp) if gallery.media_type_of_row(row) == "video" else None

    monkeypatch.setattr(gallery, "animated_preview_path", fake_anim)
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])

    assert view._thumb_widgets["v1"].findChildren(QMovie)          # the video loops
    assert view._thumb_widgets["i1"].findChildren(QMovie) == []    # the image is a still
    # Each tile resolved its preview through the shared helper, with the app's dirs.
    assert ("v1", COMFYUI_OUTPUT_DIR, THUMB_DIR) in calls


def test_settings_folder_video_tiles_animate(qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    rows = [_row("v1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4")]
    monkeypatch.setattr(
        gallery, "animated_preview_path",
        lambda row, o, t: str(webp) if gallery.media_type_of_row(row) == "video" else None,
    )
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["v1"])  # the video's settings folder
    assert view._thumb_widgets["v1"].findChildren(QMovie)  # its grid tile loops


def test_recents_tiles_are_badged_image_or_video(qtbot):
    # The shelf mixes kinds, so each finished tile wears a corner badge naming its
    # own — an image thumbnail and a video thumbnail, told apart at a glance.
    rows = [
        _image("i1", "a cat", 50, 1),
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4"),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])

    def badge_type(pid):
        badges = view._thumb_widgets[pid].findChildren(MediaBadge)
        return badges[0].media_type if badges else None

    assert badge_type("i1") == "image"
    assert badge_type("v1") == "video"


def test_inflight_card_is_badged_by_its_media_type(qtbot):
    # A running video row with no file yet still badges its in-flight card a video,
    # inferred from the workflow — so the kind reads before the first frame lands.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["rr1"].media_type == "video"


def test_a_new_generation_appears_at_the_top_of_recents(qtbot):
    db = FakeDB([_image("old", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    assert view.visible_prompt_ids() == ["old"]

    # A fresh generation lands; a poll reflects it at the top of the running list.
    db.add(_image("new", "a dog", 50, 2))
    view._poll()
    assert view.visible_prompt_ids() == ["new", "old"]


def test_new_generations_appear_without_manual_refresh(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    assert set(_top_level(view._tree)) == {"Recents", "Starred", "Experiments", "Trash", "Images"}

    # A new video lands in the DB; a poll tick reflects it with no Refresh button.
    db.add(_row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
                "wan22_i2v_00001_.mp4"))
    view._poll()
    assert set(_top_level(view._tree)) == {
        "Recents", "Starred", "Experiments", "Trash", "Images", "Videos"}


def test_folders_start_collapsed(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    images = _top_level(view._tree)["Images"]
    assert images.isExpanded() is False
    assert images.child(0).isExpanded() is False


def test_opening_a_folder_shows_its_grid_but_selects_nothing(qtbot):
    # Opening a folder used to auto-load its first item; now it shows the grid and
    # selects nothing, so the info pane's tab is left alone until an explicit click.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    # A branch folder shows its child tiles but auto-selects no generation...
    workflow = _top_level(view._tree)["Images"].child(0)
    view._tree.setCurrentItem(workflow)
    assert view._selected is None

    # ...and a leaf folder shows its thumbnails but likewise selects nothing.
    leaf = workflow.child(0).child(0).child(0)
    view._tree.setCurrentItem(leaf)
    assert set(view.visible_prompt_ids()) == {"i1", "i2"}  # the grid is shown
    assert view._selected is None                          # but nothing is picked


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


def _source_tile(view):
    return view._info_tabs.current_config_panel()._source_tile


def test_video_source_tile_points_to_its_image_and_navigates(qtbot):
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs._config_panels():
        panel._preview.show_media = MagicMock()  # don't start WMF playback

    # Viewing the video shows a tile pointing back to the image it was built from.
    view._on_thumbnail_clicked("vid1")
    assert not _source_tile(view).isHidden()
    assert _source_tile(view)._prompt_id == "img1"

    # Clicking that tile navigates the gallery to the source image.
    _source_tile(view).activated.emit("img1")
    assert "img1" in view.visible_prompt_ids()
    assert view._selected["prompt_id"] == "img1"
    # The image itself has no source image, so no tile shows.
    view._on_thumbnail_clicked("img1")
    assert _source_tile(view).isHidden()


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
    assert not view._back_btn.isEnabled() and not view._forward_btn.isEnabled()

    _select_first_leaf(view)   # opening a folder is somewhere to come back from
    view._thumbnail_clicked("i1")
    view._thumbnail_clicked("i2")
    assert view._back_btn.isEnabled() and not view._forward_btn.isEnabled()

    for _ in range(3):
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
    view._thumbnail_clicked("a")                       # viewing it
    assert view._selected["prompt_id"] == "a"
    view._confirm = lambda text: True
    view._delete_folder(view._current_deletable_folder())
    assert db.get_generation("a") is None
    assert view._selected is None                       # navigated off the emptied folder

    view._undo()
    assert db.get_generation("a") is not None            # restored
    assert view._selected["prompt_id"] == "a"            # and back where we deleted from


def test_back_after_following_a_link_returns_to_the_viewed_generation(qtbot):
    # Viewing a generation, then following its source link, records both as history
    # stops; Back returns to the one we were looking at before the link.
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    view._thumbnail_clicked("vid1")               # viewing the video
    assert view._selected["prompt_id"] == "vid1"

    view._on_source_link("img1")                  # follow its source-image link
    assert view._selected["prompt_id"] == "img1"
    view._go_back()
    assert view._selected["prompt_id"] == "vid1"  # Back to where we were


def _linked_view(qtbot, source="i7", count=12):
    """A view on a video whose start frame is one of ``count`` sibling images, with
    the browser pane's scrolling recorded — the setup for following a source link
    into a folder big enough that landing on the right tile matters."""
    images = [_image(f"i{n}", "a cat", 50, n) for n in range(1, count + 1)]
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": f"sdxl_t2i_{source}.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video] + images))
    qtbot.addWidget(view)
    view.refresh()
    scrolled = []
    view._scroll.ensureWidgetVisible = lambda widget, *margins: scrolled.append(widget)
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    view._thumbnail_clicked("vid1")               # viewing the video
    return view, scrolled


def test_following_a_source_link_lands_on_the_image_itself(qtbot):
    # Opening the folder the source image lives in isn't enough: with a dozen
    # siblings in it, which one the link meant has to be picked out — highlighted,
    # and scrolled to rather than left off the bottom of the pane.
    view, scrolled = _linked_view(qtbot)

    view._on_source_link("i7")                    # follow its source-image link

    assert view.selected_prompt_ids() == ["i7"]
    assert view._thumb_widgets["i7"].is_selected()
    assert scrolled == [view._thumb_widgets["i7"]]


def test_a_followed_link_scrolls_again_once_the_folder_is_laid_out(qtbot):
    # The folder's tiles are created but not yet positioned when the link lands, so
    # that first scroll has no real tile position to aim at. A second pass, after
    # this turn's layout has run, is what actually puts the tile on screen.
    view, scrolled = _linked_view(qtbot)

    view._on_source_link("i7")
    qtbot.wait(1)

    tile = view._thumb_widgets["i7"]
    assert scrolled == [tile, tile]


def test_a_followed_link_does_not_scroll_a_folder_moved_on_from(qtbot):
    # Navigating away before that second pass runs leaves it nothing to do: the
    # tile is gone, and the view the user chose instead isn't ours to move.
    view, scrolled = _linked_view(qtbot)

    view._on_source_link("i7")
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])  # back off before layout
    scrolled.clear()
    qtbot.wait(1)

    assert scrolled == []


def test_history_spans_folder_navigation(qtbot):
    # Every place the user went is a stop: the folder they opened and the item they
    # then viewed in it, so Back retraces the walk rather than skipping the folders.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])  # browse to the video folder
    view._thumbnail_clicked("v1")                      # view its item
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # then to the image folder
    view._thumbnail_clicked("i1")                      # view its item
    assert view._selected["prompt_id"] == "i1"

    view._go_back()                                    # the image folder
    view._go_back()                                    # the video folder
    view._go_back()
    assert view._selected["prompt_id"] == "v1"  # Back walks generations across folders


def test_back_returns_to_the_recents_shelf_then_forward_reopens_the_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    view._thumb_widgets["i2"].double_clicked.emit("i2")  # open i2 in its folder
    assert view._showing_recents() is False
    assert view._back_btn.isEnabled()                    # the shelf is somewhere to go back to

    view._go_back()
    assert view._showing_recents()                       # Back returns to the Recents shelf

    view._go_forward()
    assert view._showing_recents() is False              # Forward re-opens the folder
    assert view.selected_generation() == "i2"


def test_back_returns_to_a_shelf_left_by_opening_a_folder(qtbot):
    # The reported bug: a folder was no history stop at all, so leaving Recents by
    # clicking one in the tree recorded nothing and Back had nowhere to go from —
    # the shelf was on the stack, but the cursor was still sitting on it.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])

    view._tree.setCurrentItem(
        _top_level(view._tree)["Images"].child(0).child(0).child(0).child(0)
    )
    assert view._showing_recents() is False
    assert view._back_btn.isEnabled()

    view._go_back()

    assert view._showing_recents()


def test_back_walks_folders_the_way_it_walks_generations(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    cat, dog = lora.child(0), lora.child(1)
    view._tree.setCurrentItem(cat)
    view._tree.setCurrentItem(dog)

    view._go_back()

    assert view._tree.currentItem() is cat

    view._go_forward()

    assert view._tree.currentItem() is dog


def test_reopening_the_same_folder_is_not_a_second_history_stop(qtbot):
    # A rebuild re-selects the open folder every poll; each must not pile onto the
    # stack or Back would walk a hundred copies of where the user already is.
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    leaf = _top_level(view._tree)["Images"].child(0).child(0).child(0).child(0)
    view._tree.setCurrentItem(leaf)
    depth = len(view._history._stack)

    view.refresh()
    view._poll()

    assert len(view._history._stack) == depth


def test_back_returns_to_the_starred_shelf_after_drilling_into_a_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    dog_key = _key(_top_level(view._tree)["Images"].child(0).child(0).child(0).child(1))
    view._toggle_star(dog_key)

    view._tree.setCurrentItem(_top_level(view._tree)["Starred"])
    view._drill_into(view.visible_folder_keys()[0])      # into the dog folder
    view._thumbnail_clicked("i2")                        # view an item there
    assert view._tree.currentItem() is not view._starred_item

    view._go_back()                                      # the folder drilled into
    view._go_back()
    assert view._tree.currentItem() is view._starred_item  # Back returns to Starred


def test_back_to_recents_restores_the_item_selected_on_the_shelf(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    view._thumb_widgets["i2"].clicked.emit("i2")         # select i2 on the shelf
    view._thumb_widgets["i2"].double_clicked.emit("i2")  # open it in its folder
    assert view._showing_recents() is False

    view._go_back()
    assert view._showing_recents()                       # back on the shelf...
    assert view.selected_generation() == "i2"            # ...with i2 previewed again
    assert view._thumb_widgets["i2"].is_selected()       # and its tile re-highlighted


def test_previewing_on_the_shelf_is_not_its_own_history_step(qtbot):
    # Selecting items on the shelf is shelf state, not navigation: Back leaves the
    # shelf for wherever you came from, rather than stepping through each preview.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])    # land on a folder's item
    view._thumbnail_clicked("i1")
    landing = view.selected_generation()
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])
    view._thumb_widgets["i1"].clicked.emit("i1")         # browse a couple of previews
    view._thumb_widgets["i2"].clicked.emit("i2")

    view._go_back()
    assert view._showing_recents() is False              # Back leaves the shelf...
    assert view.selected_generation() == landing         # ...to where we came from


def _animated_strip(view):
    return view._info_tabs.current_config_panel()._animated_strip


def test_selecting_an_image_lists_the_videos_it_was_animated_into(qtbot):
    from origenerator.gui.animated_strip import _VideoTile
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, video]), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("img1")
    assert not _animated_strip(view).isHidden()
    assert len(_animated_strip(view).findChildren(_VideoTile)) == 1

    # Clicking the preview navigates to that video.
    _animated_strip(view).video_activated.emit("vid1")
    assert view._selected["prompt_id"] == "vid1"


def test_animation_strip_is_hidden_for_a_video_or_an_unanimated_image(qtbot):
    from origenerator.gui.animated_strip import _VideoTile
    image = _image("img1", "a cat", 50, 1)
    lonely = _image("img2", "a dog", 50, 2)  # never animated
    video = _row("vid1", "wan22_i2v",
                 {"input_image": "sdxl_t2i_img1.png"}, "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, lonely, video]), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs._config_panels():
        panel._preview.show_media = MagicMock()  # don't start WMF playback

    view._on_thumbnail_clicked("vid1")   # a video isn't "animated into" anything
    assert _animated_strip(view).isHidden()

    view._on_thumbnail_clicked("img2")   # an image nothing was made from
    assert _animated_strip(view).isHidden()
    assert _animated_strip(view).findChildren(_VideoTile) == []


def test_clicking_thumbnail_shows_resolved_preview(qtbot, monkeypatch):
    from origenerator.gui import generate_config_panel as gcp_module
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.show_media = MagicMock()
    resolved = (Path("C:/out/sdxl_t2i_i1.png"), "image")
    monkeypatch.setattr(gcp_module, "resolve_preview", MagicMock(return_value=resolved))

    view._on_thumbnail_clicked("i1")

    # The loaded tab resolves the selection's output and shows it last (after any
    # settings-folder autoshow the form prefill does).
    assert view._preview.show_media.call_args.args == (resolved[0], "image")


def test_clicking_thumbnail_without_media_clears_preview(qtbot, monkeypatch):
    from origenerator.gui import generate_config_panel as gcp_module
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._preview.clear = MagicMock()
    view._preview.show_media = MagicMock()
    monkeypatch.setattr(gcp_module, "resolve_preview", MagicMock(return_value=None))

    view._on_thumbnail_clicked("i1")

    # Nothing displayable resolved for the selection, so the preview ends cleared.
    assert view._preview.clear.called
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


def test_info_pane_is_a_tab_widget_of_editable_config_tabs(qtbot):
    from PyQt6.QtWidgets import QTabWidget
    from origenerator.gui.generate_config_panel import GenerateConfigPanel
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    # The info pane is a tab widget of identical editable generate panels — no
    # special or permanent tab. The first one opens on construction, hosting the
    # preview a selection lands in.
    assert isinstance(view._info_tabs, QTabWidget)
    assert view._panes.widget(2) is view._info_tabs
    assert isinstance(view._info_tabs.widget(0), GenerateConfigPanel)
    assert view._info_tabs.widget(0).isAncestorOf(view._preview)


def test_selecting_a_thumbnail_loads_it_into_the_front_tab(qtbot):
    # Picking an item loads it into a config tab, brought to the front.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("i1")

    panel = view._info_tabs.current_config_panel()
    assert panel is view._info_tabs.currentWidget()
    assert panel._displayed_row["prompt_id"] == "i1"


def test_a_suppressed_reselection_leaves_the_active_tab_alone(qtbot):
    # A poll/rebuild re-selects the current generation with history suppressed; that
    # must not yank the user off a config tab they're editing or fork a new one.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient())
    qtbot.addWidget(view)
    editing = view._info_tabs._add_subtab()  # config tab at index 1, current
    count = view._info_tabs.count()
    view._suppress_history = True
    view._on_thumbnail_clicked("i1")
    view._suppress_history = False
    assert view._info_tabs.currentWidget() is editing  # stayed on the config tab
    assert view._info_tabs.count() == count            # no new tab forked
    assert editing._displayed_row is None              # its form/footer untouched


def _current_form(view):
    return view._info_tabs.current_config_panel()._param_form


def test_selecting_a_thumbnail_loads_its_params_into_the_form(qtbot, tmp_path):
    # A tab is an editable generate panel: picking a generation seeds its form with
    # that generation's settings, ready to tweak and re-run.
    db = Database(tmp_path / "t.db")
    params = dict(_SDXL.default_params(), positive_prompt="a wizard", seed=123)
    db.insert_generation(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a wizard", seed=123,
        params_json=json.dumps(params), workflow_json="{}",
    )
    view = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("g1")

    values = _current_form(view).get_values_static()
    assert values["positive_prompt"] == "a wizard"
    assert values["seed"] == 123


def test_a_suppressed_reselection_does_not_reload_the_form(qtbot, tmp_path):
    # A poll/rebuild re-selects the current generation with history suppressed; that
    # must not wipe edits the user has made in the form.
    db = Database(tmp_path / "t.db")
    params = dict(_SDXL.default_params(), positive_prompt="a wizard")
    db.insert_generation(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a wizard", params_json=json.dumps(params), workflow_json="{}",
    )
    view = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g1")           # loads the form
    _current_form(view).set_values({"positive_prompt": "my edit"})

    view._suppress_history = True
    view._on_thumbnail_clicked("g1")
    view._suppress_history = False

    assert _current_form(view).get_values_static()["positive_prompt"] == "my edit"


def test_selecting_an_unregistered_thumbnail_leaves_the_reused_tab_alone(qtbot, tmp_path):
    # Selecting an unregistered generation (a different folder) forks a fresh tab
    # rather than corrupting the one showing a rebuildable generation.
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="reg", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", params_json=json.dumps(dict(_SDXL.default_params())),
        workflow_json="{}",
    )
    db.insert_generation(
        prompt_id="unreg", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    view = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("reg")
    reg_panel = view._info_tabs.current_config_panel()
    reg_before = reg_panel._param_form.get_values_static()

    view._on_thumbnail_clicked("unreg")  # a different folder → a fresh tab

    # The rebuildable tab keeps its form; the new tab (unregistered) left its own
    # form as-is but now displays the imported row.
    assert reg_panel._param_form.get_values_static() == reg_before
    assert view._info_tabs.current_config_panel()._displayed_row["prompt_id"] == "unreg"


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
    # Images -> SDXL workflow -> model -> "(no LoRA)" -> dog settings leaf (cat is sibling 0).
    dog_leaf = _top_level(saved._tree)["Images"].child(0).child(0).child(0).child(1)
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


def test_selecting_generation_shows_typical_time_in_the_loaded_tab(qtbot):
    # Loading a generation into a config tab seeds its form with the generation's
    # workflow, whose estimate line then reads that workflow's typical time.
    rows = [
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ]
    view = GalleryView(FakeDB(rows), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs._config_panels():
        panel._preview.show_media = MagicMock()

    view._on_thumbnail_clicked("v1")
    estimate = view._info_tabs.current_config_panel()._estimate_label
    assert estimate.text() == "Typical time: ~12 min (based on 3 runs)"


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


# --- deletion & undo ------------------------------------------------------

def _open_leaf(view):
    """Select the first settings-group leaf so its thumbnails are showing."""
    workflow = _top_level(view._tree)["Images"].child(0)
    leaf = workflow.child(0).child(0).child(0)  # workflow -> model -> "(no LoRA)" -> settings
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


def test_a_branch_session_deletes_nothing_out_of_the_library(qtbot, monkeypatch, tmp_path):
    # The composition, not just the rule: a preview's gallery builds its actions
    # around a trash that takes nothing, so deleting a tile forgets the row in
    # its own copied database and leaves the file for the live app, whose own
    # row still points at it.
    monkeypatch.setenv(ENV_FLAG, "1")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.write_bytes(b"data")
    monkeypatch.setattr(gallery_view_module, "COMFYUI_OUTPUT_DIR", output_dir)
    monkeypatch.setattr(gallery_view_module, "STATE_DIR", tmp_path / "state")
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)  # builds its own actions, the way the app does
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._apply_selection("i1", _NO_MOD)
    view._delete_selection()

    assert db.get_generation("i1") is None
    assert file_path.exists()


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


def test_a_starred_row_renders_a_starred_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_starred("i2", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    assert view._thumb_widgets["i1"].is_starred() is False
    assert view._thumb_widgets["i2"].is_starred() is True


def test_right_click_star_bookmarks_the_picked_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    # The menu's first entry is Star/Unstar (Delete is last).
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[0]
    )

    view._thumbnail_context_menu("i1", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]           # persisted
    assert view._thumb_widgets["i1"].is_starred() is True  # tile updated on rebuild


def test_right_click_unstar_clears_a_starred_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    db = FakeDB(rows)
    db.set_generation_starred("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    labels = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda self, *a: (labels.append(self.actions()[0].text()), self.actions()[0])[1],
    )

    view._thumbnail_context_menu("i1", QPoint(0, 0))

    assert labels == ["Unstar 1 item"]                 # a starred item offers Unstar
    assert not db.get_generation("i1")["starred"]      # cleared


def test_right_click_star_acts_on_the_whole_multi_selection(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._apply_selection("i1", _NO_MOD)
    view._apply_selection("i3", _CTRL)  # i1 + i3 selected
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[0]
    )

    view._thumbnail_context_menu("i3", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]
    assert db.get_generation("i3")["starred"]
    assert not db.get_generation("i2").get("starred")  # untouched


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
    view._tree.setCurrentItem(model.child(0).child(0))  # one of the two settings leaves
    view._confirm = lambda text: True

    view._delete_selection()  # deletes that settings folder

    # The leaf's parent — the "(no LoRA)" folder — survives via its sibling leaf,
    # so the tree falls back onto it rather than jumping up to the top.
    current = view._tree.currentItem().data(0, _GROUP_ROLE)
    assert isinstance(current, gallery.LoraGroup)


def test_deleting_a_folder_returns_to_the_most_recent_one_still_there(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    for pid, prompt in [("i1", "a cat"), ("i2", "a dog")]:  # two settings folders
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
    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # the (no LoRA) folder
    first_leaf, second_leaf = lora.child(0), lora.child(1)
    first_key = first_leaf.data(0, _GROUP_ROLE).key
    view._tree.setCurrentItem(first_leaf)   # visit the first settings folder
    view._tree.setCurrentItem(second_leaf)  # then the second (now current)
    view._confirm = lambda text: True

    view._delete_selection()  # deletes the second folder

    # Return to the first — the most recent folder we were in that still exists —
    # rather than the deleted folder's parent.
    current = view._tree.currentItem().data(0, _GROUP_ROLE)
    assert isinstance(current, gallery.SettingsGroup)
    assert current.key == first_key


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


def test_a_delete_can_let_go_of_the_files_it_is_about_to_move(qtbot):
    # The app holding a file open is what used to fail its own delete: Windows
    # refuses to move one. Hung off the actions rather than any one caller, so it
    # covers every delete there is — a picked tile, a folder, a rejected
    # experiment, a slideshow's Up key.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert view._actions._release_files == view._release_held_media


def test_releasing_held_media_clears_a_pane_behind_the_one_in_front(qtbot, tmp_path):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    doomed = tmp_path / "doomed.png"
    doomed.write_bytes(b"x")
    behind = view._info_tabs.current_config_panel()
    behind._preview.show_image(doomed)
    view._info_tabs._add_subtab()  # a second tab takes the front

    view._release_held_media([doomed])

    assert not behind._preview.is_showing_any([doomed])


def test_releasing_held_media_reaches_an_open_slideshow(qtbot, tmp_path):
    # Its Up key condemns the very item it's playing — the file it holds open.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view._slideshow = MagicMock()

    view._release_held_media([tmp_path / "clip.mp4"])

    view._slideshow.release_media.assert_called_once()


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
    # media -> workflow -> model -> "(no LoRA)" -> settings (the thumbnail leaf)
    leaf = _top_level(view._tree)["Images"].child(0).child(0).child(0).child(0)
    view._tree.setCurrentItem(leaf)
    return leaf.data(0, _GROUP_ROLE).key


def _seeded_db(tmp_path, seed=7):
    """A DB holding one completed SDXL image with full, re-rollable params —
    stamped with the workflow's current version, as a run made by this app would
    be (the settings key folds the version in, so a stale one would put re-rolls
    of this row in a different folder)."""
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="orig",
        workflow_name="sdxl_t2i",
        workflow_version=_SDXL.version,
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


# --- auto-generate: the folder re-roll on a loop until stopped --------------

def test_toggling_auto_starts_a_reroll_loop(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._auto_btn.click()  # the header's Auto toggle, switched on

    assert view._auto.is_active(key)
    assert key in view._reroll_jobs          # a first variation is running
    client.submit_job.assert_called_once()
    assert view._auto_btn.isChecked()


def test_auto_relaunches_when_a_variation_finishes(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._reroll_jobs[key]

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the variation finishes

    assert client.submit_job.call_count == 2   # the next one was launched
    assert view._auto.is_active(key)
    assert key in view._reroll_jobs            # a fresh variation is running


def test_toggling_auto_off_stops_the_loop(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._reroll_jobs[key]

    view._toggle_auto(False)
    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert client.submit_job.call_count == 1   # not relaunched after stop
    assert not view._auto.is_active(key)


def test_auto_stops_when_a_variation_fails(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._reroll_jobs[key]

    client.job_error.emit(job.prompt_id, "boom")   # ComfyUI rejected it

    assert not view._auto.is_active(key)
    assert client.submit_job.call_count == 1       # did not spin on the failure


def test_cancelling_a_reroll_stops_the_auto_loop(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)

    view._cancel_reroll(key)  # cancelling the in-flight job also ends the loop

    assert not view._auto.is_active(key)


def test_auto_toggle_hidden_off_a_settings_leaf(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._auto_btn.isHidden()             # offered on a re-rollable leaf

    view._tree.setCurrentItem(_top_level(view._tree)["Images"])  # a media root, not a leaf
    assert view._auto_btn.isHidden()


# --- a tab's Generate is a re-roll of its folder, navigated to at once ---------

def _generate_in_current_tab(view, positive_prompt, seed):
    """Prefill the front config tab with a full sdxl config and click Generate,
    returning the settings folder the launched re-roll runs in."""
    panel = view._info_tabs.current_config_panel()
    params = dict(_SDXL.default_params(), positive_prompt=positive_prompt, seed=seed)
    panel.prefill("sdxl_t2i", params)
    panel._param_form.set_seed_random(False)  # a fixed seed, so the config is concrete
    panel._on_generate()
    return gallery.settings_folder_key(
        {"workflow_name": "sdxl_t2i", "params_json": json.dumps(params)},
        gallery.build_image_config_index(view._image_rows),
    )


def test_generate_launches_a_reroll_in_the_configs_existing_folder(qtbot, tmp_path):
    # Change 1: Generate in a tab whose settings match an existing folder launches a
    # re-roll there and lands the browser in that folder, its live tile selected.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    orig_folder = _select_first_leaf(view)      # the folder 'orig' already lives in
    view._tree.setCurrentItem(_top_level(view._tree)["Images"])  # navigate away first

    folder = _generate_in_current_tab(view, positive_prompt="a cat", seed=123)

    assert folder == orig_folder                    # same settings folder as 'orig'
    assert folder in view._reroll_jobs              # a re-roll now runs in it
    assert view._selected_folder_key() == folder    # and the view jumped there
    assert view._selected_reroll_key == folder      # its live tile drives the info pane


def test_generate_navigates_to_a_brand_new_folder_immediately(qtbot, tmp_path):
    # Change 3: edited params make a settings folder with no finished result yet, but
    # the re-roll's running row gives it a tree node at once — so the view navigates
    # there DURING generation, not only when it finishes.
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    before = set(view._item_by_key)

    folder = _generate_in_current_tab(view, positive_prompt="a totally new prompt", seed=5)

    assert folder not in before                     # a brand-new folder...
    assert folder in view._item_by_key              # ...that now has a node (its running row)
    assert folder in view._reroll_jobs              # the re-roll is in flight
    assert view._selected_folder_key() == folder    # navigated to at once, mid-generation


# --- voice steering: Auto is voice's "on"; utterances steer the loop's prompt --

def test_turning_auto_on_starts_voice_and_steers_the_prompt(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_auto(True)
    assert view._voice.started
    (launch_key,) = view._reroll_jobs.keys()  # the folder the first generation lands in

    view._voice.say({"positive": "a cat, no hat", "negative": "ugly"})  # rewritten pair
    client.job_completed.emit(view._reroll_jobs[launch_key].prompt_id, _REROLL_HISTORY)

    # the loop re-homed to the new-prompt folder, carrying both steered prompts
    assert launch_key not in view._reroll_jobs
    (new_key,) = view._reroll_jobs.keys()
    assert new_key != launch_key and view._auto.is_active(new_key)
    assert view._reroll_jobs[new_key].params["positive_prompt"] == "a cat, no hat"
    assert view._reroll_jobs[new_key].params["negative_prompt"] == "ugly"

    # completing the re-homed generation makes its folder exist -> the view follows
    client.job_completed.emit(view._reroll_jobs[new_key].prompt_id, _REROLL_HISTORY)
    assert view._selected_folder_key() == new_key


def test_turning_auto_off_stops_voice(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_auto(True)
    view._toggle_auto(False)

    assert view._voice.stopped


def test_voice_status_caption_shows_listening_and_what_was_heard(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_auto(True)
    assert not view._voice_status.isHidden()
    assert "Listening" in view._voice_status.text()

    view._voice.heard.emit("no hat")
    assert "no hat" in view._voice_status.text()

    view._toggle_auto(False)
    assert view._voice_status.isHidden()


def test_voice_status_caption_keeps_clear_of_the_header_buttons(qtbot, tmp_path):
    # It used to float centered over the top of the view, landing squarely on the
    # header toolbar the user was trying to click. It now takes its own room at
    # the top of the left pane, so it covers nothing however long the message.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1200, 800)
    view.show()
    qtbot.waitExposed(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_auto(True)
    view._voice.heard.emit("give her a much longer caption than the idle one")
    qtbot.wait(1)  # let the layout settle around the grown caption

    caption = QRect(view._voice_status.mapTo(view, QPoint(0, 0)), view._voice_status.size())
    for button in (view._back_btn, view._forward_btn, view._undo_btn, view._delete_btn):
        assert not caption.intersects(
            QRect(button.mapTo(view, QPoint(0, 0)), button.size())
        )
    assert caption.bottom() <= view._filter_edit.mapTo(view, QPoint(0, 0)).y()


def test_esc_stops_auto_generate(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    assert view._auto.is_active(key)

    handled = view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )

    assert handled is True
    assert not view._auto.is_active(key)


# --- slideshow: play a folder's or a shelf's media fullscreen ---------------

def _resolve_by_id(monkeypatch):
    """Resolve every row's preview to a per-row image path (the autouse default
    stubs resolution to None, which would leave the slideshow nothing to seed)."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: (f"{row['prompt_id']}.png", "image"))


def test_slideshow_opens_the_folders_media(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    assert len(view._slideshow._playlist) == 2  # both variations queued to play
    view._slideshow.close()


def test_slideshow_button_follows_what_is_on_screen(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_starred("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._slideshow_btn.isHidden()          # a folder with media offers it
    assert "this folder" in view._slideshow_btn.toolTip()

    # The shelves are collections of media too, so each plays as a folder does...
    view._tree.setCurrentItem(view._recents_item)
    assert not view._slideshow_btn.isHidden()
    assert "Recents" in view._slideshow_btn.toolTip()
    view._tree.setCurrentItem(view._starred_item)
    assert not view._slideshow_btn.isHidden()
    assert "Starred" in view._slideshow_btn.toolTip()

    # ...while a shelf holding nothing at all doesn't offer one.
    view._tree.setCurrentItem(view._experiments_item)
    assert view._slideshow_btn.isHidden()


def test_slideshow_plays_the_recents_shelf(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._recents_item)

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    assert len(view._slideshow._playlist) == 2  # both recent generations queued
    view._slideshow.close()


def test_recents_slideshow_honors_the_media_type_filter(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._recents_item)
    view._recents_video_cb.setChecked(False)  # the shelf now lists images only

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    # It plays what the shelf shows, not everything recent.
    assert [item[2] for item in view._slideshow._playlist._items] == ["i1"]
    view._slideshow.close()

    view._recents_image_cb.setChecked(False)  # nothing left on the shelf to play
    assert view._slideshow_btn.isHidden()


def test_slideshow_plays_the_experiments_shelf(qtbot, monkeypatch):
    # Reviewing a batch of experiments is exactly what a slideshow is for: full
    # screen, one at a time, rather than squinting at a grid of thumbnails.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([
        _experiment_row("e1"),
        _experiment_row("e2", seed=10),
        _experiment_row("e3", verdict="up", seed=11),  # reviewed: off the shelf
    ]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._experiments_item)
    assert not view._slideshow_btn.isHidden()
    assert "Experiments" in view._slideshow_btn.toolTip()

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    # What the shelf shows, so the judged one stays out of the rotation.
    assert {item[2] for item in view._slideshow._playlist._items} == {"e1", "e2"}
    view._slideshow.close()


def test_condemning_an_experiment_in_a_slideshow_rejects_it(qtbot):
    # Up on an unreviewed experiment is the shelf's Reject, not a plain delete:
    # the row survives to teach the policy what to steer away from.
    db = FakeDB([_experiment_row("e1"), _image("i1", "a cat", 50, 1)])
    actions = FakeActions()
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._trash_generation("e1")
    view._trash_generation("i1")

    assert [r["prompt_id"] for r in actions.rejected] == ["e1"]
    assert [r["prompt_id"] for batch in actions.deleted for r in batch] == ["i1"]


def test_starred_slideshow_plays_starred_items_and_folders_once(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    db.set_generation_starred("i2", True)  # a starred item...
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)  # "(no LoRA)"
    view._toggle_star(_key(lora.child(0)))   # ...and a starred folder (the cat one)
    view._tree.setCurrentItem(view._starred_item)

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    # The item, plus what the bookmarked folder's tile stands for.
    assert {item[2] for item in view._slideshow._playlist._items} == {"i1", "i2"}
    view._slideshow.close()


def test_enter_in_a_shelf_slideshow_lands_in_the_items_own_folder(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._recents_item)
    view._start_slideshow()
    slideshow = view._slideshow
    qtbot.addWidget(slideshow)
    shown = slideshow._playlist.current()[2]

    slideshow.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, _NO_MOD))

    assert view._slideshow is None                  # out of the slideshow...
    assert shown in view.visible_prompt_ids()       # ...into the folder holding it
    assert view._browser.selected_ids == {shown}    # with that item picked


def test_slideshow_items_carry_each_rows_thumbnail(qtbot, monkeypatch):
    # The neighbor stills either side of the shown item are drawn from these —
    # a video has no other still to show small.
    _resolve_by_id(monkeypatch)
    row = dict(_image("i1", "a cat", 50, 1), thumbnail_path="thumb.png")
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    view.refresh()

    assert view._slideshow_items([row])[0] == ("i1.png", "image", "i1", "thumb.png")


def test_starred_slideshow_plays_a_starred_item_in_a_starred_folder_once(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_starred("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._toggle_star(_select_first_leaf(view))  # star the folder holding it too
    view._tree.setCurrentItem(view._starred_item)

    view._start_slideshow()

    qtbot.addWidget(view._slideshow)
    assert [item[2] for item in view._slideshow._playlist._items] == ["i1"]  # not twice
    view._slideshow.close()


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


def test_finishing_a_reroll_loads_its_result_into_the_front_tab(qtbot, tmp_path):
    # Change 4: a Generate ends on its result. When the re-roll it launched finishes,
    # the just-saved generation loads into the front config tab (show_completed_result),
    # so the tab shows the finished item — not the live-frame or idle placeholder.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the re-roll finishes

    panel = view._info_tabs.current_config_panel()
    assert panel._displayed_row is not None
    assert panel._displayed_row["prompt_id"] == job.prompt_id  # the just-finished result


def test_finishing_a_reroll_keeps_a_prompt_typed_while_it_ran(qtbot, tmp_path):
    # The reported bug, end to end: the user keeps typing the next prompt while a
    # Generate runs; when it finishes, loading its result into the front tab must
    # not re-seed the form and wipe what they typed.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    panel = view._info_tabs.current_config_panel()
    panel._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the re-roll finishes

    assert panel._param_form.get_values_static()["positive_prompt"] == "a wizard mid-edit"


def test_canceling_a_selected_reroll_releases_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _reroll_tile(view).selected.emit()

    view._cancel_reroll(key)

    assert view._selected_reroll_key is None


class _FakeLiveFullscreen(QWidget):
    """Stands in for the FullscreenPreview a double-click pops open, recording what
    the running generation feeds it — without a real media backend."""

    closed = pyqtSignal()
    media_changed = pyqtSignal()
    delete_requested = pyqtSignal(str)
    star_requested = pyqtSignal(str)

    def __init__(self, media, *, frame=None, **kwargs):
        super().__init__()
        self.media = media
        self.frames = [frame] if frame is not None else []
        self.landed = None
        self.levels = None
        self.enhance_hook = None
        self.enhanced = None
        self._live = media is None

    def set_levels(self, levels_by_path):
        self.levels = levels_by_path

    def set_enhance(self, on_enhance, ids_by_path):
        self.enhance_hook = (on_enhance, ids_by_path)

    def note_enhanced(self, prompt_id, path, media_type="image"):
        self.enhanced = (prompt_id, path, media_type)

    def is_live(self):
        return self._live

    def show_frame(self, data):
        self.frames.append(data)

    def show_landed(self, media):
        self.landed = media
        self._live = False

    def showFullScreen(self):
        self.show()

    def set_stroke(self, stroke):
        pass

    def osr2_drive_target(self):
        return None


def test_a_generation_can_be_watched_fullscreen_while_it_is_still_being_made(
        qtbot, tmp_path, monkeypatch):
    # The reported gap, end to end: double-clicking the preview mid-generation did
    # nothing. Now it opens over the live frames, keeps streaming them, and lands on
    # the finished image when the run completes.
    from origenerator.gui import fullscreen_preview as fs_module
    from origenerator.gui import generate_config_panel as gcp_module
    monkeypatch.setattr(fs_module, "FullscreenPreview", _FakeLiveFullscreen)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _reroll_tile(view).selected.emit()
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)

    win = view._preview.open_fullscreen()  # the double-click, mid-generation
    qtbot.addWidget(win)
    assert win is not None and win.is_live()
    assert win.frames == [frame]  # seeded with what was on screen

    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")  # a later, redder frame
    later = buf.getvalue()
    client.preview_image.emit(job.prompt_id, later)
    assert win.frames == [frame, later]  # the run goes on streaming into it

    done = tmp_path / "done.png"
    Image.new("RGB", (8, 8), (10, 120, 200)).save(done, "PNG")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, output_dir: (done, "image"))

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert win.landed == (done, "image")  # ends on the result, not the last frame


def test_a_cancelled_generation_closes_the_view_watching_it(qtbot, tmp_path):
    # Nothing will ever land, so the view would sit on a stale partial frame.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _reroll_tile(view).selected.emit()
    fs = _FakeFullscreen(None, live=True)
    view._on_fullscreen_opened(fs)

    view._cancel_reroll(key)

    assert fs.closes == 1


def test_a_cancelled_generation_leaves_a_plain_fullscreen_alone(qtbot, tmp_path):
    # One opened over a saved file has its own thing on screen: it stays up.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _reroll_tile(view).selected.emit()
    fs = _FakeFullscreen(None)
    view._on_fullscreen_opened(fs)

    view._cancel_reroll(key)

    assert fs.closes == 0


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


def _waiting_view(qtbot, tmp_path, backlog):
    """A gallery with a selected re-roll ComfyUI hasn't started, ``backlog`` prompts
    ahead of it and no frame yet — the state that used to read as a hang."""
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})  # reconcile finds nothing done
    client.foreign_backlog = MagicMock(return_value=backlog)
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    _reroll_tile(view).selected.emit()
    view._preview.show_message = MagicMock()
    return view, client


def test_a_run_stuck_behind_another_app_says_how_much_is_ahead(qtbot, tmp_path):
    # The reported mystery: a Generate parked behind another client's work looked
    # exactly like a hang. The pane now names what's holding it.
    view, _client = _waiting_view(qtbot, tmp_path, backlog=3)

    view._poll()

    assert view._preview.show_message.call_args.args[0] == "Waiting behind 3 jobs from another app"


def test_the_wait_text_follows_the_queue_as_it_drains(qtbot, tmp_path):
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()

    client.foreign_backlog = MagicMock(return_value=1)  # one finished ahead of us
    view._poll()

    assert view._preview.show_message.call_args.args[0] == "Waiting behind 1 job from another app"


def test_a_queue_of_the_users_own_jobs_leaves_the_plain_waiting_note(qtbot, tmp_path):
    # Only another app's work earns the extra line: waiting on his own queue means
    # ComfyUI is generating something he asked for, which is no mystery at all.
    view, _client = _waiting_view(qtbot, tmp_path, backlog=0)

    view._poll()

    assert view._preview.show_message.call_args.args[0] == "Waiting for preview…"


def test_a_streamed_frame_ends_the_wait_text(qtbot, tmp_path):
    # Once ComfyUI is rendering it, the frame is the answer — don't paint over it.
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()
    job = list(view._reroll_jobs.values())[0]
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._preview.show_message = MagicMock()

    view._poll()

    view._preview.show_message.assert_not_called()


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


def _handpicked_i2v_db(tmp_path):
    """A DB with a single i2v whose start frame is a hand-picked (un-rebuildable)
    image — no source generation, so its image seed can't be re-rolled."""
    db = Database(tmp_path / "hp.db")
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="handpicked.png")),
        workflow_json="{}",
    )
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    return db


def _tooltips(view, prompt_id):
    return [b.toolTip() for b in view._thumb_widgets[prompt_id]._corner_buttons]


def test_i2v_folder_item_carries_both_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")  # the i2v's own settings leaf

    # Its start frame is a re-buildable image, so both per-seed controls show.
    assert _tooltips(view, "vid") == ["Randomize video seed", "Randomize image seed"]


def test_image_folder_item_has_no_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "img")  # a plain SDXL image leaf — not image-conditioned

    assert _tooltips(view, "img") == []


def test_i2v_item_with_a_handpicked_frame_offers_only_the_video_seed(qtbot, tmp_path):
    view = GalleryView(_handpicked_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    # The frame can't be re-rolled, so only the video-seed control is offered.
    assert _tooltips(view, "vid") == ["Randomize video seed"]


def test_video_seed_hover_rerolls_only_the_item_video_seed(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")
    view._reroll.reroll_video_seed = MagicMock()

    view._thumb_widgets["vid"]._corner_buttons[0].click()  # "Randomize video seed"

    view._reroll.reroll_video_seed.assert_called_once()
    _key, row = view._reroll.reroll_video_seed.call_args.args
    assert row["prompt_id"] == "vid"


def test_image_seed_hover_rerolls_only_the_item_image_seed(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")
    view._reroll.reroll_image_seed = MagicMock()

    view._thumb_widgets["vid"]._corner_buttons[1].click()  # "Randomize image seed"

    view._reroll.reroll_image_seed.assert_called_once()
    _key, row, image_rows = view._reroll.reroll_image_seed.call_args.args
    assert row["prompt_id"] == "vid"


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


def test_delete_works_with_gallery_as_the_central_widget(qtbot, tmp_path):
    # Mirror the real app: the gallery is the window's central widget, and the
    # app-wide Delete key filter must still reach it.
    from PyQt6.QtWidgets import QMainWindow
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
    win.setCentralWidget(view)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Images"].child(0).child(0).child(0).child(0))
    view._apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_gallery_hands_off_keys_while_a_config_form_is_focused(qtbot, tmp_path, monkeypatch):
    # The grid and an editable config form are now visible together, so the app-wide
    # Delete/Undo filter must disarm while a config field has focus — its combos and
    # buttons aren't text fields, so without this it would wipe a gallery thumbnail.
    from PyQt6.QtWidgets import QApplication
    view = GalleryView(Database(tmp_path / "t.db"), client=ComfyUIClient())
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    panel = view._info_tabs._add_subtab()

    monkeypatch.setattr(QApplication, "focusWidget", lambda: panel._workflow_combo)
    assert view._gallery_owns_keys() is False   # editing a config: the gallery hands off

    monkeypatch.setattr(QApplication, "focusWidget", lambda: view._tree)
    assert view._gallery_owns_keys() is True     # browsing the tree: the gallery owns Delete


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


# --- Recents shelf: in-flight cards for queued/running generations ------------

def _png_bytes():
    buf = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeRerollJob:
    """Minimal stand-in for a GenerationJob the gallery treats as a live re-roll."""

    def __init__(self, prompt_id, workflow_name, params, state="running", frame=None,
                 progress=(0, 0), foreign_ahead=None, started_at=None):
        self.prompt_id = prompt_id
        self.state = state
        self.last_preview = frame
        self.last_progress = progress
        self.foreign_ahead = foreign_ahead  # another app's jobs ahead of it, if any
        self.started_at = started_at        # when ComfyUI began it; None while queued
        self.params = params
        self.workflow = WORKFLOW_REGISTRY[workflow_name]

    def reconcile(self):
        pass  # the poll pings this on every tracked re-roll; nothing to do here

    def refresh_backlog(self):
        pass  # the poll re-reads the queue position here; the fake's is fixed


def _open_recents(view):
    view._tree.setCurrentItem(_top_level(view._tree)["Recents"])


def _running_row(prompt_id, prompt="a cat", workflow="sdxl_t2i"):
    """A running generation row, as a re-roll or a Generate job inserts up front —
    no output yet, so it never enters the tree, only the in-flight cards."""
    return _row(prompt_id, workflow, {"positive_prompt": prompt}, f"{prompt_id}.png",
                status="running", output_files="[]")


def test_recents_shows_an_inflight_card_above_finished_items(qtbot):
    # An in-flight generation (a running DB row, as a re-roll inserts) shows as a
    # card on Recents; the finished item still lists below it, and the output-less
    # running row is never counted among the finished thumbnails.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_recents(view)

    assert "gen1" in view._inflight_cards
    assert view.visible_prompt_ids() == ["done"]          # cards aren't finished items


def test_recents_shows_a_live_reroll_as_an_inflight_card(qtbot):
    # A gallery re-roll: a running DB row (as _launch_reroll inserts) plus a live
    # job that supplies the frame. The card shows and carries the job's frame.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_top_level(view._tree)["Images"].child(0).child(0).child(0))
    view._reroll._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, state="running", frame=_png_bytes()
    )]
    _open_recents(view)

    assert "rr1" in view._inflight_cards
    assert not view._inflight_cards["rr1"]._image.pixmap().isNull()  # the job's live frame
    # Clicking the re-roll card opens the folder it runs in (its tile shows there).
    view._on_inflight_clicked("rr1")
    assert view._selected_folder_key() == folder_key


def _running_in_folder(prompt_id, prompt, steps, seed):
    """A running sdxl row sharing the settings folder of _image(prompt, steps, …) —
    same settings, fresh seed, no output — as a tab's Generate inserts up front."""
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"{prompt_id}.png", status="running", output_files="[]")


def test_open_folder_shows_a_running_generation_via_the_reroll_tile(qtbot, tmp_path):
    # A tab's Generate IS a re-roll, so a generation running in a folder is the
    # folder's RerollTile — it shows the live frame. The output-less running row is
    # not drawn as a separate card or a (broken) static thumbnail; the tile stands
    # for it. Its folder's other, finished items still list as static thumbnails.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)                 # a real re-roll running in the folder

    assert _reroll_tile(view) is not None            # the running generation IS the tile
    assert job.prompt_id not in view._inflight_cards  # not a separate in-flight card
    assert job.prompt_id not in view.visible_prompt_ids()  # nor an output-less static tile
    assert view.visible_prompt_ids() == ["orig"]     # only the finished item is a thumbnail


def test_open_folder_omits_a_running_row_from_the_static_grid(qtbot):
    # A running row (no output yet) gives its folder a tree node, but must not draw
    # as a broken, output-less static thumbnail — the folder's live tile stands for
    # it instead. Only the finished item lists as a thumbnail.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_in_folder("run1", "a cat", 50, 2))  # same folder as i1, still running
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert "run1" not in view._inflight_cards       # no separate in-flight card in the folder
    assert view.visible_prompt_ids() == ["i1"]      # run1 isn't a static thumbnail either


def test_open_folder_does_not_double_show_a_reroll_running_in_it(qtbot, tmp_path):
    # A gallery re-roll running in a folder is already led by its RerollTile; its
    # running row must not ALSO appear as a separate in-flight card in that folder.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)            # a real re-roll running in the folder

    view._rerender_current_leaf()               # redraw the open folder with its live tile

    assert _reroll_tile(view) is not None       # the RerollTile leads it...
    assert job.prompt_id not in view._inflight_cards  # ...and no duplicate in-flight card


def test_a_reroll_finishing_drops_its_inflight_card(qtbot):
    # The card tracks the database: once the re-roll's row leaves the running state
    # (it completed), the in-flight card drops even though a job object lingers.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_top_level(view._tree)["Images"].child(0).child(0).child(0))
    view._reroll._jobs[folder_key] = [
        _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"})]
    _open_recents(view)
    assert "rr1" in view._inflight_cards

    # The re-roll finishes: its row becomes a completed generation, its job drops.
    view._reroll_jobs.pop(folder_key)
    db.delete_generation("rr1")
    db.add(_row("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, "rr1.png"))
    view._poll()
    assert "rr1" not in view._inflight_cards


def test_inflight_card_frame_updates_in_place_without_a_rerender(qtbot):
    # A tracked re-roll's live frame is pushed into its existing card between
    # rebuilds, without re-rendering the whole shelf.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_top_level(view._tree)["Images"].child(0).child(0).child(0))
    job = _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, frame=None)
    view._reroll._jobs[folder_key] = [job]
    _open_recents(view)
    card = view._inflight_cards["rr1"]

    job.last_preview = _png_bytes()  # a live frame arrives on the tracked re-roll
    view._poll()
    assert view._inflight_cards["rr1"] is card       # same card object — no re-render
    assert not card._image.pixmap().isNull()          # now showing the frame


def test_recents_shelf_appears_for_a_running_generation(qtbot):
    # A generation is running (a running DB row, no output yet): the Recents shelf
    # appears and lists it as an in-flight card.
    view = GalleryView(FakeDB([_running_row("gen1")]))
    qtbot.addWidget(view)
    view.refresh()

    assert "Recents" in _top_level(view._tree)
    _open_recents(view)
    assert "gen1" in view._inflight_cards


def test_inflight_running_cards_sort_before_queued(qtbot):
    # Running generations sort before queued ones on the shelf, regardless of the
    # order their in-flight rows come back from the database.
    db = FakeDB([
        _row("waiting", "sdxl_t2i", {"positive_prompt": "w"}, "waiting.png",
             status="pending", output_files="[]"),
        _row("going", "sdxl_t2i", {"positive_prompt": "g"}, "going.png",
             status="running", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["going", "waiting"]


def test_inflight_items_follow_the_order_comfyui_will_run_them_in(qtbot):
    # A drag in the bottom strip moves jobs in ComfyUI without touching anything
    # the database records, so the queue is ordered by what ComfyUI reports —
    # here the reverse of the order the rows were made in.
    db = FakeDB([
        _row("first", "sdxl_t2i", {"positive_prompt": "a"}, "a.png",
             status="pending", output_files="[]"),
        _row("second", "sdxl_t2i", {"positive_prompt": "b"}, "b.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._reroll._queue_order = ["second", "first"]
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["second", "first"]


def test_a_job_comfyui_has_not_listed_yet_sorts_to_the_back(qtbot):
    # A prompt submitted between polls isn't in the order yet; it waits at the end
    # rather than jumping the queue on screen.
    db = FakeDB([
        _row("known", "sdxl_t2i", {"positive_prompt": "a"}, "a.png",
             status="pending", output_files="[]"),
        _row("brand-new", "sdxl_t2i", {"positive_prompt": "b"}, "b.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._reroll._queue_order = ["known"]
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["known", "brand-new"]


def test_the_queue_shows_the_active_job_then_empties_when_idle(qtbot):
    # The bottom strip surfaces in-flight work from anywhere in the view, then
    # empties once nothing runs — keeping its slot so the panes never shift.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)   # showEvent -> refresh -> feeds the strip

    assert view._queue.isVisible()
    assert view._queue.keys() == ["gen1"]
    assert view._queue.running_preview().key == "gen1"

    db.delete_generation("gen1")   # the job ends, its running row gone
    view._poll()
    assert view._queue.isVisible()                    # still holding its slot
    assert view._queue.keys() == []                   # but blank
    assert view._queue.running_preview().key is None


def test_the_queue_lists_every_waiting_job_not_just_the_running_one(qtbot):
    db = FakeDB([
        _running_row("running-one", prompt="a dog"),
        _row("waiting-one", "sdxl_t2i", {"positive_prompt": "w"}, "w.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._queue.keys() == ["running-one", "waiting-one"]


def test_dragging_a_queue_row_asks_comfyui_for_that_order(qtbot):
    from unittest.mock import patch

    from origenerator.gui.reroll_controller import RerollController

    db = FakeDB([
        _running_row("running-one", prompt="a dog"),
        _row("w1", "sdxl_t2i", {"positive_prompt": "w"}, "w.png",
             status="pending", output_files="[]"),
        _row("w2", "sdxl_t2i", {"positive_prompt": "x"}, "x.png",
             status="pending", output_files="[]"),
    ])
    with patch.object(RerollController, "reorder") as reorder:
        view = GalleryView(db)
        qtbot.addWidget(view)
        view._reroll._queue_order = ["running-one", "w1", "w2"]
        view.refresh()

        view._queue.move_row(2, 1)

    reorder.assert_called_once_with(["running-one", "w2", "w1"])


def test_clicking_a_queue_row_opens_that_jobs_folder(qtbot):
    # A queue row is a place in the gallery, not a settings form: clicking it
    # lands in the folder the job will appear in, with its live card selected.
    db = FakeDB([_running_row("gen1", prompt="a dog")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._select_reroll = MagicMock()

    view._inflight_items()[0].reveal()

    view._select_reroll.assert_called_once()


def test_the_strip_times_the_job_against_the_workflows_recent_runs(qtbot):
    # What the running half counts down from: the live job's own start time and
    # the median of what this workflow's finished runs actually took.
    db = FakeDB([
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _running_folder_key(view)
    began = time.time() - 90.5
    view._reroll._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "wan22_i2v", {}, state="running", progress=(10, 20), started_at=began
    )]

    item = view._inflight_items()[0]
    assert item.started_at == began
    assert item.typical_seconds == 724.0   # the median of the three timed runs

    view._update_queue()
    assert view._queue.running_preview()._caption.text() == "1:30 elapsed · ~10:33 left"


def test_the_strip_has_no_clock_for_a_job_still_queued(qtbot):
    # Nothing has begun, so there is no elapsed time to report — the wait behind
    # ComfyUI is the queue beside it to explain.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_row("waiting", "sdxl_t2i", {"positive_prompt": "w"}, "waiting.png",
                status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].started_at is None
    assert view._queue.running_preview()._caption.text() == ""


def _running_folder_key(view):
    """The settings-folder key the running wan22_i2v row above lands in."""
    return gallery.settings_folder_key(
        view._db.get_generation("rr1"),
        gallery.build_image_config_index(view._image_rows),
    )


def _finished_row_db(tmp_path):
    db = Database(tmp_path / "t.db")
    p = dict(_SDXL.default_params(), seed=1, positive_prompt="a cat")
    db.insert_generation(prompt_id="done", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="a cat", seed=1,
                         params_json=json.dumps(p), workflow_json="{}")
    db.update_generation("done", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_t2i_done.png"}]))
    return db


def test_generate_inflight_card_persists_across_navigation_and_polls(qtbot, tmp_path):
    # Real wiring, as the app builds it: a tab's Generate launches a re-roll, whose
    # in-flight card must stay on Recents across navigating to a folder and back, and
    # across poll ticks.
    client = ComfyUIClient()
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = lambda prompt_id: {}   # reconcile finds nothing done
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()
    panel = gv._info_tabs._add_subtab()
    panel._param_form.set_values({"seed": 2, "positive_prompt": "a dog"})
    panel._on_generate()                          # emits generate_requested -> a re-roll
    (pid,) = [job.prompt_id for job in gv._reroll_jobs.values()]

    gv._tree.setCurrentItem(gv._recents_item)
    assert pid in gv._inflight_cards

    folder = _top_level(gv._tree)["Images"].child(0).child(0).child(0)
    gv._tree.setCurrentItem(folder)              # navigate away
    gv._tree.setCurrentItem(gv._recents_item)    # and back
    assert pid in gv._inflight_cards, "card vanished after navigating away and back"

    gv._poll()
    assert pid in gv._inflight_cards, "card vanished after a poll"


def test_reroll_inflight_card_persists_across_navigation_and_polls(qtbot, tmp_path):
    client = ComfyUIClient()
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = lambda prompt_id: {}   # reconcile finds nothing done
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()

    folder_key = gallery.settings_folder_key(db.get_generation("done"))
    gv._start_reroll(folder_key)
    rr_pid = gv._reroll_jobs[folder_key].prompt_id

    gv._tree.setCurrentItem(gv._recents_item)
    assert rr_pid in gv._inflight_cards

    gv._tree.setCurrentItem(gv._item_by_key[folder_key])  # into the re-roll's folder
    gv._tree.setCurrentItem(gv._recents_item)             # and back
    assert rr_pid in gv._inflight_cards, "re-roll card vanished after navigation"

    gv._poll()
    assert rr_pid in gv._inflight_cards, "re-roll card vanished after a poll"


def test_i2v_reroll_inflight_card_follows_the_image_to_video_handoff(qtbot, tmp_path):
    # The user's real case: an i2v re-roll runs its image stage, then swaps to the
    # video stage under the same folder key (a new prompt id). The Recents card
    # must follow that handoff, on Recents and after navigating away and back.
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _reroll_tile(view).add_requested.emit()
    img_job = view._reroll_jobs[key]

    view._tree.setCurrentItem(view._recents_item)
    assert img_job.prompt_id in view._inflight_cards

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)  # image -> video
    vid_job = view._reroll_jobs[key]
    assert vid_job.prompt_id != img_job.prompt_id

    view._poll()
    assert vid_job.prompt_id in view._inflight_cards, "video-stage card missing after handoff"

    view._tree.setCurrentItem(view._item_by_key[key])   # away
    view._tree.setCurrentItem(view._recents_item)        # and back
    assert vid_job.prompt_id in view._inflight_cards, "video-stage card missing after navigation"


def test_recents_shows_a_running_reroll_row_with_no_live_job(qtbot, tmp_path):
    # A re-roll left running in the DB but not tracked by a live job — e.g. a
    # restart that didn't re-adopt it into _reroll_jobs — must still show as
    # in-flight. The card reflects the database, the source of truth for what is
    # in flight, not just the jobs this session happens to hold objects for.
    db = _finished_row_db(tmp_path)
    p = dict(_SDXL.default_params(), seed=5, positive_prompt="a wolf")
    db.insert_generation(prompt_id="rr_running", workflow_name="sdxl_t2i",
                         workflow_version="v", positive_prompt="a wolf", seed=5,
                         params_json=json.dumps(p), workflow_json="{}")
    db.update_generation("rr_running", status="running")
    gv = GalleryView(db, client=ComfyUIClient())
    qtbot.addWidget(gv)
    gv.refresh()
    gv._tree.setCurrentItem(gv._recents_item)

    assert "rr_running" in gv._inflight_cards


# --- combine: a video's recipe applied to a dropped image -------------------


def _combine_db(tmp_path):
    """A DB with one SDXL image to drop in and one i2v video whose recipe to reuse.

    The video's own input image is left at the workflow default (empty), so the
    combined result — keyed to the dropped image — lands in a fresh folder. Rows
    carry the workflows' current versions, as runs made by this app would (the
    settings key folds the version in).
    """
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", seed=1,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=1, positive_prompt="a dog")),
        workflow_json="{}",
    )
    db.update_generation("img", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_pick.png", "subfolder": ""}]))
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt="dance", seed=42,
        params_json=json.dumps(dict(_WAN_I2V.default_params(),
                                    seed=42, noise_seed=99, positive_prompt="dance")),
        workflow_json="{}",
    )
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    return db


def test_combine_submits_with_reused_seed_and_swapped_input_image(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._generate_combination("img", "vid")

    assert len(view._reroll_jobs) == 1
    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"  # the dropped image
    assert job.params["seed"] == 42       # the video's seed, reused (not randomized)
    assert job.params["noise_seed"] == 99
    view._client.submit_job.assert_called_once()


def test_open_combination_prefills_a_generate_tab_without_launching(qtbot, tmp_path):
    # "Open in generator" builds the same combination Generate would, but hands it to
    # an editable tab to tweak first — so no job runs and the form is prefilled.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._open_combination("img", "vid")

    assert view._reroll_jobs == {}                 # opened for editing, not launched
    view._client.submit_job.assert_not_called()
    config = view._info_tabs.current_config_panel().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"  # the dropped image
    assert config.params["seed"] == 42                               # the video's seed, carried in


def test_open_category_opens_the_resolved_recipe_without_launching(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", lambda *a, **k: None)

    view._open_category("img", "dancing")  # the combine DB's one clip is a "dance"

    assert view._reroll_jobs == {}                 # opened for editing, not launched
    view._client.submit_job.assert_not_called()
    config = view._info_tabs.current_config_panel().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"  # recipe on the dropped image


def test_open_category_hints_and_opens_nothing_when_the_act_has_no_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)  # its one video is a "dance" clip — no epsilon recipe exists
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", lambda *a, **k: None)
    tabs_before = view._info_tabs.count()
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))

    view._open_category("img", "epsilon")

    assert view._info_tabs.count() == tabs_before  # no recipe to open: no tab forked
    assert shown                                   # but tell the user why


def test_combine_open_buttons_are_wired_to_the_view(qtbot, tmp_path):
    # The panel's two "Open in generator" signals reach the view's open handlers, so
    # clicking Open with a dropped video (or a picked act) opens an editable tab.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.open_requested.emit("img", "vid")

    assert view._reroll_jobs == {}
    config = view._info_tabs.current_config_panel().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"


def _insert_completed_video(db, prompt_id, params, filename):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt=params.get("positive_prompt", ""), negative_prompt="",
        seed=params.get("seed"), params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": ""}]))


def test_combine_duplicate_declined_submits_nothing(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    combined = gallery.combined_params(db.get_generation("vid"), db.get_generation("img"), _WAN_I2V)
    _insert_completed_video(db, "dup", combined, "wan22_i2v_dup.mp4")  # this exact run exists
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: None)

    view._generate_combination("img", "vid")

    assert view._reroll_jobs == {}                    # declined: nothing submitted
    view._client.submit_job.assert_not_called()


def test_combine_duplicate_accepted_randomizes_the_seed(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    combined = gallery.combined_params(db.get_generation("vid"), db.get_generation("img"), _WAN_I2V)
    _insert_completed_video(db, "dup", combined, "wan22_i2v_dup.mp4")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: REROLL_VIDEO)

    view._generate_combination("img", "vid")

    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "wan22_i2v"  # the video runs on the same dropped frame
    assert job.params["seed"] != 42        # a fresh seed, not the duplicate's
    assert job.params["noise_seed"] != 99  # both dual-noise seeds re-rolled


def test_combine_duplicate_image_seed_redraws_the_dropped_image(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    combined = gallery.combined_params(db.get_generation("vid"), db.get_generation("img"), _WAN_I2V)
    _insert_completed_video(db, "dup", combined, "wan22_i2v_dup.mp4")  # this exact run exists
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: REROLL_IMAGE)

    view._generate_combination("img", "vid")

    # The dropped image is re-drawn first — the tracked job is its SDXL re-roll,
    # not the video — so a fresh frame precedes the (seed-kept) video.
    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "sdxl_t2i"
    assert json.loads(view._db.get_generation(job.prompt_id)["params_json"])["seed"] != 1


def test_generate_request_duplicate_declined_launches_nothing(qtbot, tmp_path, monkeypatch):
    # Regression: a tab's Generate with a pinned seed that reproduces a past run
    # must warn via the shared dialog, not silently re-launch identical copies.
    # Declining launches nothing — the same guard the re-roll and combine paths use.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: None)

    view._on_generate_requested("sdxl_t2i", {"seed": 42, "positive_prompt": "a cat"})

    assert view._reroll_jobs == {}              # declined: nothing launched
    view._client.submit_job.assert_not_called()


def test_generate_request_duplicate_accepted_randomizes_the_seed(qtbot, tmp_path, monkeypatch):
    # Accepting the dialog re-rolls the seed, so the config launched is a fresh
    # variation the folder can run without reproducing the duplicate.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: REROLL_VIDEO)

    view._on_generate_requested("sdxl_t2i", {"seed": 42, "positive_prompt": "a cat"})

    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "sdxl_t2i"
    assert job.params["seed"] != 42            # a fresh seed, not the duplicate's


def test_generate_request_without_a_duplicate_launches_straight_away(qtbot, tmp_path, monkeypatch):
    # A config that hasn't been generated before must launch with no dialog at all.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda *a, **k: pytest.fail("no dialog for a novel config"))

    view._on_generate_requested("sdxl_t2i", {"seed": 999, "positive_prompt": "a novel prompt"})

    job = next(iter(view._reroll_jobs.values()))
    assert job.params["seed"] == 999           # launched exactly as asked, unprompted


# --- cancel the front tab's run, and remember an accepted random-seed choice ---

def _front_panel(view):
    return view._info_tabs.current_config_panel()


def test_generate_shows_the_front_tabs_cancel_button(qtbot, tmp_path):
    # A Generate launched from a tab makes that tab offer to cancel it, mirroring
    # the folder's live re-roll tile — with Generate still pressable for another.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))

    panel._on_generate()

    assert view._reroll_jobs                          # a run is in flight
    assert panel._cancel_btn.isHidden() is False      # the tab offers to cancel it
    assert panel._generate_btn.isEnabled() is True


def _two_image_db(tmp_path, prompts=("the first one", "a completely different one")):
    """Two completed images. Same prompt for both puts them in one settings folder;
    different prompts put them in two."""
    db = Database(tmp_path / "t.db")
    for (pid, prompt), seed in zip(zip(("a", "b"), prompts), (7, 8)):
        params = dict(_SDXL.default_params(), seed=seed, positive_prompt=prompt)
        db.insert_generation(prompt_id=pid, workflow_name="sdxl_t2i",
                             workflow_version=_SDXL.version, positive_prompt=prompt,
                             seed=seed, params_json=json.dumps(params), workflow_json="{}")
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"sdxl_{pid}.png",
                                                       "subfolder": ""}]))
    return db


def _click_thumbnail(view, row, image_rows):
    """Load a browsed generation into the info pane, as clicking its tile does."""
    view._info_tabs.load_selection(row, image_rows)
    return _front_panel(view)


def test_a_second_image_from_the_same_folder_can_be_generated_too(qtbot, tmp_path):
    # The reported block: two pictures of one recipe. Generate the first, click the
    # second, and its Generate button was still mid-run — so a second could not be
    # started at all, and the button claimed the shown image was the one cooking.
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    first = _click_thumbnail(view, rows["a"], image_rows)
    first.use_random_seed()  # a fresh sample, not a duplicate of what's on screen
    first._on_generate()
    assert len(view._reroll.all_jobs) == 1

    panel = _click_thumbnail(view, rows["b"], image_rows)

    assert panel._generating is False
    assert panel._generate_btn.text() == "Generate"
    assert panel._generate_btn.isEnabled() is True

    panel.use_random_seed()
    panel._on_generate()

    assert len(view._reroll.all_jobs) == 2  # both queued, as ComfyUI will run them


def test_another_images_tab_can_still_generate_while_the_first_runs(qtbot, tmp_path):
    # The reported block: Generate one image, click a completely different one, and
    # its tab came up already in progress mode — so the second one could not be
    # launched at all, and the button claimed a run that was not its own.
    db = _two_image_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    view._info_tabs.load_selection(rows["a"], image_rows)
    first = _front_panel(view)
    first._param_form.set_values({"positive_prompt": "a re-roll of the first one"})
    first._on_generate()

    view._info_tabs.load_selection(rows["b"], image_rows)

    second = _front_panel(view)
    assert second is not first
    assert second._generating is False
    assert second._generate_btn.text() == "Generate"
    assert second._generate_btn.isEnabled() is True
    assert second._cancel_btn.isHidden() is True


def test_finishing_a_reroll_hides_the_front_tabs_cancel_button(qtbot, tmp_path):
    # When the run ends the tab drops Cancel and Generate returns.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    job = next(iter(view._reroll_jobs.values()))
    assert panel._cancel_btn.isHidden() is False

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._reroll_jobs == {}
    assert panel._cancel_btn.isHidden() is True
    assert panel._generate_btn.isEnabled() is True


def test_a_tabs_cancel_stops_the_run_its_bar_is_showing(qtbot, tmp_path):
    # Generate twice from one tab and the tab owns two runs. Its bar follows the
    # one being made, so its Cancel stops that one — the reported dead click was
    # the tab having quietly swapped its claim to the run queued behind, so a
    # press stopped something off screen and what was rendering carried on.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel.use_random_seed()
    panel._on_generate()
    panel._on_generate()
    being_made, queued_behind = [job.prompt_id for job in view._reroll.all_jobs]

    panel._cancel_btn.click()

    assert [job.prompt_id for job in view._reroll.all_jobs] == [queued_behind]
    assert view._db.get_generation(being_made) is None
    assert panel._generating is True  # the one behind is still its run to watch

    panel._cancel_btn.click()

    assert view._reroll.all_jobs == []
    assert panel._generating is False


def test_cancel_works_on_a_run_launched_from_a_clicked_image(qtbot, tmp_path):
    # The path the user actually takes: click a picture in the browser, Generate,
    # then Cancel. The tab is the one the click loaded, not one prefilled by hand.
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    panel = _click_thumbnail(view, rows["a"], list(rows.values()))
    panel.use_random_seed()
    panel._on_generate()
    prompt_id = view._reroll.all_jobs[0].prompt_id
    assert panel._cancel_btn.isHidden() is False

    panel = _front_panel(view)
    panel._cancel_btn.click()

    assert view._reroll.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_clicking_the_tabs_cancel_button_stops_its_run(qtbot, tmp_path):
    # The button itself, not the signal behind it: it is what the user presses.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    prompt_id = next(iter(view._reroll_jobs.values())).prompt_id

    panel._cancel_btn.click()

    assert view._reroll.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_canceling_from_the_front_tab_stops_the_reroll(qtbot, tmp_path):
    # The tab's Cancel stops the folder's re-roll exactly as the folder tile's does:
    # the job goes and its abandoned running row is dropped.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    prompt_id = next(iter(view._reroll_jobs.values())).prompt_id
    assert view._db.get_generation(prompt_id) is not None

    panel.cancel_requested.emit()

    assert view._reroll_jobs == {}
    assert view._db.get_generation(prompt_id) is None
    assert panel._cancel_btn.isHidden() is True


def test_duplicate_accepted_switches_the_front_tab_to_a_random_seed(qtbot, tmp_path, monkeypatch):
    # Accepting the "already generated" dialog doesn't just re-roll this one launch —
    # it switches the front tab's seed to Random, so the choice sticks on the tab.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))
    assert panel.current_config().seed_is_random is False   # pinned to the duplicate seed
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda parent, wf, *, can_reroll_image=False: REROLL_VIDEO)

    panel._on_generate()

    assert panel.current_config().seed_is_random is True


def test_random_seed_choice_survives_a_cancel_so_re_generate_does_not_re_ask(qtbot, tmp_path, monkeypatch):
    # The user's scenario: agree to a random seed, cancel that first attempt, then
    # Generate again — the choice stuck, so there's no second "already generated"
    # dialog and it launches a fresh variation straight away.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))
    prompts = []
    monkeypatch.setattr(gallery_view_module, "offer_reroll",
                        lambda *a, **k: prompts.append(1) or REROLL_VIDEO)

    panel._on_generate()                 # duplicate → asks once → accept
    assert prompts == [1]
    key = next(iter(view._reroll_jobs))
    view._cancel_reroll(key)             # cancel the first attempt
    assert view._reroll_jobs == {}

    panel._on_generate()                 # Generate again

    assert prompts == [1]                # not re-asked — the choice was preserved
    assert view._reroll_jobs             # a fresh variation launched


def test_combine_noop_for_an_unknown_video_workflow(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.insert_generation(prompt_id="vx", workflow_name="mystery", workflow_version="v",
                         positive_prompt="", seed=1, params_json=json.dumps({"seed": 1}),
                         workflow_json="{}")
    db.update_generation("vx", status="completed",
                         output_files=json.dumps([{"filename": "mystery_vx.mp4", "subfolder": ""}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._generate_combination("img", "vx")  # can't rebuild "mystery"

    assert view._reroll_jobs == {}
    view._client.submit_job.assert_not_called()


def test_combine_noop_when_the_image_has_no_output_file(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.update_generation("img", output_files=json.dumps([]))  # file pruned since it was dropped
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._generate_combination("img", "vid")

    assert view._reroll_jobs == {}


def test_category_uses_the_scene_matched_recipe(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    seen = {}

    def fake_smart(category, image_scene, candidates, **kw):
        seen.update(category=category, image_scene=image_scene,
                    scened=all("start_scene" in c for c in candidates),
                    ids=[c.get("prompt_id") for c in candidates])
        return "vid"  # the recipe whose starting scene fits this image

    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", fake_smart)

    view._generate_category("img", "alpha")

    assert seen["category"] == "alpha"
    assert seen["image_scene"] == "a dog"   # the dropped image's own prompt is the scene to match
    assert seen["scened"]                    # candidates enriched with each recipe's start scene
    assert seen["ids"] == ["vid"]            # only the rebuildable i2v video is a candidate (not the image)
    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"  # recipe run on the dropped image
    assert job.params["seed"] == 42                               # recipe's seed, reused via the combine path


def test_category_falls_back_to_most_used_when_scene_match_unavailable(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", lambda *a, **k: None)
    called = {}

    def fake_best(category, candidates):
        called["category"] = category
        return "vid"

    monkeypatch.setattr(gallery_view_module.recipe_match, "best_recipe", fake_best)

    view._generate_category("img", "alpha")

    assert called["category"] == "alpha"   # model unavailable → the act's most-used recipe
    job = next(iter(view._reroll_jobs.values()))
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_category_launches_a_real_recipe_via_the_fallback(qtbot, tmp_path, monkeypatch):
    # No live model in tests, so force the deterministic fallback: real best_recipe then
    # finds the combine DB's one "dance" clip for the "dancing" act and runs it.
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", lambda *a, **k: None)

    view._generate_category("img", "dancing")

    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_refresh_greys_out_the_acts_with_no_video_to_mine(qtbot, tmp_path):
    db = _combine_db(tmp_path)  # its one video is a "dance" clip
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)

    view.refresh()

    combo = view._combine._category
    enabled = {combo.itemText(i) for i in range(1, combo.count())
               if combo.model().item(i).isEnabled()}
    # "dancing" has a video to mine; "gamma" needs none — the example overlay
    # curates a recipe for it.
    assert enabled == {"dancing", "gamma"}


def test_category_prefers_the_overlays_curated_recipe_over_mining(qtbot, tmp_path, monkeypatch):
    # "gamma" is curated in the example overlay, so the launch takes its pinned
    # workflow+params — mining is never consulted, and the gallery needs no past
    # gamma video at all.
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated act must not mine")))

    view._generate_category("img", "gamma")

    job = next(iter(view._reroll_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"     # run on the dropped image
    assert job.params["lora_high"] == "example-act-high.safetensors"  # the curated spec's pin
    assert job.params["steps"] == 24


def test_open_category_prefers_the_curated_recipe_too(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated act must not mine")))
    opened = []
    monkeypatch.setattr(view._info_tabs, "open_config",
                        lambda name, params: opened.append((name, params)))

    view._open_category("img", "gamma")

    (name, params), = opened
    assert name == "wan22_i2v"
    assert params["input_image"] == "sdxl_pick.png [output]"
    assert params["lora_high"] == "example-act-high.safetensors"


def test_category_noop_and_hints_when_the_act_has_no_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)  # its one video is a "dance" clip — no epsilon recipe exists
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.recipe_match, "smart_recipe", lambda *a, **k: None)
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))

    view._generate_category("img", "epsilon")

    assert view._reroll_jobs == {}            # nothing to reuse: launch nothing
    view._client.submit_job.assert_not_called()
    assert shown                              # but tell the user why


# --- standalone enhance: the folder button, the selection action, the queue ---

_ENHANCE_HISTORY = {"outputs": {"12": {"images": [
    {"filename": "image_enhance_00001_.png", "subfolder": "image", "type": "output"}]}}}


def _enhanceable_db(tmp_path, count=2):
    """A DB whose one SDXL folder holds ``count`` finished, un-enhanced images
    (pre-enhance v002 rows: no enhance params, so nothing marks them)."""
    db = Database(tmp_path / "test.db")
    for i in range(count):
        pid = f"g{i}"
        db.insert_generation(
            prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
            positive_prompt="a cat", seed=i,
            params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": i}),
            workflow_json="{}",
        )
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"sdxl_t2i_g{i}.png",
                                                       "subfolder": "image",
                                                       "type": "output"}]))
    return db


def test_enhance_all_button_shows_only_on_a_folder_awaiting_enhancement(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._enhance_all_btn.isHidden()   # a plain image awaits

    # Once a standalone enhance of that image exists, nothing awaits: the
    # button retires from this folder.
    db.insert_generation(
        prompt_id="e0", workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": "image/sdxl_t2i_g0.png [output]"}),
        workflow_json="{}",
    )
    db.update_generation("e0", status="completed",
                         output_files=json.dumps([{"filename": "image_enhance_e0.png"}]))
    view.refresh()
    key = gallery.settings_folder_key(db.get_generation("g0"))
    view._tree.setCurrentItem(view._item_by_key[key])
    assert view._enhance_all_btn.isHidden()


def test_enhance_all_queues_every_member_image(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._enhance_all()

    # Both images share one source config, so their enhances share one folder —
    # and both go to ComfyUI, which works through them one at a time with the
    # bottom strip showing the line.
    jobs = view._reroll.all_jobs
    assert len(jobs) == 2
    assert {j.workflow.name for j in jobs} == {"image_enhance"}
    assert all(j.params["input_image"].startswith("image/sdxl_t2i_g") for j in jobs)
    assert {j.params["positive_prompt"] for j in jobs} == {"a cat"}  # the sources' own

    client.job_completed.emit(jobs[0].prompt_id, _ENHANCE_HISTORY)

    # The finished one FOLDED into its source — the transient job row is gone, and
    # the source image itself now wears the enhanced file (identity untouched) —
    # while the other keeps running.
    assert [j.prompt_id for j in view._reroll.all_jobs] == [jobs[1].prompt_id]
    assert view._db.get_generation(jobs[0].prompt_id) is None
    (upgraded,) = [r for r in view._db.list_generations() if r.get("original_files")]
    files = gallery.row_output_files(upgraded)
    assert files[0]["filename"] == "image_enhance_00001_.png"   # the new face
    assert files[1]["filename"] == f"sdxl_t2i_{upgraded['prompt_id']}.png"  # still listed
    assert gallery.is_enhanced_row(upgraded)


def test_enhance_items_queues_the_picked_images(qtbot, tmp_path):
    # The thumbnail context menu's action: enhance exactly the picked images,
    # through the same queue the folder button uses.
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view.enhance_items(["g0", "g1"])

    jobs = view._reroll.all_jobs
    assert len(jobs) == 2
    assert {j.workflow.name for j in jobs} == {"image_enhance"}


# --- the Enhance subpanel: the app's enhancement settings -------------------


def _set_enhance(view, **fields):
    """Put the panel where an edit would, the way the gallery stores it."""
    settings = gallery.EnhanceSettings(**fields)
    view.set_enhance_settings(settings.to_json())
    return settings


def test_the_hud_holds_the_left_of_the_bottom_row_and_enhance_the_right(qtbot, tmp_path):
    # Both panels share the bottom of the center pane: genau's console at its
    # fixed size on the left, the Enhance settings taking the width beside it.
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    row = view._stroke_panel.parentWidget().layout().itemAt(
        _row_index(view, view._stroke_panel)
    )
    assert row.itemAt(0).widget() is view._stroke_panel
    assert row.itemAt(1).widget() is view._enhance_panel
    assert row.stretch(0) == 0 and row.stretch(1) == 1


def test_a_hairline_closes_the_browser_pane_off_from_the_panels_below(qtbot, tmp_path):
    # Without it the Enhance knobs read as the bottom of whatever folder is on
    # screen, rather than as the app-wide settings they are.
    from PyQt6.QtWidgets import QFrame

    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    column = view._stroke_panel.parentWidget().layout()
    above = column.itemAt(_row_index(view, view._stroke_panel) - 1).widget()

    assert isinstance(above, QFrame)
    assert above.height() == 1
    # Painted, not a native sunken line: the app's flat background swallows those.
    assert "background-color" in above.styleSheet()


def _row_index(view, widget):
    """Which slot of the browser pane's column holds the row ``widget`` sits in."""
    column = widget.parentWidget().layout()
    for i in range(column.count()):
        item = column.itemAt(i)
        if item.layout() is not None and item.layout().indexOf(widget) >= 0:
            return i
    raise AssertionError("the stroke panel is not in a row of the browser pane")


def test_enhance_panel_stays_up_wherever_you_are(qtbot, tmp_path):
    # The settings are the app's, not the folder's: they follow you, so they are
    # as available on the shelves as inside a settings folder.
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._enhance_panel.isHidden()

    for item in (_top_level(view._tree)["Images"], view._recents_item,
                 view._starred_item, view._experiments_item, view._trash_item):
        view._tree.setCurrentItem(item)
        assert not view._enhance_panel.isHidden()


def test_the_panel_opens_on_the_settings_the_session_left(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    _set_enhance(view, auto=True, params={"enhance_scale": 3.0, "enhance_steps": 42,
                                          "enhance_denoise": 0.4})

    shown = view._enhance_panel.settings()
    assert shown.auto is True
    assert shown.params["enhance_scale"] == 3.0
    assert shown.params["enhance_steps"] == 42
    # And the view hands them back for the session to persist.
    assert gallery.EnhanceSettings.parse(view.enhance_settings()).auto is True


def test_editing_the_panel_takes_effect_at_once(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    # No Apply button: an edit lands straight away, so the settings an enhance
    # launched a moment later runs at are the ones on screen.
    view._enhance_panel._steps.setValue(33)

    assert gallery.EnhanceSettings.parse(
        view.enhance_settings()
    ).params["enhance_steps"] == 33


def test_enhance_all_runs_at_the_panels_settings(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_scale": 1.5, "enhance_steps": 44,
                               "enhance_denoise": 0.3})
    _select_first_leaf(view)

    view._enhance_all()

    (job,) = view._reroll_jobs.values()
    assert job.params["enhance_scale"] == 1.5
    assert job.params["enhance_steps"] == 44
    assert job.params["enhance_denoise"] == 0.3


def test_a_single_enhance_runs_at_the_same_settings_from_anywhere(qtbot, tmp_path):
    # An image picked off the Recents shelf enhances at exactly what the panel
    # says, the same as one picked inside its own folder — there is one setting.
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 51})

    view.enhance_items(["g0"])

    (job,) = view._reroll_jobs.values()
    assert job.params["enhance_steps"] == 51


def test_auto_enhance_claims_a_newly_generated_image(qtbot, tmp_path):
    # The box's standing instruction: with it ticked the app turns out finished
    # images without the user pressing Enhance All after every run.
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, auto=True, params={"enhance_steps": 27})

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")

    (job,) = view._reroll_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 27


def test_auto_enhance_leaves_a_new_image_alone_with_the_box_off(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")

    assert view._reroll_jobs == {}


def test_a_reroll_never_inherits_the_enhancement_of_what_it_varies(qtbot, tmp_path):
    # With the box unticked, a fresh seed must come out at base level — even
    # from a folder whose rows were made with the inline tail on. The stored
    # enhance flag is the recipe's history, not an instruction for the next run.
    db = _enhanceable_db(tmp_path, count=1)
    db.set_params_json("g0", json.dumps(dict(
        _SDXL.default_params(), positive_prompt="a cat", seed=0, enhance=True)))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._start_reroll(key)

    (job,) = view._reroll_jobs.values()
    assert job.params["enhance"] is False


def test_a_running_enhance_shows_in_the_strip_of_the_tab_showing_that_image(qtbot,
                                                                            tmp_path):
    # The level being made appears where the levels are, mirroring the run's
    # frames like every other in-flight card in the app.
    from origenerator.gui.enhance_versions import _PendingRow

    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    row = db.get_generation("g0")
    panel.show_saved_generation(row, view._image_rows)

    view.enhance_items(["g0"])

    assert panel._versions._host.findChildren(_PendingRow)
    (job,) = view._reroll_jobs.values()
    view._client.preview_image.emit(job.prompt_id, b"a frame")
    status, frame, settings = panel._pending_enhancement
    assert (status, frame) == ("running", b"a frame")
    # The tile names what is being made, the way a finished level names what
    # made it — read off the job, not the panel, which may have moved on since.
    assert settings.startswith("2x · 20 steps · 0.15 denoise")

    # An enhance of a DIFFERENT image lands in the same settings folder (both
    # images share a recipe), so it is this tab's own run it must keep showing.
    view.enhance_items(["g1"])
    assert panel._pending_enhancement == ("running", b"a frame", settings)


def test_each_tab_reads_its_own_image_out_of_a_batch_of_enhances(qtbot, tmp_path):
    # A batch of enhances goes to the controller whole, and its members share one
    # settings key, so the ones behind the leader must still be findable: a tab
    # showing an image waiting its turn says so, rather than borrowing the frame
    # of the one ComfyUI is actually rendering.
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    first = view._info_tabs.current_config_panel()
    first.show_saved_generation(db.get_generation("g0"), view._image_rows)
    second = view._info_tabs._add_subtab()
    second.show_saved_generation(db.get_generation("g1"), view._image_rows)

    view.enhance_items(["g0", "g1"])

    # Both went out — no backlog in here held the second one out of sight — and
    # they landed in the one folder, which is why a tab must not read it by key.
    leader, follower = view._reroll.all_jobs
    assert [j.workflow.name for j in (leader, follower)] == \
        ["image_enhance", "image_enhance"]
    assert len(view._reroll.jobs) == 1
    assert view.is_enhancing(db.get_generation("g1"))  # the one behind counts too

    view._client.preview_image.emit(leader.prompt_id, b"a frame")
    assert first._pending_enhancement == (
        "running", b"a frame", gallery.describe_enhance_params(leader.params))
    # The tab whose image is still waiting shows a queued tile, not that frame.
    assert second._pending_enhancement == (
        "queued", None, gallery.describe_enhance_params(follower.params))


def test_a_running_enhance_also_streams_onto_the_images_own_tile(qtbot, tmp_path):
    # The middle column is where the user is looking while a folder enhances
    # itself, so the run streams there too — under the scrim, which stays up
    # because what is on the tile is still not the finished file.
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._browser._thumb_widgets["g0"].is_enhancing()

    view.enhance_items(["g0"])

    # The launch redraws the folder, so the tile to watch is the one now up.
    tile = view._browser._thumb_widgets["g0"]
    assert tile.is_enhancing()
    assert not view._browser._thumb_widgets["g1"].is_enhancing()

    (job,) = view._reroll.all_jobs
    view._client.preview_image.emit(job.prompt_id, _png_bytes())
    tile = view._browser._thumb_widgets["g0"]
    assert tile._image_label.pixmap() is not None
    assert not tile._image_label.pixmap().isNull()

    # The run ending puts the tile's own picture back: those frames were a
    # partial render of a file that never landed.
    view._reroll._jobs.clear()
    view._reconcile_pending_enhancements()
    assert not tile.is_enhancing()


def test_an_enhance_still_queued_lends_its_tile_no_frame(qtbot, tmp_path):
    # A batch shares one folder and so one frame slot: the frame there belongs
    # to whichever of them ComfyUI is running, and lending it to the tiles queued
    # behind would show each of those a picture of a different image.
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view.enhance_items(["g0", "g1"])
    leader, follower = view._reroll.all_jobs
    view._client.preview_image.emit(leader.prompt_id, _png_bytes())

    tiles = view._browser._thumb_widgets
    assert tiles["g0"].is_enhancing() and tiles["g1"].is_enhancing()
    assert not tiles["g0"]._image_label.pixmap().isNull()
    assert follower.state == "queued"
    assert tiles["g1"]._resting_pixmap is None   # never given the leader's frame


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def _enhanced_in_place(db, pid="g0"):
    """Fold a level onto ``pid``: the enhanced file leads, the original stays."""
    db.update_generation(
        pid,
        output_files=json.dumps([
            {"filename": "image_enhance_00001_.png", "subfolder": "image"},
            {"filename": f"sdxl_t2i_{pid}.png", "subfolder": "image"},
        ]),
        original_files=json.dumps([{"filename": f"sdxl_t2i_{pid}.png",
                                    "subfolder": "image"}]),
        enhance_history=json.dumps([
            {"filename": "image_enhance_00001_.png",
             "params": {"enhance_scale": 2.0}},
        ]),
    )
    return db.get_generation(pid)


def test_the_version_lists_delete_bins_that_level_and_keeps_the_image(qtbot, tmp_path):
    # A level is a file, not a generation: the image keeps its row, its folder
    # and its other versions, and the delete lands on the same undo stack as
    # every other delete in the gallery.
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    row = _enhanced_in_place(db)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel.show_saved_generation(row, view._image_rows)

    panel._versions.delete_requested.emit([0])   # the enhancement, not the original

    updated = db.get_generation("g0")
    assert json.loads(updated["output_files"]) == [
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image"}
    ]
    assert not gallery.is_enhanced_row(updated)   # the badge goes with the level
    assert view._actions.can_undo()
    assert not view._undo_btn.isHidden()


def test_auto_enhance_stops_after_one_pass_rather_than_looping(qtbot, tmp_path):
    # The enhance folds back onto the row it came from, and that row arrives
    # here again as "finished". Already-enhanced, it must not queue another —
    # otherwise auto-enhance enhances forever.
    db = _enhanceable_db(tmp_path, count=1)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, auto=True)

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")
    (job,) = view._reroll_jobs.values()
    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert view._reroll_jobs == {}
    upgraded = db.get_generation("g0")
    assert gallery.is_enhanced_row(upgraded)
    # One enhancement, one level above the original.
    assert [lvl.label for lvl in gallery.enhance_levels(upgraded)] == \
        ["Enhance 1", "Original"]


def test_combine_new_folder_lands_on_recents_then_reveals_on_finish(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()

    view._generate_combination("img", "vid")

    assert view._showing_recents()  # brand-new folder: watch it cook on the shelf
    prompt_id = next(iter(view._reroll_jobs.values())).prompt_id

    client.job_completed.emit(prompt_id, _VID_REROLL_HISTORY)

    assert not view._showing_recents()  # the finished row gave its folder a node
    new_row = db.get_generation(prompt_id)
    image_rows = [r for r in db.list_generations() if gallery.media_type_of_row(r) == "image"]
    expected = gallery.settings_folder_key(new_row, gallery.build_image_config_index(image_rows))
    assert view._selected_folder_key() == expected


def test_combine_existing_folder_is_opened_with_the_live_tile(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    # A sibling already made from this image with the recipe's settings (other seed)
    # gives the target (image × settings) folder a node before we combine.
    sib = dict(_WAN_I2V.default_params(), seed=7, noise_seed=7, positive_prompt="dance",
               input_image="sdxl_pick.png [output]")
    _insert_completed_video(db, "vsib", sib, "wan22_i2v_vsib.mp4")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._generate_combination("img", "vid")

    expected = view._leaf_by_id["vsib"].data(0, _GROUP_ROLE).key
    assert not view._showing_recents()
    assert view._selected_folder_key() == expected
    assert view._selected_reroll_key == expected  # watching the live combine tile


def test_combine_slot_predicates_gate_by_kind(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view._combine_accepts_image("img") is True
    assert view._combine_accepts_image("vid") is False   # a video isn't a start frame
    assert view._combine_accepts_video("vid") is True
    assert view._combine_accepts_video("img") is False   # an image isn't an i2v recipe


def test_combine_panel_generate_button_launches_the_job(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine.image_slot.set_item("img")
    view._combine.video_slot.set_item("vid")

    view._combine._generate_btn.click()  # the panel's button, wired to the view

    assert len(view._reroll_jobs) == 1
    job = next(iter(view._reroll_jobs.values()))
    assert job.params["input_image"] == "sdxl_pick.png [output]"
    assert job.params["seed"] == 42


def test_combine_selection_reports_the_slotted_ids(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine.image_slot.set_item("img")
    view._combine.video_slot.set_item("vid")

    assert view.combine_selection() == ["img", "vid"]


def test_restore_combine_selection_refills_the_slots(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view.restore_combine_selection(["img", "vid"])

    assert view._combine.image_slot.current_id() == "img"
    assert view._combine.video_slot.current_id() == "vid"


def test_restore_combine_selection_skips_gone_or_mismatched_items(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    # image slot given a deleted id; video slot given an image (wrong kind)
    view.restore_combine_selection(["ghost", "img"])

    assert view._combine.image_slot.current_id() is None   # "ghost" no longer exists
    assert view._combine.video_slot.current_id() is None   # "img" isn't an i2v recipe


def test_restore_combine_selection_tolerates_a_missing_payload(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view.restore_combine_selection(None)          # nothing saved yet
    view.restore_combine_selection(["only-one"])  # malformed

    assert view.combine_selection() == [None, None]


def test_dragging_a_browser_thumbnail_lights_its_combine_slot(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tw = ThumbnailWidget("vid", None, "v")  # a video tile, wired like a real one
    qtbot.addWidget(tw)
    view._browser._wire_drag(tw)

    tw.drag_started.emit("vid")  # the drag begins — before reaching any slot
    assert view._combine.video_slot._label.property("dragActive") is True
    assert view._combine.image_slot._label.property("dragActive") is False

    tw.drag_ended.emit()
    assert view._combine.video_slot._label.property("dragActive") is False


def test_dragging_the_generate_preview_lights_its_combine_slot(qtbot, tmp_path):
    # The front generate tab's preview drags onto combine like a browser thumbnail.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()

    panel.preview_drag_started.emit("vid")  # the drag begins — before reaching a slot
    assert view._combine.video_slot._label.property("dragActive") is True
    assert view._combine.image_slot._label.property("dragActive") is False

    panel.preview_drag_ended.emit()
    assert view._combine.video_slot._label.property("dragActive") is False


# --- Drive OSR2: one global toggle, following whatever video is in front ----

class _FakeDriver:
    def __init__(self):
        self.started = []
        self.stopped = 0

    def start(self, player, actions):
        self.started.append((player, actions))

    def stop(self):
        self.stopped += 1


class _FakeFullscreen(QObject):
    """Stand-in for a FullscreenPreview: a settable drive target, a closed signal,
    a media_changed signal (paging), the curation signals its Up/Down keys emit,
    and a recorded playlist arming. ``live`` makes it one opened over a generation
    still in flight."""
    closed = pyqtSignal()
    media_changed = pyqtSignal()
    delete_requested = pyqtSignal(str)
    star_requested = pyqtSignal(str)

    def __init__(self, target, *, live=False):
        super().__init__()
        self._target = target
        self._live = live
        self.playlist = None       # the items set_playlist was armed with, if any
        self.playlist_index = None
        self.levels = None         # the per-image version playlists (Shift+arrows)
        self.enhance_hook = None   # (callback, ids) Down asks through
        self.enhanced = None       # a landed enhancement handed back to it
        self.stroke = None         # the shared stroke driver the gallery wires in
        self.closes = 0

    def set_levels(self, levels_by_path):
        self.levels = levels_by_path

    def set_enhance(self, on_enhance, ids_by_path):
        self.enhance_hook = (on_enhance, ids_by_path)

    def note_enhanced(self, prompt_id, path, media_type="image"):
        self.enhanced = (prompt_id, path, media_type)

    def osr2_drive_target(self):
        return self._target

    def is_live(self):
        return self._live

    def close(self):
        self.closes += 1
        self.closed.emit()

    def set_stroke(self, stroke):
        self.stroke = stroke

    def set_playlist(self, items, index):
        self.playlist = list(items)
        self.playlist_index = index


def _osr2_view(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient())
    qtbot.addWidget(view)
    driver = _FakeDriver()
    view._osr2_driver = driver
    return view, driver, view._info_tabs.current_config_panel()


def test_global_toggle_drives_the_front_video_and_untoggling_stops(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")

    view._osr2_btn.setChecked(True)  # the one global switch, on
    assert driver.started == [("player-A", "actions-A")]

    view._osr2_btn.setChecked(False)  # off
    assert driver.stopped == 1


def test_toggle_on_with_no_video_shown_drives_nothing(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: None  # front tab isn't showing a scripted video

    view._osr2_btn.setChecked(True)
    assert driver.started == []


def test_browsing_to_a_new_video_retargets_the_running_driver(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    panel.osr2_drive_target = lambda: ("B.mp4", "pB", "aB")
    panel.displayed_changed.emit()  # user browsed to another video in the same tab
    assert driver.started[-1] == ("pB", "aB")  # re-aimed at B


def test_switching_to_a_tab_without_a_scripted_video_stops_driving(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    assert driver.started

    view._info_tabs._add_subtab()  # a fresh, blank tab comes to the front
    assert driver.stopped >= 1


def test_osr2_enabled_state_round_trips_for_persistence(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)
    assert view.osr2_enabled() is False
    view.set_osr2_enabled(True)
    assert view.osr2_enabled() is True and view._osr2_btn.isChecked()


class _FakeAmbientAudio:
    """Stands in for the audio bed so a gallery test never opens a media backend."""

    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


def _audio_view(qtbot):
    bed = _FakeAmbientAudio()
    view = GalleryView(FakeDB([]), actions=FakeActions(), ambient_audio=bed)
    qtbot.addWidget(view)
    return view, bed


def test_the_audio_switch_starts_and_silences_the_bed(qtbot):
    view, bed = _audio_view(qtbot)
    assert (bed.starts, bed.stops) == (0, 0)  # off until asked

    view._audio_btn.setChecked(True)
    assert bed.starts == 1

    view._audio_btn.setChecked(False)
    assert bed.stops == 1


def test_audio_enabled_state_round_trips_for_persistence(qtbot):
    view, bed = _audio_view(qtbot)
    assert view.audio_enabled() is False

    view.set_audio_enabled(True)

    assert view.audio_enabled() is True and view._audio_btn.isChecked()
    assert bed.starts == 1  # restoring the switch actually starts it playing


def test_opening_fullscreen_arms_the_visible_folder_as_a_playlist(qtbot, monkeypatch):
    # Left/Right in fullscreen page through the folder: the view is armed with the
    # visible items' media, starting on the one already shown.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, output_dir: (f"{row['prompt_id']}.png", "image"),
    )
    view.refresh()
    _open_leaf(view)
    view._on_thumbnail_clicked("i2")  # i2 is the shown/selected item

    fs = _FakeFullscreen(None)
    view._on_fullscreen_opened(fs)

    order = view._browser.visible_prompt_ids()
    # Each entry carries its generation's id, so the view's Up and Down can name
    # what to trash and what to bookmark, and its stored thumbnail, which is the
    # only still a video has for the neighbor previews.
    assert fs.playlist == [(f"{pid}.png", "image", pid, None) for pid in order]
    assert fs.playlist_index == order.index("i2")  # opened on the shown item


def test_paging_the_fullscreen_re_aims_the_osr2(qtbot):
    # Paging to another clip re-aims the one device at the newly shown video.
    view, driver, _panel = _osr2_view(qtbot)
    view._osr2_btn.setChecked(True)
    fs = _FakeFullscreen(("A.mp4", "pA", "aA"))
    view._on_fullscreen_opened(fs)
    assert driver.started[-1] == ("pA", "aA")

    fs._target = ("B.mp4", "pB", "aB")
    fs.media_changed.emit()  # Left/Right landed on another clip
    assert driver.started[-1] == ("pB", "aB")


# --- the live auto-generate slideshow ----------------------------------------

class _SignalStroke(QObject):
    """Stands in for the app-global Osr2StrokeDriver: records the calls, flips
    on toggle, and reports the handovers — no device backend spins up."""

    active_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.active = False
        self.calls = []
        self.state = Stroke()

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        self.active_changed.emit(self.active)
        return self.active

    def stop(self):
        was_active = self.active
        self.active = False
        self.calls.append(("stop",))
        if was_active:
            self.active_changed.emit(False)

    def adjust_speed(self, delta):
        self.calls.append(("speed", delta))

    def adjust_amplitude(self, delta):
        self.calls.append(("amplitude", delta))

    def adjust_center(self, delta):
        self.calls.append(("center", delta))

    def toggle_cruise(self):
        self.calls.append("cruise")

    def quarter_offset(self):
        self.calls.append("nudge")

    def cycle_shape(self):
        self.calls.append(("shape",))

    def status_text(self):
        return "OSR2 stub"


def _auto_montage_view(qtbot, monkeypatch, rows):
    """A gallery on a settings leaf whose loop reports active, with the slideshow
    built on stubbed player and stroke so no media or device backend spins up."""
    view = GalleryView(FakeDB(rows), actions=FakeActions(), client=ComfyUIClient(),
                       osr2_stroke=_SignalStroke())
    qtbot.addWidget(view)
    monkeypatch.setattr(
        view, "_make_auto_montage",
        lambda: AutoGenerateView(player=MagicMock(), stroke=view._osr2_stroke),
    )
    view.refresh()
    _open_leaf(view)
    key = view._selected_folder_key()
    monkeypatch.setattr(view._auto, "is_active", lambda k: k == key)
    return view, key


def test_auto_montage_key_follows_the_open_folders_loop(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    key = view._selected_folder_key()
    assert view._auto_montage_key() is None           # not looping → no montage
    monkeypatch.setattr(view._auto, "is_active", lambda k: k == key)
    assert view._auto_montage_key() == key
    assert view._plain_fullscreen_allowed() is False  # montage pre-empts fullscreen


def test_the_preview_double_click_is_gated_while_looping(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    panel = view._info_tabs.current_config_panel()
    # The gate is wired to the gallery, and vetoes the plain fullscreen while looping.
    assert panel._preview._fullscreen_gate == view._plain_fullscreen_allowed
    assert panel._preview._fullscreen_gate() is False


def test_double_clicking_the_preview_while_looping_opens_the_montage(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    assert view._auto_montage is None
    view._on_preview_double_clicked()
    assert isinstance(view._auto_montage, AutoGenerateView)
    view._auto_montage.close()


def test_the_montage_seeds_the_rotation_and_opens_on_the_live_slot(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view, key = _auto_montage_view(qtbot, monkeypatch, rows)
    _resolve_by_id(monkeypatch)
    view._open_auto_montage(key)
    montage = view._auto_montage
    assert montage._playlist.count == 3  # both finished items, plus the live slot
    assert montage._playlist.on_live()
    montage.close()


def test_a_live_frame_feeds_the_open_montage(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    montage = view._auto_montage
    seen = []
    monkeypatch.setattr(montage, "show_live_frame", lambda d: seen.append(d))
    view._on_reroll_preview(key, b"frame-bytes")
    assert seen == [b"frame-bytes"]
    montage.close()


def test_a_finished_item_joins_the_montage_rotation(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    montage = view._auto_montage
    before = montage._playlist.count
    _resolve_by_id(monkeypatch)
    view._feed_montage_finished(key)
    assert montage._playlist.count == before + 1
    montage.close()


def test_closing_the_montage_forgets_it(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    view._auto_montage.close()
    assert view._auto_montage is None


def test_up_in_the_montage_skips_the_current_and_keeps_looping(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    cancelled, relaunched = [], []
    monkeypatch.setattr(view._reroll, "cancel", lambda k: cancelled.append(k))
    monkeypatch.setattr(view._auto, "note_finished", lambda k: relaunched.append(k))
    view._skip_auto_current(key)
    assert cancelled == [key]   # the in-flight job is abandoned...
    assert relaunched == [key]  # ...but the loop launches the next


def test_marking_weird_in_the_montage_trashes_the_item(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    view._auto_montage.weird_requested.emit("i1")
    assert [r["prompt_id"] for r in view._actions.deleted[0]] == ["i1"]
    view._auto_montage.close()


def test_the_stroke_taking_the_device_stops_the_funscript_drive(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    stopped = []
    monkeypatch.setattr(view._osr2_driver, "stop", lambda: stopped.append(True))
    view._osr2_driving = ("clip.mp4", "player")  # as if a funscript drive were on
    view._osr2_stroke.toggle()                   # the stroke takes the device
    assert stopped == [True]                     # the funscript drive stood down
    assert view._osr2_drive_source() is None     # and nothing may retake the device


def test_closing_the_montage_leaves_the_stroke_running(qtbot, monkeypatch):
    # The stroke is app-global: dismissing a view must not park the device.
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    view._osr2_stroke.toggle()
    view._auto_montage.close()
    assert view._osr2_stroke.active


def test_escape_panic_stops_a_running_stroke(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._osr2_stroke.toggle()
    assert view._handle_escape() is True
    assert not view._osr2_stroke.active


def test_the_stroke_keys_work_in_the_main_window_too(qtbot, monkeypatch):
    # "Always available": the same keys the fullscreen views answer are routed
    # app-wide by the gallery's event filter, under its own-keys guards.
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    monkeypatch.setattr(view, "_gallery_owns_keys", lambda: True)
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_L, _NO_MOD)
    assert view.eventFilter(view, event) is True
    assert ("speed", 5) in view._osr2_stroke.calls


def test_the_loop_ending_drops_the_montage_live_slot(qtbot, monkeypatch):
    view, key = _auto_montage_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._open_auto_montage(key)
    view._on_auto_stopped(key)
    assert view._auto_montage._playlist.live is False
    view._auto_montage.close()


def test_watching_a_video_fullscreen_drives_nothing_with_the_toggle_off(qtbot):
    # The toggle governs the fullscreen view as much as the tab preview: double-
    # clicking a clip to watch it doesn't take the device on its own.
    view, driver, _panel = _osr2_view(qtbot)
    assert not view._osr2_btn.isChecked()

    view._on_fullscreen_opened(_FakeFullscreen(("F.mp4", "pF", "aF")))

    assert driver.started == []


def test_turning_the_toggle_on_over_an_open_fullscreen_drives_its_video(qtbot):
    # …and turning it on while one is up drives what's on screen, without closing it.
    view, driver, _panel = _osr2_view(qtbot)
    view._on_fullscreen_opened(_FakeFullscreen(("F.mp4", "pF", "aF")))

    view._osr2_btn.setChecked(True)

    assert driver.started[-1] == ("pF", "aF")


def test_untoggling_while_a_fullscreen_video_drives_stops_the_device(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    view._osr2_btn.setChecked(True)
    view._on_fullscreen_opened(_FakeFullscreen(("F.mp4", "pF", "aF")))
    assert driver.started

    view._osr2_btn.setChecked(False)

    assert driver.stopped >= 1


def test_closing_the_fullscreen_stops_driving_with_no_tab_video_behind_it(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    view._osr2_btn.setChecked(True)
    fs = _FakeFullscreen(("F.mp4", "pF", "aF"))
    view._on_fullscreen_opened(fs)
    assert driver.started

    fs.closed.emit()

    assert driver.stopped >= 1


def test_the_fullscreen_video_overrides_the_toggle_target_then_hands_back(qtbot):
    # With the toggle already driving the front-tab video, opening a fullscreen clip
    # re-aims the one device at the fullscreen player; closing hands it back.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    fs = _FakeFullscreen(("F.mp4", "pF", "aF"))
    view._on_fullscreen_opened(fs)
    assert driver.started[-1] == ("pF", "aF")

    fs.closed.emit()
    assert driver.started[-1] == ("pA", "aA")  # back to the toggle's video


def test_a_fullscreen_image_leaves_the_toggle_driving(qtbot):
    # A fullscreen with no scripted video (an image) has no target, so the toggle's
    # front-tab video keeps driving uninterrupted — no restart, no stop.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    assert driver.started == [("pA", "aA")]

    view._on_fullscreen_opened(_FakeFullscreen(None))

    assert driver.started == [("pA", "aA")] and driver.stopped == 0


def _press_escape(view):
    return view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )


def test_esc_stops_osr2_driving(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)  # driving the device
    assert driver.started

    handled = _press_escape(view)

    assert handled is True
    assert view.osr2_enabled() is False and not view._osr2_btn.isChecked()
    assert driver.stopped >= 1


def test_esc_stops_osr2_even_without_gallery_key_focus(qtbot):
    # The driven video usually lives in the focused info-pane tab, where the gallery
    # doesn't own Delete/Undo — Esc must still reach the device from there.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    view._gallery_owns_keys = lambda: False  # focus is inside a config tab

    handled = _press_escape(view)

    assert handled is True and driver.stopped >= 1


def test_esc_passes_through_when_nothing_is_running(qtbot):
    # OSR2 off and no auto loop: Esc isn't swallowed, so it can still close a
    # dropdown or cancel an edit elsewhere.
    view, _driver, _panel = _osr2_view(qtbot)

    assert _press_escape(view) is False


def test_osr2_button_tooltip_hints_esc_stops_it(qtbot):
    # The only place the Esc shortcut is discoverable, so keep the hint on the toggle.
    view, _driver, _panel = _osr2_view(qtbot)
    assert "Esc" in view._osr2_btn.toolTip()


def test_esc_defers_to_a_fullscreen_window(qtbot, monkeypatch):
    # A fullscreen preview or the slideshow is a separate top-level window that uses
    # Esc to close. The gallery's app-wide filter sees Esc first, so it must defer
    # when another window is active rather than swallow Esc to stop the OSR2.
    from PyQt6.QtWidgets import QApplication, QWidget
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view._osr2_btn.setChecked(True)
    fullscreen = QWidget()
    qtbot.addWidget(fullscreen)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: fullscreen))

    handled = _press_escape(view)

    assert handled is False and driver.stopped == 0  # Esc left for the other window


def test_another_active_window_owns_the_keys(qtbot, monkeypatch):
    # The shared guard behind both Esc and Delete: when a separate top-level window
    # (a fullscreen preview / the slideshow) is active, the gallery yields its keys.
    from PyQt6.QtWidgets import QApplication, QWidget
    view, _driver, _panel = _osr2_view(qtbot)
    assert view._other_window_owns_keys() is False  # only the gallery is up

    other = QWidget()
    qtbot.addWidget(other)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True


# --- folders the user composes: multi-select, group, drop, rename, remove -----

def _two_leaf_view(qtbot, extra=()):
    """A view whose Images tree holds two settings folders ("a cat", "a dog")
    under one "(no LoRA)" parent, plus whatever ``extra`` rows are handed in.

    Returns the two folders by *key*: every rebuild throws its tree items away,
    and these tests all rebuild."""
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1), *extra]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _top_level(view._tree)["Images"].child(0).child(0).child(0)
    return view, _key(lora.child(0)), _key(lora.child(1))


def _pick(view, *keys):
    """Pick several folder rows the way a click then Ctrl-clicks does."""
    items = [view._item_by_key[key] for key in keys]
    view._tree.setCurrentItem(items[0])
    for item in items[1:]:
        item.setSelected(True)


def test_picking_several_folders_shows_them_together_as_one_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert view.visible_folder_keys() == [cat, dog]  # both, as tiles
    assert "2 folders" in view._title.display_text()
    assert not view._group_btn.isHidden()  # offering to save the grouping


def test_the_slideshow_of_a_multi_selection_plays_every_picked_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert {r["prompt_id"] for r in view._slideshow_rows()} == {"i1", "i2"}


def test_dropping_back_to_one_folder_returns_to_that_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)

    view._tree.setCurrentItem(view._item_by_key[cat])  # a plain click on one row

    assert view._selection_group is None
    assert view.visible_prompt_ids() == ["i1"]  # its own thumbnails, not tiles
    assert view._group_btn.isHidden()


def test_delete_is_dark_while_several_folders_are_picked(qtbot):
    # Otherwise Delete would wipe whichever single row happened to be current.
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert view._current_deletable_folder() is None
    assert not view._delete_btn.isEnabled()


def test_grouping_the_picked_folders_makes_a_named_folder_and_opens_it(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Favorites", True)))

    view._group_selection()

    (record,) = view._db.list_custom_folders()
    assert record["name"] == "Favorites"
    assert record["members"] == [cat, dog]
    # ...and the view has landed on it, showing what it gathered.
    assert _top_level(view._tree)["Favorites"] is view._tree.currentItem()
    assert view.visible_folder_keys() == [cat, dog]


def test_declining_the_name_prompt_makes_no_folder(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("", False)))

    view._group_selection()

    assert view._db.list_custom_folders() == []


def _make_folder(view, name, keys):
    folder_id = view._db.create_custom_folder(name)
    view._db.add_custom_folder_members(
        folder_id, [(key, "settings", None) for key in keys]
    )
    view.refresh()
    return folder_id


def test_a_custom_folder_gets_its_own_row_and_shows_what_it_holds(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])

    row = _top_level(view._tree)["Favorites"]
    view._tree.setCurrentItem(row)

    assert row.childCount() == 0  # flat like a shelf: its members live elsewhere
    assert view.visible_folder_keys() == [cat]
    assert {r["prompt_id"] for r in view._slideshow_rows()} == {"i1"}


def test_a_custom_folder_is_not_where_the_gallery_lands_by_default(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])

    assert view._tree_view.default_item() is _top_level(view._tree)["Images"]


def test_dropping_a_folder_onto_a_custom_folder_adds_it(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat])

    view._on_folders_dropped(gallery.custom_folder_key(folder_id), [dog])

    (record,) = view._db.list_custom_folders()
    assert record["members"] == [cat, dog]
    assert view.visible_folder_keys() == [cat, dog]  # landed on it


def test_dropping_a_folder_onto_starred_stars_it(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)

    view._on_folders_dropped(gallery_view_module._STARRED_KEY, [cat])

    assert view._db.folder_meta_map()[cat]["starred"] is True


def test_dropped_folders_carry_the_identity_the_reconcile_needs(qtbot):
    # Without (level, ref) a membership cannot be re-derived when a key formula
    # moves, and the grouping silently loses the folder.
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [])

    view._on_folders_dropped(gallery.custom_folder_key(folder_id), [cat])

    (member,) = view._db.custom_folder_members_full()
    assert (member["level"], member["ref_prompt_id"]) == ("settings", "i1")


def test_removing_a_gathered_folder_leaves_its_items_alone(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat, dog])
    group = view._group_for_key(gallery.custom_folder_key(folder_id))

    view._remove_from_custom_folder(group, dog)

    (record,) = view._db.list_custom_folders()
    assert record["members"] == [cat]
    assert view._db.get_generation("i2") is not None  # the folder itself survives


def test_removing_a_custom_folder_keeps_every_generation_it_gathered(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat, dog])
    view._confirm = lambda text: True

    view._remove_custom_folder(view._group_for_key(gallery.custom_folder_key(folder_id)))

    assert view._db.list_custom_folders() == []
    assert {r["prompt_id"] for r in view._db.list_generations()} == {"i1", "i2"}
    assert "Favorites" not in _top_level(view._tree)


def test_a_custom_folder_cannot_be_deleted_by_the_folder_delete_path(qtbot):
    # Delete trashes a folder's generations; a custom folder holds none of its own,
    # so that path must never accept one.
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Favorites"])
    view._confirm = lambda text: True

    view._delete_selection()

    assert view._db.get_generation("i1") is not None
    assert view._db.list_custom_folders()[0]["id"] == folder_id


def test_renaming_a_custom_folder_renames_the_folder_itself(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat])

    view._apply_rename(gallery.custom_folder_key(folder_id), "Best of")

    assert view._db.list_custom_folders()[0]["name"] == "Best of"
    assert "Best of" in _top_level(view._tree)


def test_a_custom_folder_survives_a_rebuild_and_follows_its_members(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Favorites"])

    view._db.add(_image("i3", "a cat", 50, 9))  # a new seed joins the gathered folder
    view.refresh()

    assert view._tree.currentItem() is _top_level(view._tree)["Favorites"]
    assert {r["prompt_id"] for r in view._slideshow_rows()} == {"i1", "i3"}


def test_a_rebuild_keeps_a_live_multi_selection(qtbot):
    # A poll or a finished generation rebuilds the tree; collapsing the selection
    # would throw away the folder the user is in the middle of composing.
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)

    view._db.add(_image("i3", "a fish", 50, 3))
    view.refresh()

    assert view._selection_group is not None
    assert len(view.visible_folder_keys()) == 2


# --- somebody else's queue on the shared ComfyUI ----------------------------

class _QueueClient(ComfyUIClient):
    """A client whose ComfyUI queue holds ``foreign`` jobs of another app's."""

    def __init__(self, foreign=ForeignQueue(running=[], pending=[]), fail=None):
        super().__init__()
        self._foreign = foreign
        self._fail = fail
        self.cleared = 0

    def foreign_queue(self):
        return self._foreign

    def clear_foreign_queue(self):
        if self._fail is not None:
            raise self._fail
        self.cleared += 1
        return self._foreign.total


def _queue_view(qtbot, client):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=client)
    qtbot.addWidget(view)
    view.refresh()
    return view


def test_the_strip_names_another_apps_queue_before_generate_is_pressed(qtbot):
    # The reported bug: the queue read as free, then Generate reported six jobs
    # ahead of it out of nowhere. Polling the server's own queue is what lets the
    # strip say so while nothing of ours is in flight at all.
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)

    view._poll()

    assert view._queue.running_preview()._caption.text() == (
        "3 jobs from another app are queued on ComfyUI")
    assert not view._queue._clear.isHidden()


def test_a_queue_of_our_own_leaves_the_strip_as_it_was(qtbot):
    view = _queue_view(qtbot, _QueueClient())

    view._poll()

    assert view._queue.running_preview()._caption.text() == ""
    assert view._queue._clear.isHidden()


def test_an_unreadable_queue_claims_nothing_rather_than_a_stale_count(qtbot):
    # ComfyUI restarting mid-poll must not leave a count on screen offering to
    # clear a queue the app can no longer see.
    class Wedged(_QueueClient):
        def foreign_queue(self):
            raise OSError("connection refused")

    view = _queue_view(qtbot, _QueueClient(ForeignQueue(running=[], pending=["a"])))
    view._poll()
    assert not view._queue._clear.isHidden()

    view._client = Wedged()
    view._poll()

    assert view._foreign_queue.total == 0
    assert view._queue._clear.isHidden()


def test_clearing_wipes_the_other_apps_jobs_off_comfyui(qtbot):
    # What the user asked for: a way out from under a queue he didn't fill,
    # instead of waiting out a batch no window here can account for.
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True

    view._queue._clear.click()

    assert client.cleared == 1


def test_clearing_can_be_declined_at_the_prompt(qtbot):
    client = _QueueClient(ForeignQueue(running=[], pending=["a"]))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: False  # user says no

    view._queue._clear.click()

    assert client.cleared == 0


def test_the_prompt_says_how_many_jobs_go(qtbot):
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    asked = []
    view._confirm_clear_queue = lambda total: asked.append(total) or False

    view._queue._clear.click()

    assert asked == [3]


def test_a_failed_clear_is_surfaced_not_swallowed(qtbot, monkeypatch):
    client = _QueueClient(ForeignQueue(running=[], pending=["a"]),
                          fail=OSError("ComfyUI is not responding"))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True
    warned = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMessageBox.warning",
        lambda *a, **k: warned.append(a),
    )

    view._queue._clear.click()  # must not raise

    assert warned


def test_a_cleared_queue_blanks_the_bar_without_waiting_for_a_poll(qtbot):
    client = _QueueClient(ForeignQueue(running=[], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True

    client._foreign = ForeignQueue(running=[], pending=[])  # the clear empties it
    view._queue._clear.click()

    assert view._queue.running_preview()._caption.text() == ""
    assert view._queue._clear.isHidden()


def test_a_tile_wears_an_enhancing_scrim_while_its_run_is_in_flight(qtbot, tmp_path):
    # A folder generating with the Auto switch on has to read honestly: the base
    # render is out and on screen, and something better is on the way.
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tile = view._browser._thumb_widgets["g0"]
    assert not tile.is_enhancing()

    view.enhance_items(["g0"])
    view._rerender_current_leaf()

    assert view._browser._thumb_widgets["g0"].is_enhancing()


def test_the_add_card_enhances_the_image_the_tab_is_showing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel.show_saved_generation(db.get_generation("g0"), view._image_rows)
    _set_enhance(view, params={"enhance_steps": 29})

    panel._versions.enhance_requested.emit()

    (job,) = view._reroll_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 29


def test_holding_a_slide_enhances_it_unless_it_already_has_that_version(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view._enhance_from_slideshow("g0") is True
    (job,) = view._reroll_jobs.values()
    assert job.workflow.name == "image_enhance"

    # Asked again while that one is still cooking: nothing new is started.
    assert view._enhance_from_slideshow("g0") is False


def test_a_landed_enhancement_upgrades_that_item_in_every_open_show(
        qtbot, tmp_path, monkeypatch):
    # The whole point of enhancing from a show: what plays becomes the better
    # version. It lands minutes after the ask, so no surface is still on the
    # item that asked — each takes the upgrade wherever that item sits.
    paths = {"g0": "g0.png", "g1": "g1.png"}
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: (paths[row["prompt_id"]], "image"))
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._start_slideshow()
    qtbot.addWidget(view._slideshow)
    montage = AutoGenerateView(player=MagicMock())
    qtbot.addWidget(montage)
    montage.add_finished("g0.png", "image", "g0")
    view._auto_montage = montage
    view._fullscreen_preview = _FakeFullscreen(None)

    # The fold has happened: the row now leads with the enhanced file and wears
    # its thumbnail. That upgraded row is what reaches the shows.
    paths["g0"] = "g0_enhanced.png"
    db.update_generation("g0", thumbnail_path="g0_enhanced_thumb.png")
    view._feed_slideshow_enhanced(db.get_generation("g0"))

    upgraded = ("g0_enhanced.png", "image", "g0", "g0_enhanced_thumb.png")
    assert upgraded in view._slideshow._playlist._items
    assert upgraded in montage._playlist._items
    assert view._fullscreen_preview.enhanced == ("g0", "g0_enhanced.png", "image")
    view._slideshow.close()


def test_a_slideshow_hold_on_a_video_asks_for_nothing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps(
        [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    assert view._enhance_from_slideshow("g0") is False


def test_the_fullscreen_view_is_armed_with_each_images_versions(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps([
        {"filename": "image_enhance_1.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
    ]), original_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    fs = _FakeFullscreen(None)

    view._on_fullscreen_opened(fs)

    (levels,) = fs.levels.values()
    assert [p.name for p, _kind, _label in levels] == \
        ["image_enhance_1.png", "sdxl_t2i_g0.png"]
    # Each carries its label, so the corner can say which version is on screen.
    assert [label for _p, _kind, label in levels] == ["Enhance 1", "Original"]
    # And Down is armed with the ids, so it can name what it is looking at.
    hook, ids = fs.enhance_hook
    assert hook == view._enhance_from_slideshow
    assert set(ids.values()) == {"g0"}


def test_watching_a_generation_fullscreen_still_pages_its_folder(qtbot, monkeypatch):
    # A view opened over something still being made has no place among the
    # folder's files — but the folder is still what it was opened from, so its
    # arrows page it rather than doing nothing at all.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, output_dir: (f"{row['prompt_id']}.png", "image"),
    )
    view.refresh()
    _open_leaf(view)
    fs = _FakeFullscreen(None, live=True)

    view._on_fullscreen_opened(fs)

    assert [entry[2] for entry in fs.playlist] == view._browser.visible_prompt_ids()
    assert fs.playlist_index == 0


def test_a_slideshow_opens_on_a_folder_whose_only_item_is_still_cooking(qtbot):
    # It used to refuse: the one row had no file, so the playlist came back empty
    # and the button did nothing. A folder being filled is still worth watching.
    db = FakeDB([_running_row("cooking", prompt="a cat")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    rows = view._db.list_generations()

    items = view._slideshow_items(rows)

    assert [item[2] for item in items] == ["cooking"]
    assert items[0][0] is None  # no file behind it yet


def test_a_finished_generation_with_no_file_stays_out_of_a_slideshow(qtbot):
    db = FakeDB([_row("gone", "sdxl_t2i", {"positive_prompt": "a cat"}, "gone.png",
                      output_files="[]")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._slideshow_items(view._db.list_generations()) == []


def test_a_folder_of_one_video_is_armed_like_any_other(qtbot, monkeypatch):
    # Most video folders here hold a single clip, so skipping the arming for a
    # lone item is what made "fullscreen on a video" look like a different mode.
    rows = [_i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, output_dir: (f"{row['prompt_id']}.mp4", "video"),
    )
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])
    view._on_thumbnail_clicked("v1")

    fs = _FakeFullscreen(None)
    view._on_fullscreen_opened(fs)

    assert fs.playlist == [("v1.mp4", "video", "v1", None)]
    assert fs.playlist_index == 0


def test_a_slideshow_arms_spoken_fixes_and_its_close_disarms_them(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: ("g0.png", "image"))
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._start_slideshow()
    qtbot.addWidget(view._slideshow)
    assert view._voice.commands_on

    view._slideshow.close()
    assert view._slideshow is None
    assert not view._voice.commands_on


def test_a_fullscreen_view_arms_spoken_fixes_for_its_lifetime(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    fs = _FakeFullscreen(None)

    view._on_fullscreen_opened(fs)
    assert view._voice.commands_on

    fs.closed.emit()
    assert not view._voice.commands_on


def test_a_spoken_fix_launches_the_targeted_pass_on_the_slide(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: ("g0.png", "image"))
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["teeth_yolov8n.pt"])
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._start_slideshow()
    qtbot.addWidget(view._slideshow)

    assert view._voice.speak_command("Fix her teeth.") is not None

    (job,) = view._reroll_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_detail_fix"] is True
    assert job.params["enhance_face_detector"] == "teeth_yolov8n.pt"
    assert job.params["enhance_hand_detector"] == ""
    # The show answers where the speaker is looking, then reads Enhancing….
    assert "fixing teeth" in view._slideshow._note.text()


def test_a_spoken_fix_with_nothing_to_find_it_answers_on_the_slideshow(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: ("g0.png", "image"))
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: [])
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._start_slideshow()
    qtbot.addWidget(view._slideshow)

    view._voice.speak_command("fix teeth")

    assert view._reroll_jobs == {}
    assert "no teeth detector" in view._slideshow._note.text()
