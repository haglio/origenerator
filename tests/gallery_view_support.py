from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image
from PIL import Image as _Image
from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QImage,
    QKeyEvent,
)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QMessageBox,
    QSplitter,
)

from origenerator import (
    gallery,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    OUTPUT_PLACES,
    THUMB_DIR,
)
from origenerator.db import Database
from origenerator.gallery.collection import (
    TRASH_KEY,
)
from origenerator.gallery.sides import LANDSCAPE
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_state import GenerationSource
from origenerator.gui.folder_tree import _action_rects
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.request_worker import RevisionWorker
from origenerator.gui.reroll_tile import RerollTile
from origenerator.motion_engine import Motion
from origenerator.orientation import base_of, oriented_key
from origenerator.output_places import OutputPlaces
from origenerator.prompt_edit import request_applier
from origenerator.slideshow_buttons import MODE_BUTTONS
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY
from tests import gestures
from tests.comfyui_folders import SUITE_FOLDERS
from tests.slideshow_hud_support import funestra_of

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


_WAN_I2V = WORKFLOW_REGISTRY["wan22_i2v"]


_REROLL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


_VID_REROLL_HISTORY = {"outputs": {"19": {"images": [
    {"filename": "wan_new.mp4", "subfolder": "video", "type": "output"}]}}}


_NO_MOD = Qt.KeyboardModifier.NoModifier


_CTRL = Qt.KeyboardModifier.ControlModifier


def _will_move_on(slideshow) -> bool:
    return not slideshow.shown._paused and not slideshow._keeps()


class FakeActions:
    """Records what the view asks of its action controller.

    Including where the generations are: the view draws its previews out of the
    folders its actions were built with rather than reaching the config module
    for them, so a double pointed at somewhere of its own is how a test says
    which library the view is looking at.
    """

    def __init__(self, places=OUTPUT_PLACES, thumb_dir=THUMB_DIR):
        self.places = places
        self.thumb_dir = thumb_dir
        self.deleted = []   # each entry is one delete batch (list of rows)
        self.rejected = []  # experiment rows handed to reject_experiment
        self.restored = []  # each entry is one restore_deleted call's ids
        self.purged = []    # each entry is one purge_deleted call's ids
        self.undo_count = 0
        self.redo_count = 0
        self._label = None
        self._redo_label = None

    def delete_rows(self, rows):
        self.deleted.append(list(rows))
        self._label = f"Delete {len(rows)} items"

    def restore_deleted(self, prompt_ids):
        ids = list(prompt_ids)
        self.restored.append(ids)
        return ids[0] if ids else None

    def purge_deleted(self, prompt_ids):
        self.purged.append(list(prompt_ids))

    def delete_enhance_levels(self, row, filenames):
        return True

    def reject_experiment(self, row):
        self.rejected.append(row)
        self._label = "Reject experiment"

    def undo(self):
        self.undo_count += 1
        self._label, self._redo_label = None, self._label

    def can_undo(self):
        return self._label is not None

    def undo_label(self):
        return self._label

    def redo(self):
        self.redo_count += 1
        self._label, self._redo_label = self._redo_label, None

    def can_redo(self):
        return self._redo_label is not None

    def redo_label(self):
        return self._redo_label


class FakeDB:
    """In-memory stand-in for Database covering the methods the view calls."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._by_id = {r["prompt_id"]: r for r in rows}
        self._meta = {}
        self._custom = {}       # folder id -> {"name", "folders": {key: (level, ref)}, "items"}
        self._next_custom = 1
        self._deletions = {}    # prompt_id -> the held-deletion record, newest last
        self._requests = {}     # prompt_id -> its spoken-request record, newest last
        self._seed_uses = []    # newest first
        self._combine_video_uses = []  # newest first
        self._item_numbers = {}

    def list_generations(self):
        return list(self._rows)

    def rows_made_by(self, workflow_name):
        return [row for row in self._rows if row.get("workflow_name") == workflow_name]

    def library_version(self):
        return object()  # tests change the rows directly, so every look is fresh

    def record_seed_use(self, **use):
        self._seed_uses.insert(0, use)

    def list_seed_uses(self):
        return list(self._seed_uses)

    def record_combine_video_use(self, intent, video_prompt_id, generation_prompt_id=None):
        self._combine_video_uses.insert(0, {
            "intent": intent, "video_prompt_id": video_prompt_id,
            "generation_prompt_id": generation_prompt_id,
            "created_at": f"9999-{len(self._combine_video_uses):08d}"})

    def list_combine_video_uses(self):
        return list(self._combine_video_uses)

    def custom_combinations(self):
        return [{"prompt_id": row["prompt_id"], "source_video": row["source_video"],
                 "created_at": row.get("created_at") or ""}
                for row in self._rows
                if row.get("source_video") and not row.get("act")]

    def list_item_numbers(self):
        return dict(self._item_numbers)

    def record_item_numbers(self, numbers):
        self._item_numbers.update(numbers)

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

    def upsert_folder_meta(self, key, *, custom_name, favorite, level, ref_prompt_id):
        self._meta[key] = {"custom_name": custom_name, "starred": bool(favorite)}

    def set_folder_favorite(self, key, favorite):
        self._meta.setdefault(key, {"custom_name": None, "starred": False})
        self._meta[key]["starred"] = bool(favorite)

    def set_generation_favorite(self, prompt_id, favorite):
        row = self._by_id.get(prompt_id)
        if row is not None:
            row["starred"] = 1 if favorite else 0

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

    # --- the recovery bin (deletions held for the Trash collection) --------

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

    # --- spoken requests, and the folder-wide one typed on a tab -----------

    def record_request(self, *, prompt_id, source_prompt_id, heard, **fields):
        self._requests[prompt_id] = {
            "prompt_id": prompt_id, "source_prompt_id": source_prompt_id,
            "heard": heard, "term": None, "polarity": None, "action": None,
            "old_positive": "", "old_negative": "",
            "new_positive": "", "new_negative": "", **fields,
        }

    def list_requests(self):
        return list(reversed(self._requests.values()))  # newest first

    def get_request(self, prompt_id):
        return self._requests.get(prompt_id)

    def requests_about(self, source_prompt_id):
        return [record for record in self.list_requests()
                if record["source_prompt_id"] == source_prompt_id]

    # --- custom folders (the groupings the user composes) ------------------

    def create_custom_folder(self, name, folder_id=None, side=None):
        if folder_id is None:
            folder_id = self._next_custom
        self._next_custom = max(self._next_custom, folder_id) + 1
        self._custom[folder_id] = {"name": name, "side": side, "folders": {}, "items": {}}
        return folder_id

    def delete_custom_folder(self, folder_id):
        self._custom.pop(folder_id, None)

    def add_folders_to_custom_folder(self, folder_id, folders):
        for folder_key, level, ref in folders:
            self._custom[folder_id]["folders"][folder_key] = (level, ref)

    def remove_folder_from_custom_folder(self, folder_id, folder_key):
        self._custom[folder_id]["folders"].pop(folder_key, None)

    def add_items_to_custom_folder(self, folder_id, prompt_ids):
        self._custom[folder_id]["items"].update(dict.fromkeys(prompt_ids))

    def remove_items_from_custom_folder(self, folder_id, prompt_ids):
        for prompt_id in prompt_ids:
            self._custom[folder_id]["items"].pop(prompt_id, None)

    def list_custom_folders(self):
        return [{"id": fid, "name": f["name"], "side": f["side"], "folders": list(f["folders"]),
                 "items": list(f["items"])}
                for fid, f in sorted(self._custom.items())]

    def folders_in_custom_folders(self):
        return [{"folder_id": fid, "folder_key": key, "level": level, "ref_prompt_id": ref}
                for fid, f in self._custom.items()
                for key, (level, ref) in f["folders"].items()]

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


def _enhanced_image(prompt_id, prompt, steps, seed):
    """An image whose settings ran the enhance tail — one wearing the yellow plus."""
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed,
                 "enhance": True},
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


def _side(tree, side=LANDSCAPE):
    """One section of the TOC pane — the Portrait tree, the Landscape one, or
    the one list of both shapes the radio over them collapses to (see
    :mod:`origenerator.gallery.sides`)."""
    return tree._trees[side]


def _top_level(tree, side=LANDSCAPE):
    """One half's rows: its collections, its custom folders, its All.

    Landscape by default because that is where these fixtures land — a row with
    no thumbnail, no file on disk and no size in its params has no shape to
    read, and an unmeasurable item files under the roomier region everywhere in
    this app. A test about the split itself names the side it means.
    """
    half = _side(tree, side)
    return {half.topLevelItem(i).text(0): half.topLevelItem(i)
            for i in range(half.topLevelItemCount())}


def _alls(tree, side=LANDSCAPE):
    """What one half's All row holds: its collections, then Images and Videos."""
    all_row = _top_level(tree, side)["All"]
    return {all_row.child(i).text(0): all_row.child(i) for i in range(all_row.childCount())}


def _selected_folder(view):
    """Which folder the tree has open, with the side stripped — what a test that
    is not about the split itself means by "the selected folder"."""
    return base_of(view.selected_folder_key())


def _collection(view, key, side=LANDSCAPE):
    """One side's copy of a collection row. Landscape by default, like _top_level."""
    return view._tree_item_for(oriented_key(key, side))


def _side_rows(view, side):
    """The prompt ids one side of the tree holds, from its All row down."""
    return [row["prompt_id"]
            for row in view._slideshows.rows_at(oriented_key(gallery.ALL_KEY, side))]


def _key(item):
    return item.data(0, _GROUP_ROLE).key


def _subs(item):
    """A row's own folders, without the collections a folder of folders leads with."""
    children = (item.child(i) for i in range(item.childCount()))
    return [child for child in children if child.data(0, _GROUP_ROLE) is not None]


def _at(item, *path):
    for index in path:
        item = _subs(item)[index]
    return item


def _workflow_rows(tree, media=None, side=LANDSCAPE):
    """The workflow rows, which hang under Images and Videos, by label — one
    kind's alone ("image"/"video") when ``media`` says so."""
    all_row = _top_level(tree, side).get("All")
    if all_row is None:
        return {}
    kinds = [kind for kind in _subs(all_row) if media in (None, _key(kind))]
    return {row.text(0): row for kind in kinds for row in _subs(kind)}


def _image_workflow(tree, side=LANDSCAPE):
    """The sole image workflow's row — where a one-workflow gallery starts."""
    (row,) = _workflow_rows(tree, "image", side).values()
    return row


def _video_workflow(tree):
    """The sole video workflow's row."""
    (row,) = _workflow_rows(tree, "video").values()
    return row


def _on_screen(qtbot, view, width, height):
    qtbot.addWidget(view)
    view.resize(width, height)
    with qtbot.waitActive(view):
        view.show()
        view.activateWindow()
    view.refresh()


def _children_by_prompt(item):
    """A folder's settings children keyed by the prompt their generations ran,
    since the name itself is a code (see gallery.keys)."""
    return {child.data(0, _GROUP_ROLE).rows[0]["positive_prompt"]: child
            for child in _subs(item)}


def _preview_of(view):
    """The preview of the tab in front — reached through the panel that owns it,
    since the gallery no longer keeps a handle on another class's private widget
    (C/design/004)."""
    panel = view._info_tabs.current_config_panel()
    return panel._preview if panel is not None else None


def _frame_shown(preview, frame: bytes) -> bool:
    """Whether *preview* is following a run, showing *frame* of it."""
    shown = preview._pixmap
    as_argb = QImage.Format.Format_ARGB32
    return (preview._live and shown is not None
            and shown.toImage().convertToFormat(as_argb)
            == QImage.fromData(frame).convertToFormat(as_argb))


def _search_for(view, text):
    """Type a query and let its debounce fire.

    The field waits out a beat of quiet before searching (and a longer one before
    asking the model to widen), so a test that only sets the text has typed but
    not yet searched. Nothing under the minimum length searches at all, so that
    case is left to the timer that never fires — as it is in the app.
    """
    view._search.field.setText(text)
    if view._search._timer.isActive():
        view._search._timer.stop()
        view._search._run_pending()


def _of_both_kinds(qtbot, actions=None):
    rows = [_image("i1", "a cat", 50, 1),
            _row("v1", "wan22_i2v", {"positive_prompt": "a cat", "seed": 5},
                 "wan22_i2v_00001_.mp4")]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    return view


def _collection_row(folder, label):
    (row,) = [folder.child(i) for i in range(folder.childCount())
              if folder.child(i).data(0, _GROUP_ROLE) is None and folder.child(i).text(0) == label]
    return row


def _press_ctrl_f(view, monkeypatch):
    """Ctrl+F through the app-wide event filter, with the other-window guard
    stood down: a widget another test left over can still read as the active
    window here, and that guard (shared with Esc) has its own tests."""
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    return view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, _CTRL))


def _tab_with_prompts(view, key="sdxl_t2i"):
    """Answer the front tab's workflow picker, so it has prompt fields to find in.

    The resting tab lays out no form until a workflow is chosen — and a find over
    no fields is the tree-find fallback, which has its own test below."""
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData(key))
    return panel


def _click_beside_the_mark_of(qtbot, view, key, *, which):
    """Click the star (``which=0``) or the trash (``which=1``) a folder's row
    wears in the indentation left of its mark, through the window."""
    _on_screen(qtbot, view, 1200, 800)
    row = view._tree_item_for(key)
    tree = row.treeWidget()
    tree.scrollToItem(row)
    gestures.click(tree.viewport(), _action_rects(tree.visualItemRect(row))[which].center())


def _experiment_row(prompt_id, verdict=None, prompt="a cat", steps=50, seed=9, **extra):
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"sdxl_t2i_{prompt_id}.png",
                source="experiment", experiment_verdict=verdict, **extra)


def _bin_db(rows=(), held=(), inherited=()):
    """A gallery whose bin already holds ``held`` — ``(prompt_id, row)`` pairs,
    oldest first — the way a previous session's deletes would have left it.

    ``inherited`` takes the same shape but files each as a delete that moved real
    files into the trash, the way a delete made by another instance would have.
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


def _trash_collection_view(qtbot, actions, held=(("d1", "a cat"),)):
    """The Trash collection open over the deletions given as ``(prompt_id, prompt)``,
    with the first of them picked."""
    view = GalleryView(
        _bin_db(held=[(pid, _image(pid, prompt, 50, n))
                      for n, (pid, prompt) in enumerate(held, start=1)]),
        actions=actions,
    )
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    view._browser.apply_selection(held[0][0], _NO_MOD)
    return view


def _click_tile(view, prompt_id):
    QTest.mouseClick(view._browser._thumb_widgets[prompt_id], Qt.MouseButton.LeftButton, _NO_MOD)


def _right_click(view, prompt_id):
    """Right-click a tile the way Qt does — through the widget's own custom-context
    signal — so a menu the pane never connected registers as no menu at all."""
    view._browser._thumb_widgets[prompt_id].customContextMenuRequested.emit(QPoint(0, 0))


def _answer_menu(monkeypatch, label):
    """Answer the next menu with the entry reading ``label``.

    By its words rather than its place in the list: a menu grows and shrinks with
    what the row it was raised over can do — "Go to folder" is absent inside the
    item's own folder, Enhance is absent for a video, "Delete folder…" is absent
    over a workflow — so an index picks a different entry depending on where it
    is raised.

    Sub-menus are searched after the top level, so the folders listed under "Add
    to folder" are answerable by their own names.
    """
    def find(menu):
        for act in menu.actions():
            if act.text() == label:
                return act
        for act in menu.actions():
            if act.menu() is not None and (found := find(act.menu())) is not None:
                return found
        return None

    def pick(menu, *_args):
        act = find(menu)
        if act is None:  # loudly, not as a menu the user dismissed
            raise AssertionError(f"no menu entry reading {label!r}")
        act.trigger()  # as Qt does for the entry clicked, before exec returns it
        return act

    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", pick)


def _answer_confirmation(monkeypatch, button):
    """Click ``button`` on the next confirmation dialog.

    Most tests of a destructive action replace `_confirm` outright, which is the
    right way to keep a modal out of a test that is about something else. These
    few answer the real dialog instead, because the step from the button the user
    clicks to the decision the gallery takes is otherwise pinned nowhere: with it
    inverted, a "No" at the delete prompt deletes anyway and all 657 tests passed.
    """
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: button))


def _menu_labels(monkeypatch, labels):
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda menu, *a: labels.extend(act.text() for act in menu.actions()),
    )


def _name_of(row, number):
    return f"{gallery.folder_id(gallery.settings_folder_key(row))} {number:03d}"


def _scroll_bar(view):
    return view._scroll.verticalScrollBar()


def _drawn(view):
    """The items whose tiles the pane has drawn so far, in the order drawn."""
    return list(view._browser._thumb_widgets)


def _write_looping_webp(path, size=(64, 48)):
    """A tiny two-frame looping WebP standing in for a video's moving preview."""
    frames = [_Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def _open_leaf(view):
    """Select the first settings-group leaf so its thumbnails are showing."""
    workflow = _image_workflow(view._tree)
    leaf = _at(workflow, 0, 0, 0)  # workflow -> model -> "(no LoRA)" -> settings
    view._tree.setCurrentItem(leaf)
    return leaf


def _click_off(view):
    """Put the pick down, as a click on the pane's background does — which since
    a folder opens on its first item is how Favorite, Enhance and Delete come to be
    aimed at the whole folder again (see
    test_clicking_the_pane_background_drops_the_selection)."""
    view._browser.clear_thumbnail_selection()


def _reroll_client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-X")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    # Every send asks after an earlier run of its id first; answered here,
    # never by a server on the machine.
    client.fetch_history = MagicMock(return_value={})
    client.forget_history = MagicMock()
    return client


def _png_bytes() -> bytes:
    """An 8x8 PNG. Tests compare frames to this helper's own output, so the
    only thing that matters is that every call returns the same bytes."""
    buf = BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _reroll_tile(view):
    tiles = view._scroll.widget().findChildren(RerollTile)
    return tiles[0] if tiles else None


def _generating_tile(view):
    tiles = view._scroll.widget().findChildren(GeneratingTile)
    return tiles[0] if tiles else None


def _tile_kinds_in_order(view):
    layout = view._scroll.widget().layout()
    return [type(layout.itemAt(index).widget()) for index in range(layout.count())]


def _select_first_leaf(view, side=LANDSCAPE):
    # workflow -> model -> "(no LoRA)" -> settings (the thumbnail leaf)
    leaf = _at(_image_workflow(view._tree, side), 0, 0, 0)
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


def _resolve_by_id(monkeypatch):
    """Resolve every row's preview to a per-row image path (the autouse default
    stubs resolution to None, which would leave the slideshow nothing to seed)."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: (f"{row['prompt_id']}.png", "image"))


MODE_VERBS = frozenset(action for action, _label, _lit in MODE_BUTTONS)


def _in_view(view, prompt_id) -> bool:
    tile = view._browser._thumb_widgets[prompt_id]
    viewport = view._scroll.viewport()
    return viewport.rect().contains(QRect(tile.mapTo(viewport, QPoint(0, 0)), tile.size()))


def _running_reroll(view, side=LANDSCAPE):
    """Start a re-roll and return (key, job) for the freshly launched job."""
    key = _select_first_leaf(view, side)
    _reroll_tile(view).add_requested.emit()
    return key, view._live_jobs[key]


def _single_i2v_db(tmp_path, input_image):
    db = Database(tmp_path / "hp.db")
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image=input_image)),
        workflow_json="{}",
    )
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    return db


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
    actions = GalleryActions(db, OutputPlaces.in_one_folder(output_dir), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):
        view.show()
    view.refresh()
    return view, db, file_path


class _FakeRerollJob:
    """Minimal stand-in for a GenerationJob the gallery treats as a live re-roll."""

    def __init__(self, prompt_id, workflow_name, params, state="running", frame=None,
                 progress=(0, 0), foreign_ahead=None, started_at=None,
                 pass_progress=None, stage=""):
        self.prompt_id = prompt_id
        self.origin = prompt_id  # a run of its own, not a chained stage
        self.state = state
        self.last_preview = frame
        self.last_progress = progress
        self.last_pass_progress = pass_progress  # the pass in hand, for the bar's band
        self.last_stage = stage                  # and what the caption calls it
        self.foreign_ahead = foreign_ahead  # another app's jobs ahead of it, if any
        self.started_at = started_at        # when ComfyUI began it; None while queued
        self.params = params
        self.workflow = WORKFLOW_REGISTRY[workflow_name]
        self.source = GenerationSource.GENERATED
        self.thumb_dir = THUMB_DIR
        self.shielded = False

    def reconcile_with(self, history):
        pass  # the poll applies /history on every tracked re-roll; nothing here

    def take_backlog(self, foreign_ahead):
        pass  # the poll applies the queue position here; the fake's is fixed

    def take_executing(self, executing):
        pass  # and ComfyUI's word on whether it is making it; the fake's state is fixed

    def cancel(self):
        self.state = "canceled"


def _open_recents(view):
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])


def _running_row(prompt_id, prompt="a cat", workflow="sdxl_t2i"):
    """A running generation row, as a re-roll or a Generate job inserts up front —
    no output yet, so it never enters the tree, only the in-flight cards."""
    return _row(prompt_id, workflow, {"positive_prompt": prompt}, f"{prompt_id}.png",
                status="running", output_files="[]")


def _menu_offering(monkeypatch, module, pick=None):
    """Stand in for a raised menu: record its entries, and choose one by prefix.

    Returns the list each raised menu's labels land in — empty if no menu was
    ever raised at all, which is how "a right-click that offers nothing" is told
    apart from one that offers something.
    """
    raised = []

    def fake_exec(menu, *_args):
        labels = [action.text() for action in menu.actions()]
        raised.append(labels)
        if pick is None:
            return None
        return next(a for a in menu.actions() if a.text().startswith(pick))

    monkeypatch.setattr(f"origenerator.gui.{module}.QMenu.exec", fake_exec)
    return raised


def _combine_db(tmp_path, *, enhanced=True):
    """A DB with one SDXL image to drop in and one i2v video whose settings to reuse.

    The video's own input image is left at the workflow default (empty), so the
    combined result — keyed to the dropped image — lands in a fresh folder. Rows
    carry the workflows' current versions, as runs made by this app would (the
    settings key folds the version in).

    The image is enhanced already, its base render kept under it, so a combine
    makes its video straight away; ``enhanced=False`` is an image a video has to
    wait on while it is enhanced.
    """
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", seed=1,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=1, positive_prompt="a dog")),
        workflow_json="{}",
    )
    base = [{"filename": "sdxl_pick_base.png", "subfolder": "", "role": "original"}]
    db.update_generation("img", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_pick.png", "subfolder": ""}] + (base if enhanced else [])))
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt="dance", seed=42,
        params_json=json.dumps(dict(_WAN_I2V.default_params(),
                                    seed=42, noise_seed=99, positive_prompt="dance")),
        workflow_json="{}",
    )
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    db.set_settings_source("vid", category="dancing")
    return db


def _front_panel(view):
    return view._info_tabs.current_config_panel()


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


def _set_enhance(view, **fields):
    """Put the panel where an edit would, the way the gallery stores it."""
    settings = gallery.EnhanceSettings(**fields)
    view.set_enhance_settings(settings.to_json())
    return settings


def _pane_holding(widget):
    while not isinstance(widget.parentWidget(), QSplitter):
        widget = widget.parentWidget()
    return widget


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


def _double_click_slideshow(view, qtbot, *, media=("shown.png", "image"), target=None):
    """The double-click path end to end: the gallery opens the folder under the
    pane as a real slideshow.

    ``media`` is what the pane was showing — ``None`` for a generation still
    running under it — and the generation it names is the tile these tests
    clicked, which is what the tab shows.
    ``target`` stands in for the OSR2 drive target the clip on screen would
    offer, since these tests carry no real scripted video.
    """
    shown = view.selected_prompt_id() if media is not None else None
    slideshow = view._slideshows.open_on_preview(media, shown)
    qtbot.addWidget(slideshow.shown)
    if target is not None:
        _aim_slideshow(view, slideshow, target)
    return slideshow


def _aim_slideshow(view, slideshow, target):
    """Say what the clip on screen offers the device, and reconcile as a step
    onto it would."""
    slideshow.osr2_drive_target = lambda: target
    view.reconcile_osr2()


class _HeldRadio:
    def __init__(self):
        self.ticked = None
        self.closed = False

    def tick(self, *, image, level, paused):
        self.ticked = (image, level, paused)

    def close(self):
        self.closed = True


class _FakeRadio:
    """Stands in for Origenerator Radio so a gallery test never opens an engine."""

    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.frozen = False
        self.held: list[_HeldRadio] = []

    def held_by_a_slideshow(self):
        self.held.append(_HeldRadio())
        return self.held[-1]

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def set_frozen(self, frozen):
        self.frozen = frozen


class _SignalMotion(QObject):
    """Stands in for the app-global Osr2MotionDriver: records the calls, flips
    on toggle, and reports the handovers — no device backend spins up."""

    active_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.active = False
        self.calls = []
        self.state = Motion()
        self.held = None
        self.frozen = False
        self.parked_by_the_pause = False

    def set_frozen(self, frozen):
        self.frozen = frozen

    def hold(self, control):
        self.held = control
        self.calls.append(("hold", control))

    def release(self):
        self.held = None
        self.calls.append(("release",))

    def set_max_intensity(self, level):
        self.state.state.max_intensity = level

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        self.active_changed.emit(self.active)
        return self.active

    def start(self):
        was_active = self.active
        self.active = True
        self.calls.append(("start",))
        if not was_active:
            self.active_changed.emit(True)

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

    def toggle_learned(self):
        self.calls.append("learned")

    def set_learned(self, on):
        self.calls.append(("learned", on))

    def cycle_shape(self, step=1):
        self.calls.append(("shape", step))

    def set_speed(self, value):
        self.calls.append(("set_speed", value))

    def set_amplitude(self, value):
        self.calls.append(("set_amplitude", value))

    def set_center(self, value):
        self.calls.append(("set_center", value))

    def status_text(self):
        return "OSR2 stub"


def _a_slideshow_standing_on_its_own(qtbot, monkeypatch, **gallery):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions(),
                       client=ComfyUIClient(folders=SUITE_FOLDERS), **gallery)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    return view, slideshow


def _press_enter(slideshow):
    gestures.press_key(slideshow.shown, Qt.Key.Key_Return)


def _press_escape(view):
    return view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )


def _keys_are_the_gallerys(view):
    """Say outright that no other window owns the keystroke — which window Qt
    calls active is ambient in a test process, so a fullscreen slideshow another test
    opened and closed can still hold it."""
    view._other_window_owns_keys = lambda: False


def _two_leaf_view(qtbot, extra=(), actions=None):
    """A view whose Images tree holds two settings folders ("a cat", "a dog")
    under one "(no LoRA)" parent, plus whatever ``extra`` rows are handed in.

    Returns the two folders by *key*: every rebuild throws its tree items away,
    and these tests all rebuild."""
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1), *extra]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    return view, _key(_at(lora, 0)), _key(_at(lora, 1))


def _pick(view, *keys):
    """Pick several folder rows the way a click then Ctrl-clicks does."""
    items = [view._tree_item_for(key) for key in keys]
    view._tree.setCurrentItem(items[0])
    for item in items[1:]:
        item.setSelected(True)


def _make_folder(view, name, keys):
    folder_id = view._db.create_custom_folder(name)
    view._db.add_folders_to_custom_folder(
        folder_id, [(key, "settings", None) for key in keys]
    )
    view.refresh()
    return folder_id


#
# Every test below raises a real menu and answers it by the words the user reads,
# because the menu is where the label is wired to the handler. Calling the handler
# instead — which is what the rest of this file does — leaves that wiring covered
# by nothing at all: swapping two arms of the custom folder's menu, so that its
# harmless entry deleted the folder, used to pass all 657 tests.

def _tall_on_screen(view):
    if not view.isVisible():
        view.resize(1200, 1400)  # room in the list below its last row
        view.show()
        QTest.qWaitForWindowExposed(view)


def _below_the_last_row(tree) -> QPoint:
    last = tree.model().index(0, 0)
    while tree.indexBelow(last).isValid():
        last = tree.indexBelow(last)
    row = tree.visualRect(last)
    below = QPoint(10, row.y() + row.height() + 8)
    assert tree.viewport().rect().contains(below), "the list has no room below its last row"
    return below


def _tree_menu(view, key=None, side=LANDSCAPE):
    """Right-click a folder's row in the list, or the empty space below the last
    row of ``side`` when no key is given, through the window as a mouse does."""
    _tall_on_screen(view)
    if key is None:
        tree = view._tree._trees[side]
        at = _below_the_last_row(tree)
    else:
        row = view._tree_item_for(key)
        tree = row.treeWidget()
        tree.scrollToItem(row)
        at = tree.visualItemRect(row).center()
    gestures.right_click(tree.viewport(), at)


def _requestable_db(tmp_path, prompt="a woman, a hat, soft light"):
    """A DB holding one finished, re-rollable SDXL image — what a spoken request
    is made about. Fabricated prompt text, like every fixture here."""
    db = Database(tmp_path / "test.db")
    params = dict(_SDXL.default_params(), seed=7, positive_prompt=prompt,
                  negative_prompt="blurry")
    db.insert_generation(
        prompt_id="orig", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt=prompt, negative_prompt="blurry", seed=7,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation("orig", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_t2i_orig.png", "subfolder": "image", "type": "output"}]))
    return db


def _requesting_view(qtbot, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("orig.png", "image"))
    view = GalleryView(_requestable_db(tmp_path, **kw), client=_reroll_client())
    qtbot.addWidget(view)
    # The words alone, with no smart matcher: these cover the policy and the
    # plumbing, and a matcher would put a local LLM in the middle of both.
    view._voice._revision = RevisionWorker(
        lambda positive, negative, request, *, in_scenes:
            request_applier(in_scenes)(positive, negative, request),
        parent=view)
    view._voice._revision.revised.connect(view._voice._on_revised)
    view._bank.mic.setChecked(True)  # the switch, as the user flips it
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    return view


def _finish_reroll(view, job):
    """Land a launched job, so what it made is a finished item like any other."""
    view._client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)
    view.refresh()


def _genau_db(tmp_path):
    """The combine DB plus a looping clip launched as the "alpha" act to mine.

    The long-form video the fixture already carries was launched as the same act,
    so this also pins that the Genau lane picks the loop over it. "state two" is
    the one image state the example overlay lets the Genau lane animate at all,
    and "alpha" the one act it allows from it — so an "animate as go now" over
    this image needs no act said. Both images are enhanced already, as
    the combine DB's is.
    """
    db = _combine_db(tmp_path)
    loop = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    db.insert_generation(
        prompt_id="loop", workflow_name="wan22_flf2v_loop", workflow_version=loop.version,
        positive_prompt="one cycle of it", seed=7,
        params_json=json.dumps(dict(loop.default_params(), seed=7, noise_seed=8,
                                    positive_prompt="one cycle of it")),
        workflow_json="{}",
    )
    db.update_generation("loop", status="completed",
                         output_files=json.dumps([{"filename": "flf2v_loop_1.mp4", "subfolder": ""}]))
    db.set_settings_source("loop", category="alpha")
    # A second image, sorted, so a spoken animation has a state to go by. The
    # fixture's original "img" has not been sorted at all.
    db.insert_generation(
        prompt_id="img_act", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="an image by the window", seed=2,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=2,
                                    positive_prompt="an image by the window")),
        workflow_json="{}",
    )
    db.update_generation("img_act", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_act.png", "subfolder": ""},
         {"filename": "sdxl_act_base.png", "subfolder": "", "role": "original"}]))
    db.set_image_state("img_act", "state two")
    return db


def _genau_view(qtbot, tmp_path):
    view = GalleryView(_genau_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view
