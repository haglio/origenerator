from __future__ import annotations

import json
from dataclasses import InitVar, asdict, dataclass
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
    QTextCursor,
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
from origenerator.db import Database, NewGeneration
from origenerator.gallery.collection import (
    TRASH_KEY,
)
from origenerator.gallery.shapes import LANDSCAPE
from origenerator.gallery_edits import GalleryEdits
from origenerator.generation_state import GenerationSource
from origenerator.gui.folder_tree import _action_rects
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView, Shared
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.new_tile import NewTile
from origenerator.item_actions import ItemActions
from origenerator.item_shape import base_of, shaped_key
from origenerator.media import MediaType
from origenerator.motion_engine import Motion
from origenerator.output_places import OutputPlaces
from origenerator.prompt_edit import request_applier
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
    def __init__(self, places=OUTPUT_PLACES, thumb_dir=THUMB_DIR):
        self.places = places
        self.thumb_dir = thumb_dir
        self.deleted = []
        self.rejected = []
        self.trashed_files = []
        self.restored = []
        self.purged = []
        self.undo_count = 0
        self.redo_count = 0
        self._label = None
        self._redo_label = None

    def delete_rows(self, rows, *, pressed=None):
        self.deleted.append(list(rows))
        self._label = f"Delete {len(rows)} items"

    def restore_deleted(self, prompt_ids):
        ids = list(prompt_ids)
        self.restored.append(ids)
        return ids[0] if ids else None

    def purge_deleted(self, prompt_ids):
        self.purged.append(list(prompt_ids))

    def delete_enhance_versions(self, row, filenames):
        return True

    def trash_file(self, path, already_at=None):
        self.trashed_files.append(path if already_at is None else (path, already_at))


    trash = GalleryEdits.trash

    def reject_experiment(self, row, *, pressed=None):
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
    def __init__(self, rows):
        self._rows = list(rows)
        self._by_id = {r["prompt_id"]: r for r in rows}
        self._meta = {}
        self._custom = {}
        self._next_custom = 1
        self._deletions = {}
        self._requests = {}
        self._seed_uses = []
        self._combine_video_uses = []
        self._item_numbers = {}

    def list_generations(self):
        return [dict(row) for row in self._rows]

    def rows_made_by(self, workflow_name):
        return [row for row in self._rows if row.get("workflow_name") == workflow_name]

    def library_version(self):
        return object()

    def record_seed_use(self, use):
        self._seed_uses.insert(0, asdict(use))

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
                if row.get("source_video") and not row.get("action")]

    def list_item_numbers(self):
        return dict(self._item_numbers)

    def record_item_numbers(self, numbers):
        self._item_numbers.update(numbers)

    def get_generation(self, prompt_id):
        return self._by_id.get(prompt_id)

    @property
    def requests(self):
        return self

    def exchange_of(self, prompt_id):
        return []

    def items_asked_into(self, prompt_id):
        return []

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


    def record_trashed(self, prompt_id, row, batch, *, deleted_at=None):
        self._deletions.pop(prompt_id, None)
        self._deletions[prompt_id] = {
            "prompt_id": prompt_id, "row": row, "batch": batch,
            "deleted_at": "2026-08-15 03:00:00",
        }

    def list_trashed(self):
        return list(reversed(self._deletions.values()))

    def get_trashed(self, prompt_id):
        return self._deletions.get(prompt_id)

    def forget_trashed(self, prompt_id):
        self._deletions.pop(prompt_id, None)

    def record_request(self, request):
        self._requests[request.prompt_id] = asdict(request)

    def list_requests(self):
        return list(reversed(self._requests.values()))

    def get_request(self, prompt_id):
        return self._requests.get(prompt_id)

    def requests_about(self, source_prompt_id):
        return [record for record in self.list_requests()
                if record["source_prompt_id"] == source_prompt_id]

    def create_custom_collection(self, name, folder_id=None, shape=None):
        if folder_id is None:
            folder_id = self._next_custom
        self._next_custom = max(self._next_custom, folder_id) + 1
        self._custom[folder_id] = {"name": name, "side": shape, "folders": {}, "items": {}}
        return folder_id

    def delete_custom_collection(self, folder_id):
        self._custom.pop(folder_id, None)

    def add_folders_to_custom_collection(self, folder_id, folders):
        for folder_key, level, ref in folders:
            self._custom[folder_id]["folders"][folder_key] = (level, ref)

    def remove_folder_from_custom_collection(self, folder_id, folder_key):
        self._custom[folder_id]["folders"].pop(folder_key, None)

    def add_items_to_custom_collection(self, folder_id, prompt_ids):
        self._custom[folder_id]["items"].update(dict.fromkeys(prompt_ids))

    def remove_items_from_custom_collection(self, folder_id, prompt_ids):
        for prompt_id in prompt_ids:
            self._custom[folder_id]["items"].pop(prompt_id, None)

    def list_custom_collections(self):
        return [{"id": fid, "name": f["name"], "side": f["side"], "folders": list(f["folders"]),
                 "items": list(f["items"])}
                for fid, f in sorted(self._custom.items())]

    def folders_in_custom_collections(self):
        return [{"folder_id": fid, "folder_key": key, "level": level, "ref_prompt_id": ref}
                for fid, f in self._custom.items()
                for key, (level, ref) in f["folders"].items()]

    def add(self, row):
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
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed,
                 "enhance": True},
                f"sdxl_t2i_{prompt_id}.png")


def _i2v_video(prompt_id, lora, prompt="dance", seed=1):
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": prompt,
                 "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors",
                 "lora_high": f"{lora}_high.safetensors", "lora_low": f"{lora}_low.safetensors",
                 "seed": seed},
                f"wan22_i2v_{prompt_id}.mp4")


def _shape(tree, shape=LANDSCAPE):
    return tree._trees[shape]


def _top_level(tree, shape=LANDSCAPE):
    half = _shape(tree, shape)
    return {half.topLevelItem(i).text(0): half.topLevelItem(i)
            for i in range(half.topLevelItemCount())}


def _alls(tree, shape=LANDSCAPE):
    all_row = _top_level(tree, shape)["All"]
    return {all_row.child(i).text(0): all_row.child(i) for i in range(all_row.childCount())}


def _selected_folder(view):
    return base_of(view.selected_folder_key())


def _collection(view, key, shape=LANDSCAPE):
    return view._tree_item_for(shaped_key(key, shape))


def _shape_rows(view, shape):
    return [row["prompt_id"]
            for row in view._slideshows.rows_at(shaped_key(gallery.ALL_KEY, shape))]


def _key(item):
    return item.data(0, _GROUP_ROLE).key


def _subs(item):
    children = (item.child(i) for i in range(item.childCount()))
    return [child for child in children if child.data(0, _GROUP_ROLE) is not None]


def _at(item, *path):
    for index in path:
        item = _subs(item)[index]
    return item


def _workflow_rows(tree, media=None, shape=LANDSCAPE):
    all_row = _top_level(tree, shape).get("All")
    if all_row is None:
        return {}
    kinds = [kind for kind in _subs(all_row) if media in (None, _key(kind))]
    return {row.text(0): row for kind in kinds for row in _subs(kind)}


def _image_workflow(tree, shape=LANDSCAPE):
    (row,) = _workflow_rows(tree, "image", shape).values()
    return row


def _video_workflow(tree):
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
    return {child.data(0, _GROUP_ROLE).rows[0]["positive_prompt"]: child
            for child in _subs(item)}


def _viewport_of(view):
    tab = view._generate_pane.current_generate_tab()
    return tab._viewport if tab is not None else None


def _frame_shown(preview, frame: bytes) -> bool:
    shown = preview._pixmap
    as_argb = QImage.Format.Format_ARGB32
    return (preview._live and shown is not None
            and shown.toImage().convertToFormat(as_argb)
            == QImage.fromData(frame).convertToFormat(as_argb))


def _search_for(view, text):
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
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    return view.eventFilter(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F, _CTRL))


def _tab_with_prompts(view, key="sdxl_t2i"):
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData(key))
    return tab


def _click_beside_the_mark_of(qtbot, view, key, *, which):
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


def _trash_db(rows=(), held=(), inherited=()):
    db = FakeDB(list(rows))
    for prompt_id, row in held:
        db.record_trashed(prompt_id, row, {"moves": [], "subdir": None})
    for prompt_id, row in inherited:
        db.record_trashed(prompt_id, row, {
            "moves": [[f"out/{prompt_id}.png", f"trash/{prompt_id}/0_{prompt_id}.png"]],
            "subdir": f"trash/{prompt_id}",
        })
    return db


def _trash_collection_view(qtbot, actions, held=(("d1", "a cat"),)):
    view = GalleryView(
        _trash_db(held=[(pid, _image(pid, prompt, 50, n))
                      for n, (pid, prompt) in enumerate(held, start=1)]),
        actions=actions,
    )
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    view._gallery_pane.apply_selection(held[0][0], _NO_MOD)
    return view


def _click_tile(view, prompt_id):
    QTest.mouseClick(view._gallery_pane._thumb_widgets[prompt_id], Qt.MouseButton.LeftButton, _NO_MOD)


def _right_click(view, prompt_id):
    """Right-click through the tile's customContextMenuRequested, the signal Qt raises."""
    view._gallery_pane._thumb_widgets[prompt_id].customContextMenuRequested.emit(QPoint(0, 0))


def _answer_menu(monkeypatch, label):
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
        if act is None:
            raise AssertionError(
                f"no menu entry reading {label!r}: said loudly, not as a menu the user dismissed")
        # Qt triggers the entry clicked before exec returns it.
        act.trigger()
        return act

    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", pick)


def _answer_confirmation(monkeypatch, button):
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
    return list(view._gallery_pane._thumb_widgets)


def _write_looping_webp(path, size=(64, 48)):
    frames = [_Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def _open_leaf(view):
    workflow = _image_workflow(view._tree)
    leaf = _at(workflow, 0, 0, 0)
    view._tree.setCurrentItem(leaf)
    return leaf


def _click_off(view):
    view._gallery_pane.clear_thumbnail_selection()


def _reroll_client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-X")
    client.interrupt = MagicMock()
    client.cancel_prompt = MagicMock()
    client.fetch_history = MagicMock(return_value={})
    client.forget_history = MagicMock()
    return client


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _new_tile(view):
    tiles = view._scroll.widget().findChildren(NewTile)
    return tiles[0] if tiles else None


def _generating_tile(view):
    tiles = view._scroll.widget().findChildren(GeneratingTile)
    return tiles[0] if tiles else None


def _tile_kinds_in_order(view):
    layout = view._scroll.widget().layout()
    return [type(layout.itemAt(index).widget()) for index in range(layout.count())]


def _select_first_leaf(view, shape=LANDSCAPE):
    leaf = _at(_image_workflow(view._tree, shape), 0, 0, 0)
    view._tree.setCurrentItem(leaf)
    return leaf.data(0, _GROUP_ROLE).key


def _seeded_db(tmp_path, seed=7):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="orig",
        workflow_name="sdxl_t2i",
        workflow_version=_SDXL.version,
        positive_prompt="a cat",
        negative_prompt="",
        seed=seed,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=seed, positive_prompt="a cat")),
        workflow_json="{}",
    ))
    db.update_generation(
        "orig", status="completed",
        output_files=json.dumps([{"filename": "sdxl_orig.png", "subfolder": ""}]),
    )
    return db


def _generate_in_current_tab(view, positive_prompt, seed):
    tab = view._generate_pane.current_generate_tab()
    params = dict(_SDXL.default_params(), positive_prompt=positive_prompt, seed=seed)
    tab.prefill("sdxl_t2i", params)
    tab._param_form.set_seed_random(False)
    tab._on_generate()
    return gallery.settings_folder_key(
        {"workflow_name": "sdxl_t2i", "params_json": json.dumps(params)},
        gallery.build_image_config_index(view._image_rows),
    )


def _resolve_by_id(monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: (f"{row['prompt_id']}.png", "image"))


def _in_view(view, prompt_id) -> bool:
    tile = view._gallery_pane._thumb_widgets[prompt_id]
    viewport = view._scroll.viewport()
    return viewport.rect().contains(QRect(tile.mapTo(viewport, QPoint(0, 0)), tile.size()))


def _running_reroll(view, shape=LANDSCAPE):
    key = _select_first_leaf(view, shape)
    _new_tile(view).add_requested.emit()
    return key, view._live_jobs[key]


def _single_i2v_db(tmp_path, input_image):
    db = Database(tmp_path / "hp.db")
    db.insert_generation(NewGeneration(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image=input_image)),
        workflow_json="{}",
    ))
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    return db


def _shown_view_with_one_image(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    output_dir = tmp_path / "output"
    db.insert_generation(NewGeneration(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"steps": 50}), workflow_json="{}",
    ))
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"img")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryEdits(db, OutputPlaces.in_one_folder(output_dir), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):
        view.show()
    view.refresh()
    return view, db, file_path


@dataclass(eq=False)
class _FakeRerollJob:
    prompt_id: str
    workflow_name: InitVar[str]
    params: dict
    state: str = "running"
    frame: InitVar[bytes | None] = None
    progress: InitVar[tuple] = (0, 0)
    foreign_ahead: object = None
    started_at: object = None
    pass_progress: InitVar[object] = None
    stage: InitVar[str] = ""

    def __post_init__(self, workflow_name, frame, progress, pass_progress, stage):
        self.origin = self.prompt_id
        self.last_preview = frame
        self.last_progress = progress
        self.last_pass_progress = pass_progress
        self.last_stage = stage
        self.workflow = WORKFLOW_REGISTRY[workflow_name]
        self.source = GenerationSource.GENERATED
        self.thumb_dir = THUMB_DIR
        self.shielded = False

    def reconcile_with(self, history): ...

    def take_backlog(self, foreign_ahead): ...

    def take_executing(self, executing): ...

    def cancel(self):
        self.state = "canceled"


def _open_latest(view):
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])


def _running_row(prompt_id, prompt="a cat", workflow="sdxl_t2i"):
    return _row(prompt_id, workflow, {"positive_prompt": prompt}, f"{prompt_id}.png",
                status="running", output_files="[]")


def _menu_offering(monkeypatch, module, pick=None):
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
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", seed=1,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=1, positive_prompt="a dog")),
        workflow_json="{}",
    ))
    base = [{"filename": "sdxl_pick_base.png", "subfolder": "", "role": "original"}]
    db.update_generation("img", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_pick.png", "subfolder": ""}] + (base if enhanced else [])))
    db.insert_generation(NewGeneration(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt="dance", seed=42,
        params_json=json.dumps(dict(_WAN_I2V.default_params(),
                                    seed=42, noise_seed=99, positive_prompt="dance")),
        workflow_json="{}",
    ))
    db.update_generation("vid", status="completed",
                         output_files=json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]))
    db.set_settings_source("vid", category="alpha")
    db.set_actions("vid", MediaType.VIDEO, ItemActions(("alpha",)))
    return db


def _struck_and_lit(field) -> tuple[str, str]:
    cursor = QTextCursor(field.document())
    struck = lit = ""
    for position in range(len(field.toPlainText())):
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        if fmt.fontStrikeOut():
            struck += cursor.selectedText()
        elif fmt.background().style() != Qt.BrushStyle.NoBrush:
            lit += cursor.selectedText()
    return struck.strip(), lit.strip()


def _front_panel(view):
    return view._generate_pane.current_generate_tab()


_ENHANCE_HISTORY = {"outputs": {"12": {"images": [
    {"filename": "image_enhance_00001_.png", "subfolder": "image", "type": "output"}]}}}


_BEFORE_THE_ENHANCE_TAIL = "v002"


def _enhanceable_db(tmp_path, count=2):
    db = Database(tmp_path / "test.db")
    for i in range(count):
        pid = f"g{i}"
        db.insert_generation(NewGeneration(
            prompt_id=pid, workflow_name="sdxl_t2i", workflow_version=_BEFORE_THE_ENHANCE_TAIL,
            positive_prompt="a cat", seed=i,
            params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": i}),
            workflow_json="{}",
        ))
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"sdxl_t2i_g{i}.png",
                                                       "subfolder": "image",
                                                       "type": "output"}]))
    return db


def _set_enhance(view, **fields):
    settings = gallery.EnhanceSettings(**fields)
    view.set_enhance_settings(settings.to_json())
    return settings


def _pane_holding(widget):
    while not isinstance(widget.parentWidget(), QSplitter):
        widget = widget.parentWidget()
    return widget


def _enhanced_in_place(db, pid="g0"):
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
    slideshow = (view._slideshows.open_on_preview(None, None) if media is None
                 else view._slideshows.open_in_its_folder(media, view.selected_prompt_id()))
    qtbot.addWidget(slideshow.shown)
    if target is not None:
        _aim_slideshow(view, slideshow, target)
    return slideshow


def _aim_slideshow(view, slideshow, target):
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
                       client=ComfyUIClient(folders=SUITE_FOLDERS),
                       shared=Shared(**gallery))
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
    """Qt's active window outlives the test that opened it, so say that no other window owns the key."""
    view._other_window_owns_keys = lambda: False


def _two_leaf_view(qtbot, extra=(), actions=None):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1), *extra]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    return view, _key(_at(lora, 0)), _key(_at(lora, 1))


def _pick(view, *keys):
    items = [view._tree_item_for(key) for key in keys]
    view._tree.setCurrentItem(items[0])
    for item in items[1:]:
        item.setSelected(True)


def _make_folder(view, name, keys):
    folder_id = view._db.create_custom_collection(name)
    view._db.add_folders_to_custom_collection(
        folder_id, [(key, "settings", None) for key in keys]
    )
    view.refresh()
    return folder_id


def _tall_on_screen(view):
    if not view.isVisible():
        view.resize(1200, 1400)
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


def _tree_menu(view, key=None, shape=LANDSCAPE):
    _tall_on_screen(view)
    if key is None:
        tree = view._tree._trees[shape]
        at = _below_the_last_row(tree)
    else:
        row = view._tree_item_for(key)
        tree = row.treeWidget()
        tree.scrollToItem(row)
        at = tree.visualItemRect(row).center()
    gestures.right_click(tree.viewport(), at)


def _requestable_db(tmp_path, prompt="a woman, a hat, soft light"):
    db = Database(tmp_path / "test.db")
    params = dict(_SDXL.default_params(), seed=7, positive_prompt=prompt,
                  negative_prompt="blurry")
    db.insert_generation(NewGeneration(
        prompt_id="orig", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt=prompt, negative_prompt="blurry", seed=7,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation("orig", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_t2i_orig.png", "subfolder": "image", "type": "output"}]))
    return db


def _from_the_words_alone_with_no_local_model(positive, negative, words, *, in_scenes=False, **_):
    return request_applier(in_scenes)(positive, negative, words)


def _requesting_view(qtbot, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("orig.png", "image"))
    view = GalleryView(_requestable_db(tmp_path, **kw), client=_reroll_client())
    qtbot.addWidget(view)
    view._voice.requests._work_out = _from_the_words_alone_with_no_local_model
    view._voice.requests._wait_for_the_graphics_card = lambda comfyui, holder, **settings: True
    view._buttons.mic.setChecked(True)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    return view


def _finish_reroll(view, job):
    view._client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)
    view.refresh()


def _genau_db(tmp_path):
    db = _combine_db(tmp_path)
    loop = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    db.insert_generation(NewGeneration(
        prompt_id="loop", workflow_name="wan22_flf2v_loop", workflow_version=loop.version,
        positive_prompt="one cycle of it", seed=7,
        params_json=json.dumps(dict(loop.default_params(), seed=7, noise_seed=8,
                                    positive_prompt="one cycle of it")),
        workflow_json="{}",
    ))
    db.update_generation("loop", status="completed",
                         output_files=json.dumps([{"filename": "flf2v_loop_1.mp4", "subfolder": ""}]))
    db.set_settings_source("loop", category="alpha")
    db.set_actions("loop", MediaType.VIDEO, ItemActions(("alpha",)))
    db.insert_generation(NewGeneration(
        prompt_id="img_action", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="an image by the window", seed=2,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=2,
                                    positive_prompt="an image by the window")),
        workflow_json="{}",
    ))
    db.update_generation("img_action", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_action.png", "subfolder": ""},
         {"filename": "sdxl_act_base.png", "subfolder": "", "role": "original"}]))
    db.set_actions("img_action", MediaType.IMAGE, ItemActions(("alpha", "beta")))
    return db


def _genau_view(qtbot, tmp_path):
    view = GalleryView(_genau_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view
