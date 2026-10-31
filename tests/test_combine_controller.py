"""Combine, driven with no gallery around it.

The whole act used to be reachable only by building the app's central widget:
which settings a picked act resolves to, what a stand-in row does before there is
a job, and what a spoken animation refuses. Here the host is a handful of
recorded calls.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import urllib.request

import pytest
from PIL import Image
from PyQt6.QtWidgets import QWidget

from origenerator import act_settings, evolver_export, gallery
from origenerator.animate_command import AnimateRequest
from origenerator.db import Database
from origenerator.export_lane import GENAU
from origenerator.generation_state import GenerationSource
from origenerator.gui import combine_controller as module
from origenerator.gui import file_pick
from origenerator.gui.combination import Combination
from origenerator.gui.combine_controller import ALREADY_GENAUD, CombineController
from origenerator.gui.combine_panel import CombineRequest
from origenerator.gui.notice_overlay import ERROR, NOTICE, WARNING
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import OutsideVideo, Record, rows_bringing_in
from tests.thumbnail_rows import square

IMAGE_WORKFLOW = "sdxl_t2i"
VIDEO_WORKFLOW = "wan22_i2v"


_A_CLIENT = object()


class FakePanel:
    """The combine panel reduced to what the controller drives."""

    class _Slot:
        def __init__(self):
            self.item = None
            self.changed = _Signal()

        def current_id(self):
            return self.item

        def set_item(self, prompt_id):
            self.item = prompt_id
            self.changed.emit()

    def __init__(self, image_lent_by, video_lent_by, preview, history, *,
                 named=None, name_of=None, browse_image=None, leads_to=None):
        self.image_lent_by = image_lent_by
        self.video_lent_by = video_lent_by
        self.preview = preview
        self.history = history
        self.named = named
        self.name_of = name_of
        self.browse_image = browse_image
        self.leads_to = leads_to
        self.image_slot = self._Slot()
        self.video_slot = self._Slot()
        self.intent = act_settings.VIDEO
        self.category = ""
        self.dropped = {}
        self.available = None
        self.visible = None
        self.folder_generating = None
        self.combine_requested = _Signal()
        self.animation_settings_requested = _Signal()
        self.intent_changed = _Signal()
        self.item_activated = _Signal()
        self.video_used = _Signal()

    def selected_intent(self):
        return self.intent

    def selected_category(self):
        return self.category

    def set_intent(self, intent):
        self.intent = intent

    def set_category(self, category):
        self.category = category

    def dropped_videos(self):
        return dict(self.dropped)

    def set_dropped_videos(self, videos):
        self.dropped = dict(videos)
        if not self.category:
            self.video_slot.set_item(self.dropped.get(self.intent))

    def set_available_categories(self, categories):
        self.available = list(categories)

    def hide(self):
        self.visible = False

    def note_folder_generating(self, generating):
        self.folder_generating = generating


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeWorkflow:
    def __init__(self, name=VIDEO_WORKFLOW, version="3"):
        self.name = name
        self.version = version

    def seed_keys(self):
        return ("seed",)

    def default_params(self):
        return {}

    def param_definitions(self):
        return []


class FakeJob:
    def __init__(self, prompt_id):
        self.prompt_id = prompt_id


class FakeReroll:
    def __init__(self, launches="new-run", making=()):
        self.prepared = []
        self.launches = launches
        self.making = set(making)

    def start_prepared(self, key, workflow, params):
        self.prepared.append((key, workflow.name, dict(params)))
        return self.launches

    def job_for(self, key):
        return FakeJob("the-run-already-going") if key in self.making else None


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: dict(row) for row in rows}
        self.settings_sources = []
        self.requested = []
        self.exported = []
        self.uses = []
        self.combinations = []

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def list_generations(self):
        return [dict(row) for row in self.rows.values()]

    def set_settings_source(self, prompt_id, *, category="", video_prompt_id=None):
        self.settings_sources.append((prompt_id, category, video_prompt_id))

    def record_combine_video_use(self, intent, video_prompt_id, generation_prompt_id=None):
        self.uses.append((intent, video_prompt_id, generation_prompt_id))

    def list_combine_video_uses(self):
        return [{"intent": intent, "video_prompt_id": video,
                 "generation_prompt_id": generation, "created_at": f"2026-10-02 00:00:{n:02}"}
                for n, (intent, video, generation) in reversed(list(enumerate(self.uses)))]

    def custom_combinations(self):
        return list(self.combinations)

    def mark_genau_requested(self, prompt_id):
        self.requested.append(prompt_id)

    def mark_genau_exported(self, prompt_id):
        self.exported.append(prompt_id)


class FakeSlideshows:
    def __init__(self, showing=None):
        self.showing = showing
        self.runs_said = []

    def note_voice_run(self, prompt_id, message, *, kind):
        self.runs_said.append((prompt_id, message, kind))


class FakeTabs:
    def __init__(self, panel=None):
        self.panel = panel
        self.opened = []

    def open_config(self, workflow_name, params):
        self.opened.append((workflow_name, dict(params)))
        return self.panel


class FakeConfigPanel:
    def __init__(self):
        self.source = None
        self.combination = None

    def set_settings_source(self, category, video_id, intent):
        self.source = (category, video_id, intent)

    def show_combination(self, combination):
        self.combination = combination


class FakeHost:
    """A gallery reduced to what a combine asks of one."""

    def __init__(self, *, rows=()):
        self.rows = list(rows)
        self.queue_redraws = 0
        self.revealed = []
        self.told = []

    def image_config_index(self):
        return gallery.build_image_config_index(self.rows)

    def animated_preview(self, row):
        return f"{row['prompt_id']}.webp"

    def folder_key_of(self, row):
        return f"folder-of-{row['prompt_id']}"

    def folder_key_for(self, workflow_name, params, workflow_version=None):
        return f"folder-for-{workflow_name}-{workflow_version}"

    def queue_changed(self):
        self.queue_redraws += 1

    def reveal_launch(self, key):
        self.revealed.append(key)

    def follow_link(self, prompt_id):
        pass

    def tell(self, title, message):
        self.told.append((title, message))


def _image(prompt_id="img", *, prompt="a doll on a couch", files=("one.png",),
           source="generated", state=None):
    return {
        "prompt_id": prompt_id,
        "workflow_name": IMAGE_WORKFLOW,
        "positive_prompt": prompt,
        "status": "completed",
        "source": source,
        "thumbnail_path": f"{prompt_id}-thumb.png",
        "output_files": json.dumps([{"filename": name} for name in files]),
        "params_json": "{}",
        "image_state": state,
    }


def _video(prompt_id="clip", *, workflow_name=VIDEO_WORKFLOW, status="completed",
           requested=None, exported=None, source_image=None, files=None, act=None):
    return {
        "prompt_id": prompt_id,
        "act": act,
        "workflow_name": workflow_name,
        "positive_prompt": "a doll on a couch, waving",
        "status": status,
        "thumbnail_path": f"{prompt_id}-thumb.png",
        "output_files": json.dumps(
            [{"filename": name} for name in files] if files is not None
            else [{"filename": f"{prompt_id}.mp4"}]),
        "params_json": json.dumps({"input_image": source_image} if source_image else {}),
        "genau_requested_at": requested,
        "genau_exported_at": exported,
    }


@pytest.fixture
def combine(qtbot, monkeypatch):
    """A controller under a parent this fixture keeps alive, with a recorder for
    a panel."""
    monkeypatch.setattr(module, "CombinePanel", FakePanel)
    built = []

    def build(host=None, *, db=None, jobs=None, client=_A_CLIENT, slideshows=None,
              tabs=None, inbox=None):
        host = host or FakeHost()
        parent = QWidget()
        qtbot.addWidget(parent)
        controller = CombineController(
            host, parent=parent, db=db or FakeDB(), jobs=jobs or FakeReroll(),
            client=client, info_tabs_of=lambda: tabs or FakeTabs(),
            slideshows=slideshows or FakeSlideshows(), inbox=inbox)
        # The wait between a press and a real job is what the stand-in row is
        # for; running it straight through is what lets a test press and look.
        controller._after_painting = lambda work: work()
        built.append((parent, controller))
        return controller, host
    yield build


# --- what the slots take ----------------------------------------------------


def test_the_image_slot_takes_an_image_with_a_file_to_seed_from(combine):
    # Not merely anything that produced a file: a video's clip would satisfy
    # that and cannot be a start frame.
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    assert controller._accepts_image("img") is True
    assert controller._accepts_image("clip") is False


def test_an_image_lends_the_image_slot_itself(combine):
    controller, _host = combine(db=FakeDB([_image("img")]))

    assert controller._image_lent_by("img") == "img"
    assert controller._image_lent_by("gone") is None


def test_a_video_lends_the_image_slot_the_image_it_was_made_from(combine):
    image = _image("img", files=("frame.png",))
    controller, _host = combine(
        FakeHost(rows=[image]),
        db=FakeDB([image, _video("clip", source_image="images/frame.png [output]")]))

    assert controller._image_lent_by("clip") == "img"


def test_a_video_made_from_words_alone_lends_the_image_slot_its_starting_frame(combine, tmp_path):
    db = Database(tmp_path / "test.db")
    file = tmp_path / "outbox" / "portrait" / "a-site" / "c1_topaz.mp4"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"not really a video")
    db.insert_rows(rows_bringing_in(
        OutsideVideo(file, "a-site"), Record(), frames_dir=tmp_path / "frames",
        thumb_dir=tmp_path / "thumbs", grab=lambda _path: Image.new("RGB", (64, 96))))
    rows = db.list_generations()
    [shown] = [row for row in rows if gallery.media_type_of_row(row) == MediaType.VIDEO]
    controller, _host = combine(
        FakeHost(rows=[row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE]),
        db=db)

    lent = controller._image_lent_by(shown["prompt_id"])

    assert db.get_generation(lent)["source"] == GenerationSource.STARTING_FRAME


def test_a_video_made_from_an_image_the_gallery_lacks_lends_the_image_slot_nothing(combine):
    controller, _host = combine(db=FakeDB([_video("clip", source_image="elsewhere.png")]))

    assert controller._image_lent_by("clip") is None


def _a_dropped_pair(combine, *, making=()):
    image = _image("img", files=("frame.png",))
    controller, _host = combine(FakeHost(rows=[image]),
                                db=FakeDB([image, _video("clip")]),
                                jobs=FakeReroll(making=making))
    controller.panel.image_slot.set_item("img")
    controller.panel.video_slot.set_item("clip")
    return controller


def test_generate_grays_while_the_folder_a_dropped_pair_lands_in_is_making_one(combine):
    controller = _a_dropped_pair(combine, making={"folder-of-clip"})

    assert controller.panel.folder_generating is True


def test_a_pair_whose_folder_is_making_nothing_leaves_generate_alone(combine):
    controller = _a_dropped_pair(combine, making={"folder-of-another"})

    assert controller.panel.folder_generating is False


def test_generate_comes_back_when_the_run_in_that_folder_ends(combine):
    controller = _a_dropped_pair(combine, making={"folder-of-clip"})

    controller._jobs.making.clear()
    controller.reconcile_generating()

    assert controller.panel.folder_generating is False


def test_the_video_slot_takes_only_a_video_this_app_can_rebuild(combine):
    controller, _host = combine(db=FakeDB([
        _video("clip"), _video("import", workflow_name="a_stranger")]))

    assert controller._accepts_video("clip") is True
    assert controller._accepts_video("import") is False


def test_a_dropped_item_shows_its_still_and_its_loop(combine):
    controller, _host = combine(db=FakeDB([_video("clip")]))

    assert controller._slot_preview("clip") == ("clip-thumb.png", "clip.webp")
    assert controller._slot_preview("gone") == (None, None)


def test_a_panel_with_no_server_behind_it_hides(combine):
    controller, _host = combine(client=None)

    assert controller.panel.visible is False


# --- what a session keeps ---------------------------------------------------


def test_the_session_keeps_the_image_each_lanes_videos_the_lane_and_the_act(combine):
    # None of the four is recoverable from the others: an act says nothing about
    # which lane answers it.
    controller, _host = combine()
    controller.panel.image_slot.set_item("img")
    controller.panel.set_dropped_videos({act_settings.VIDEO: "clip"})
    controller.panel.set_intent(act_settings.GENAU)
    controller.panel.set_category("waving")

    assert controller.selection() == {
        "image": "img", "videos": {act_settings.VIDEO: "clip"},
        "intent": act_settings.GENAU, "category": "waving"}


def test_a_restore_hands_each_lane_back_the_video_it_had_if_it_still_fits(combine):
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip"), _video("loop")]))

    controller.restore({"image": "img", "intent": act_settings.GENAU,
                        "videos": {act_settings.VIDEO: "clip", act_settings.GENAU: "loop",
                                   "elsewhere": "gone"}})

    assert controller.panel.dropped == {act_settings.VIDEO: "clip", act_settings.GENAU: "loop"}
    assert controller.panel.video_slot.item == "loop"


def test_a_video_put_in_the_slot_is_kept_in_the_library_under_its_lane(combine):
    db = FakeDB()
    controller, _host = combine(db=db)

    controller.panel.video_used.emit(act_settings.GENAU, "clip")

    assert db.uses == [(act_settings.GENAU, "clip", None)]


def test_recent_lists_each_lanes_videos_out_of_the_library(combine):
    db = FakeDB()
    db.combinations = [{"prompt_id": "made", "source_video": "older",
                        "created_at": "2026-10-01 00:00:00"}]
    controller, _host = combine(db=db)

    controller.panel.video_used.emit(act_settings.VIDEO, "clip")

    assert controller.panel.history(act_settings.VIDEO) == ["clip", "older"]
    assert controller.panel.history(act_settings.GENAU) == ["older"]


def test_a_restore_puts_the_lane_in_before_the_act(combine):
    # The lane decides which acts are answerable, and set_category refuses one
    # that is grayed out under it.
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    controller.restore({"image": "img", "video": "clip",
                        "intent": act_settings.GENAU, "category": "waving"})

    assert controller.panel.intent == act_settings.GENAU
    assert controller.panel.category == "waving"


def test_a_restore_skips_an_item_that_no_longer_fits_its_slot(combine):
    controller, _host = combine(db=FakeDB([_image("img")]))

    controller.restore({"image": "img", "video": "gone"})

    assert controller.panel.image_slot.item == "img"
    assert controller.panel.video_slot.item is None


def test_the_two_item_list_older_sessions_wrote_still_restores(combine):
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    controller.restore(["img", "clip"])

    assert controller.panel.image_slot.item == "img"
    assert controller.panel.video_slot.item == "clip"


# --- the stand-in row -------------------------------------------------------


def test_a_press_puts_a_row_in_the_line_before_there_is_a_job(combine):
    # The work between the press and a real job is seconds long, and a button
    # that seems to do nothing reads as an app that has died.
    controller, host = combine(db=FakeDB([_image("img"), _video("clip")]))

    key = controller._show_launching("img", video_id="clip")

    (row,) = controller.launching_rows()
    assert row.key == key
    assert row.reading.status == "queued"
    assert row.starting is True
    assert row.source_video_thumbnail == "clip-thumb.png"
    assert host.queue_redraws == 1


def test_a_picked_act_names_itself_rather_than_showing_a_video(combine):
    controller, _host = combine(db=FakeDB([_image("img")]))

    controller._show_launching("img", category="waving")

    (row,) = controller.launching_rows()
    assert row.act == "waving"
    assert row.source_video_thumbnail is None


def test_the_stand_in_row_comes_off_however_the_launch_ends(combine):
    controller, host = combine(db=FakeDB([_image("img")]))
    key = controller._show_launching("img", category="waving")

    controller._drop_launching(key)
    controller._drop_launching(key)  # twice costs nothing

    assert controller.launching_rows() == []
    assert host.queue_redraws == 2


# --- launching a dropped pair ----------------------------------------------


def test_a_dropped_pair_runs_the_videos_settings_on_the_image(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params",
                        lambda video_row, image_row, wf: {"seed": 7, "input_image": "one.png"})
    jobs = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img"), _video("clip")]), jobs=jobs)

    controller._generate_combination("img", "clip")

    assert [name for _key, name, _params in jobs.prepared] == [VIDEO_WORKFLOW]
    assert host.revealed == ["folder-of-clip"]


def test_a_dropped_pair_notes_the_lane_its_video_was_used_under(combine, monkeypatch):
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, FakeWorkflow())
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params", lambda v, i, wf: {"seed": 7})
    db = FakeDB([_image("img"), _video("clip")])
    controller, _host = combine(db=db)

    controller._generate_combination("img", "clip", intent=act_settings.GENAU)
    controller._generate_combination("img", "clip", category="waving")

    assert db.uses == [(act_settings.GENAU, "clip", "new-run")]


def test_an_unrebuildable_pair_launches_nothing(combine, monkeypatch):
    monkeypatch.delitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, raising=False)
    jobs = FakeReroll()
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]), jobs=jobs)

    controller._generate_combination("img", "clip")

    assert jobs.prepared == []


# --- finding the settings an act names --------------------------------------


def test_an_act_with_nothing_assigned_runs_its_most_used_video_and_asks_no_model(
        combine, monkeypatch):
    sent = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, FakeWorkflow())
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params",
                        lambda video_row, image_row, wf: {"seed": 7})
    controller, host = combine(
        db=FakeDB([_image("img", state="state one"), _video("clip", act="waving")]))

    controller.generate_category("img", "waving")

    assert sent == []
    assert host.revealed == ["folder-of-clip"]


def test_pinned_settings_outrank_the_mining(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.act_settings, "pinned_settings",
                        lambda category, intent: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "written_params",
                        lambda settings, row, wf: {"seed": 3})
    mined = []
    monkeypatch.setattr(module.act_settings, "most_used_video",
                        lambda *a, **k: mined.append(1))
    jobs = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img")]), jobs=jobs)

    controller.generate_category("img", "waving")

    assert mined == []  # never asked: the overlay had pinned settings
    assert jobs.prepared[0][0] == f"folder-for-{VIDEO_WORKFLOW}-3"
    assert host.revealed == [f"folder-for-{VIDEO_WORKFLOW}-3"]


def test_an_act_with_no_past_video_says_so_and_launches_nothing(combine,
                                                                monkeypatch):
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setattr(module.act_settings, "most_used_video", lambda *a, **k: None)
    jobs = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img")]), jobs=jobs)

    controller.generate_category("img", "waving")

    assert jobs.prepared == []
    assert host.told == [("No past video yet",
                          "No past “waving” video to take settings from yet — make "
                          "one first, or drop a specific video instead.")]


def test_that_hint_lands_in_the_slideshows_corner_rather_than_a_dialog(combine,
                                                                       monkeypatch):
    # A dialog thrown over an image someone is talking to is the one place this
    # must never appear.
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setattr(module.act_settings, "most_used_video", lambda *a, **k: None)
    slideshows = FakeSlideshows(showing=object())
    controller, host = combine(db=FakeDB([_image("img")]), slideshows=slideshows)

    controller.generate_category("img", "waving", act_settings.GENAU)

    assert host.told == []
    assert slideshows.runs_said == [
        (None, "no past looping “waving” flick to take settings from yet", WARNING)]


def test_the_stand_in_row_goes_whatever_the_match_answers(combine, monkeypatch):
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setattr(module.act_settings, "most_used_video", lambda *a, **k: None)
    controller, _host = combine(db=FakeDB([_image("img")]))

    controller.panel.combine_requested.emit(CombineRequest(
        image_id="img", category="waving", intent=act_settings.VIDEO))

    assert controller.launching_rows() == []


# --- opening one instead of running it --------------------------------------


def test_an_opened_combination_prefills_a_tab_with_both_its_halves(combine,
                                                                   monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params", lambda v, i, wf: {"seed": 7})
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    panel = FakeConfigPanel()
    tabs = FakeTabs(panel)
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]), tabs=tabs)

    controller._open_combination("img", "clip")

    assert tabs.opened == [(VIDEO_WORKFLOW, {"seed": 7})]
    assert panel.source == ("", "clip", act_settings.VIDEO)
    assert panel.combination == Combination("img-thumb.png", "clip.webp")


def test_a_curated_act_opened_shows_the_frame_alone(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.act_settings, "pinned_settings",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "written_params", lambda s, r, wf: {"seed": 3})
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    panel = FakeConfigPanel()
    controller, _host = combine(db=FakeDB([_image("img")]), tabs=FakeTabs(panel))

    controller._open_category("img", "waving")

    assert panel.combination == Combination("img-thumb.png")


def _nothing_assigned(monkeypatch):
    monkeypatch.setattr(module.animation_settings, "settings_for",
                        lambda lane, act, state: None)
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)


def _apart_from_the_image_and_the_seeds(params, workflow):
    rolled = {*workflow.seed_keys(), "input_image"}
    return {key: value for key, value in params.items() if key not in rolled}


@pytest.mark.parametrize("state", ["state one", None], ids=["sorted", "unsorted"])
def test_an_act_with_no_settings_assigned_opens_the_lanes_workflow_as_it_starts(
        combine, monkeypatch, state):
    # A past video of the act is there, and its settings are not what opens.
    _nothing_assigned(monkeypatch)
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    panel = FakeConfigPanel()
    tabs = FakeTabs(panel)
    controller, host = combine(
        db=FakeDB([_image("img", state=state), _video("clip", act="waving")]), tabs=tabs)

    controller._open_category("img", "waving")

    (name, params), = tabs.opened
    workflow = module.WORKFLOW_REGISTRY[name]
    assert workflow.display_name == "WAN 2.2 I2V"
    assert params["input_image"] == "one.png [output]"
    assert (params["positive_prompt"], params["negative_prompt"]) == ("", "")
    assert (_apart_from_the_image_and_the_seeds(params, workflow)
            == _apart_from_the_image_and_the_seeds(workflow.default_params(), workflow))
    assert panel.source == ("waving", None, act_settings.VIDEO)
    assert panel.combination == Combination("img-thumb.png")
    assert host.told == []


def test_the_lanes_workflow_opens_with_its_prompts_empty_whatever_it_starts_with(
        combine, monkeypatch):
    class StartsWithWords(FakeWorkflow):
        def default_params(self):
            return {"positive_prompt": "scene one", "negative_prompt": "scene two",
                    "steps": 20}

    _nothing_assigned(monkeypatch)
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, StartsWithWords())
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    tabs = FakeTabs(FakeConfigPanel())
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]), tabs=tabs)

    controller._open_category("img", "waving")

    (_name, params), = tabs.opened
    assert (params["positive_prompt"], params["negative_prompt"]) == ("", "")
    assert params["steps"] == 20


def _what_the_press_runs(combine, monkeypatch, *, edit_first, lane, assigned):
    monkeypatch.setattr(module.animation_settings, "settings_for", lambda *_: assigned)
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    jobs, tabs = FakeReroll(), FakeTabs(FakeConfigPanel())
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]),
                                jobs=jobs, tabs=tabs)

    controller.panel.combine_requested.emit(CombineRequest(
        image_id="img", category="waving", intent=lane, edit_first=edit_first))

    ran = tabs.opened if edit_first else [
        (name, params) for _key, name, params in jobs.prepared]
    return [(name, _apart_from_the_image_and_the_seeds(
        params, module.WORKFLOW_REGISTRY[name])) for name, params in ran]


@pytest.mark.parametrize("lane", [act_settings.VIDEO, act_settings.GENAU])
@pytest.mark.parametrize("edit_first", [False, True],
                         ids=["generate", "edit individual"])
def test_settings_assigned_by_prompts_alone_run_as_if_they_named_the_lanes_own_workflow(
        combine, monkeypatch, edit_first, lane):
    # Assigned in Edit default… where no video was kept and the act had no
    # settings of its own, so the record holds what he typed and no workflow.
    prompts = {"positive_prompt": "scene one", "negative_prompt": "scene two"}
    lanes_own = act_settings.starting_settings(lane)["workflow"]

    ran = {workflow: _what_the_press_runs(
               combine, monkeypatch, edit_first=edit_first, lane=lane,
               assigned={"workflow": workflow, "params": prompts})
           for workflow in ("", lanes_own)}

    assert ran[""] == ran[lanes_own]
    (_name, params), = ran[""]
    assert params["positive_prompt"].startswith("scene one")
    assert params["negative_prompt"].startswith("scene two")


# --- a spoken animation over the image on screen ---------------------------


def test_a_run_that_errored_made_no_clip_and_does_not_stand_in_for_one(combine,
                                                                       monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    monkeypatch.setattr(module.gallery, "find_source_image_id",
                        lambda row, rows: "img")
    db = FakeDB([_image("img", state="state one"),
                 _video("clip", status="error", requested="now", files=[])])
    controller, _host = combine(db=db)

    # It gets as far as launching, which means the image was not refused.
    assert controller.animate_it(
        "img", AnimateRequest(act_settings.GENAU, "waving"))[1] != ALREADY_GENAUD


def test_a_spoken_launch_is_stamped_to_hand_its_clip_on(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.act_settings, "pinned_settings",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "written_params", lambda s, r, wf: {"seed": 3})
    db = FakeDB([_image("img")])
    controller, _host = combine(db=db)

    controller.generate_category("img", "waving", act_settings.GENAU, send=True)

    assert db.requested == ["new-run"]


def test_a_pressed_generate_leaves_its_clip_in_the_gallery(combine, monkeypatch):
    # Someone at the keyboard can look at it first; someone talking to a
    # fullscreen image cannot.
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.act_settings, "pinned_settings",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "written_params", lambda s, r, wf: {"seed": 3})
    db = FakeDB([_image("img")])
    controller, _host = combine(db=db)

    controller.generate_category("img", "waving", act_settings.GENAU)

    assert db.requested == []


def test_a_spoken_clip_hands_itself_on_when_it_lands(combine, monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "clip.mp4").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    sent = []
    monkeypatch.setattr(module.evolver_export, "export_video",
                        lambda path, destination, funscript=None: sent.append(path.name))
    db = FakeDB()
    controller, _host = combine(db=db)

    controller.send_to_genau_if_requested(_video("clip", requested="now"))

    assert sent == ["clip.mp4"]
    assert db.exported == ["clip"]


def test_the_clip_lands_in_the_inbox_this_controller_was_handed(combine, monkeypatch,
                                                                tmp_path):
    """No patching of anything: where a clip goes used to be a config constant
    this module imported, so a test could only redirect it by reaching into the
    module. It is an object now, given at construction."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "clip.mp4").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    inbox = tmp_path / "somebody elses inbox"
    controller, _host = combine(db=FakeDB(),
                                inbox=evolver_export.EvolverInbox(inbox))

    controller.send_to_genau_if_requested(_video("clip", requested="now"))

    assert (inbox / GENAU.source / "clip.mp4").read_bytes() == b"pixels"


def test_a_clip_already_handed_on_is_not_sent_twice(combine, monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(module.evolver_export, "export_video",
                        lambda path, destination, funscript=None: sent.append(path))
    controller, _host = combine()

    controller.send_to_genau_if_requested(
        _video("clip", requested="then", exported="then"))

    assert sent == []


def test_a_failed_hand_off_leaves_the_clip_in_the_gallery(combine, monkeypatch,
                                                          tmp_path):
    # The clip is safe either way, and Send-to-Genau is still there to retry with.
    output = tmp_path / "output"
    output.mkdir()
    (output / "clip.mp4").write_bytes(b"pixels")
    monkeypatch.setattr(module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))

    def boom(path, destination, funscript=None):
        raise OSError("the inbox is not there")

    monkeypatch.setattr(module.evolver_export, "export_video", boom)
    db = FakeDB()
    controller, _host = combine(db=db)

    controller.send_to_genau_if_requested(_video("clip", requested="now"))

    assert db.exported == []


# --- which acts are pickable at all -----------------------------------------


def test_an_act_with_no_video_under_it_is_grayed_out(combine, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_image_conditioned",
                        lambda name: name == VIDEO_WORKFLOW)
    monkeypatch.setattr(module.act_settings, "available_categories",
                        lambda rows, intent: [r["prompt_id"] for r in rows])
    controller, _host = combine()

    controller.offer_the_acts([_video("clip"), _image("img"),
                               _video("half", status="running")])

    assert controller.panel.available == ["clip"]


def test_switching_lanes_re_asks_which_acts_are_answerable(combine, monkeypatch):
    # An act with plenty of long-form video under it may have no loop at all.
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    seen = []
    monkeypatch.setattr(module.act_settings, "available_categories",
                        lambda rows, intent: seen.append(intent) or [])
    controller, _host = combine(db=FakeDB([_video("clip")]))
    controller.panel.set_intent(act_settings.GENAU)

    controller.panel.intent_changed.emit(act_settings.GENAU)

    assert seen == [act_settings.GENAU]


def test_a_spoken_act_whose_folder_is_already_making_one_joins_that_run(combine, monkeypatch):
    # One item at a time per folder, and the spoken request still gets its clip: the
    # run already going is stamped to be handed over when it lands, rather than a
    # second one being made of the same thing.
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.act_settings, "pinned_settings",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "written_params", lambda s, r, wf: {"seed": 3})
    slideshows = FakeSlideshows(showing="img")
    db = FakeDB([_image("img")])
    jobs = FakeReroll(launches=None, making={f"folder-for-{VIDEO_WORKFLOW}-3"})
    controller, _host = combine(db=db, slideshows=slideshows, jobs=jobs)

    controller.generate_category("img", "waving", send=True)

    assert db.requested == ["the-run-already-going"]
    assert jobs.prepared == []
    assert [message for _pid, message, _kind in slideshows.runs_said] == [module.ALREADY_MAKING_ONE]
# --- the spoken "animate as" -------------------------------------------------

_PATHS = {
    "animation_paths": {
        act_settings.VIDEO: {"waving": ["state one"], "leaning": ["state one"]},
        act_settings.GENAU: {"waving": ["state one"]},
    },
}


def _paths(monkeypatch):
    monkeypatch.setattr(module.animation_paths, "load_content", lambda: _PATHS)


def _no_mining(monkeypatch, available=("waving",)):
    monkeypatch.setattr(module.act_settings, "available_categories",
                        lambda rows, intent: list(available))
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: None)
    monkeypatch.setattr(module.act_settings, "most_used_video", lambda *a, **k: None)


def test_animate_as_runs_the_act_it_names_in_the_lane_it_names(combine, monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))
    launched = []
    controller.generate_category = lambda *args, **kw: launched.append((args, kw))

    answer = controller.animate_it("img", AnimateRequest(act_settings.GENAU, "waving"))

    assert answer == ("img", "animating as “waving”", NOTICE)
    assert launched == [(("img", "waving", act_settings.GENAU), {"send": True})]


def test_animate_as_with_no_act_said_takes_the_one_the_image_leaves(combine,
                                                                    monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))
    launched = []
    controller.generate_category = lambda *args, **kw: launched.append((args, kw))

    controller.animate_it("img", AnimateRequest(act_settings.GENAU, ""))

    assert launched == [(("img", "waving", act_settings.GENAU), {"send": True})]


def test_a_full_length_animation_is_left_in_the_gallery_rather_than_handed_on(
        combine, monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch, available=("waving", "leaning"))
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))
    launched = []
    controller.generate_category = lambda *args, **kw: launched.append((args, kw))

    controller.animate_it("img", AnimateRequest(act_settings.VIDEO, "leaning"))

    assert launched == [(("img", "leaning", act_settings.VIDEO), {"send": False})]


def test_an_act_this_image_cannot_do_is_said_and_nothing_is_run(combine,
                                                                monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))

    prompt_id, message, kind = controller.animate_it(
        "img", AnimateRequest(act_settings.GENAU, "leaning"))

    assert prompt_id is None
    assert "leaning" in message
    assert kind == ERROR


def test_an_image_nobody_has_sorted_yet_is_asked_about_first(combine, monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    controller, _host = combine(db=FakeDB([_image("img")]))

    prompt_id, message, kind = controller.animate_it(
        "img", AnimateRequest(act_settings.VIDEO, "waving"))

    assert prompt_id is None
    assert "sorted" in message
    assert kind == WARNING


def test_animate_as_declines_a_video(combine):
    controller, _host = combine(db=FakeDB([_video("clip")]))

    assert controller.animate_it("clip", AnimateRequest(act_settings.VIDEO, "waving")) == (
        None, "only an image can be animated", WARNING)


def test_an_act_with_no_past_video_yet_says_so(combine, monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch, available=())
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))

    prompt_id, message, kind = controller.animate_it(
        "img", AnimateRequest(act_settings.GENAU, "waving"))

    assert prompt_id is None
    assert "waving" in message
    assert kind == WARNING


def test_a_second_loop_asked_for_over_an_image_with_one_coming_is_refused(
        combine, monkeypatch):
    _paths(monkeypatch)
    _no_mining(monkeypatch)
    monkeypatch.setattr(module.gallery, "find_source_image_id", lambda row, rows: "img")
    db = FakeDB([_image("img", state="state one"),
                 _video("clip", status="running", requested="now")])
    controller, _host = combine(db=db)

    assert controller.animate_it("img", AnimateRequest(act_settings.GENAU, "waving")) == (
        None, ALREADY_GENAUD, WARNING)


def test_the_acts_narrow_to_what_the_dropped_image_can_start_from(combine,
                                                                     monkeypatch):
    _paths(monkeypatch)
    monkeypatch.setattr(module.act_settings, "available_categories",
                        lambda rows, intent: {"waving", "leaning"})
    controller, _host = combine(db=FakeDB([_image("img", state="state one"),
                                           _video("clip")]))

    controller.panel.image_slot.set_item("img")

    assert sorted(controller.panel.available) == ["leaning", "waving"]

    monkeypatch.setattr(module.animation_paths, "acts_for",
                        lambda state, lane, **kw: ("waving",))
    controller.image_dropped()

    assert sorted(controller.panel.available) == ["waving"]


def test_an_image_nobody_has_sorted_yet_narrows_nothing(combine, monkeypatch):
    # Graying every act over an image that says nothing about itself would read
    # as the panel being broken.
    _paths(monkeypatch)
    monkeypatch.setattr(module.act_settings, "available_categories",
                        lambda rows, intent: {"waving", "leaning"})
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    controller.panel.image_slot.set_item("img")

    assert sorted(controller.panel.available) == ["leaning", "waving"]


def test_the_settings_accepted_for_this_images_own_state_outrank_the_acts_pin(
        combine, monkeypatch, tmp_path):
    """The same act started from two situations is two runs, and the overlay's
    per-act pin can only be right for one of them."""
    pinned = {"workflow": VIDEO_WORKFLOW, "params": {"steps": 4}}
    accepted = {"workflow": VIDEO_WORKFLOW, "params": {"steps": 24}}
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: pinned)
    monkeypatch.setattr(module.animation_settings, "settings_for",
                        lambda lane, act, state: accepted if state else None)
    controller, _host = combine(db=FakeDB([_image("img", state="state one")]))

    built = controller._curated_combination("img", "waving")

    assert built is not None
    assert built[1]["steps"] == 24


def test_an_image_nobody_sorted_still_gets_the_acts_pin(combine, monkeypatch):
    pinned = {"workflow": VIDEO_WORKFLOW, "params": {"steps": 4}}
    monkeypatch.setattr(module.act_settings, "pinned_settings", lambda c, i: pinned)
    monkeypatch.setattr(module.animation_settings, "settings_for",
                        lambda lane, act, state: None)
    controller, _host = combine(db=FakeDB([_image("img")]))

    built = controller._curated_combination("img", "waving")

    assert built is not None
    assert built[1]["steps"] == 4


def test_edit_default_opens_the_window_that_settles_each_animation(combine, monkeypatch, qtbot):
    """His ask: reachable from inside the app, so the window he judges an
    animation's settings in needs no launcher of its own."""
    controller, _host = combine()
    made = QWidget()
    qtbot.addWidget(made)
    monkeypatch.setattr(module, "the_animation_window", lambda: made)

    controller.panel.animation_settings_requested.emit()

    assert made.isVisible()


def test_a_second_press_brings_that_window_back_rather_than_another(combine, monkeypatch, qtbot):
    controller, _host = combine()
    built = []

    def one_more():
        made = QWidget()
        qtbot.addWidget(made)
        built.append(made)
        return made

    monkeypatch.setattr(module, "the_animation_window", one_more)

    controller.panel.animation_settings_requested.emit()
    controller.panel.animation_settings_requested.emit()

    assert len(built) == 1


def test_the_button_on_the_real_panel_reaches_the_controller(qtbot, monkeypatch):
    """Every other test here drives a recorder in the panel's place, so the one
    thing it cannot answer is whether the button he presses is wired at all."""
    made = QWidget()
    qtbot.addWidget(made)
    monkeypatch.setattr(module, "the_animation_window", lambda: made)
    parent = QWidget()
    qtbot.addWidget(parent)
    controller = CombineController(
        FakeHost(), parent=parent, db=FakeDB(), jobs=FakeReroll(), client=object(),
        info_tabs_of=lambda: FakeTabs(), slideshows=FakeSlideshows())

    controller.panel._defaults_btn.click()

    assert made.isVisible()


def test_an_image_browsed_from_outside_runs_the_settings_on_that_file(combine, tmp_path):
    photo = square(tmp_path, "red")
    controller, _host = combine(db=FakeDB([_video("clip")]))
    controller.panel.image_slot.set_item(photo)
    controller.panel.video_slot.set_item("clip")

    workflow, params, video_row, image_row = controller._combined_params(photo, "clip")

    assert params["input_image"] == photo
    assert image_row is None
    assert controller._accepts_image(photo) is True
    assert controller._accepts_image(str(tmp_path / "nowhere.png")) is False
    assert controller._state_of(photo) == ""
    assert controller._slot_preview(photo) == (photo, None)
    assert controller.panel.name_of(photo) == "made-red.png"


def test_browsing_an_image_puts_the_file_in_the_image_zone(combine, monkeypatch, tmp_path):
    photo = square(tmp_path, "blue")
    monkeypatch.setattr(file_pick.QFileDialog, "getOpenFileName",
                        lambda *_args: (photo, ""))
    controller, _host = combine()

    controller.panel.browse_image()

    assert controller.panel.image_slot.current_id() == photo


def test_a_picked_act_runs_its_pinned_settings_on_a_browsed_image(combine, tmp_path, monkeypatch):
    photo = square(tmp_path, "green")
    monkeypatch.setattr(act_settings, "pinned_settings",
                        lambda category, intent: {"workflow": VIDEO_WORKFLOW,
                                                  "params": {"steps": 7}})
    controller, _host = combine(db=FakeDB([_video("clip")]))

    built = controller._curated_combination(photo, "gamma")

    assert built is not None
    workflow, params = built
    assert (params["input_image"], params["steps"]) == (photo, 7)
