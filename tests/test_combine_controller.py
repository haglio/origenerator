"""Combine, driven with no gallery around it.

The whole act used to be reachable only by building the app's central widget:
which recipe a picked act resolves to, what a stand-in row does while the model
thinks, which seed a press re-rolls rather than reproduce a run, and what a
spoken "genau it" refuses. Here the host is a handful of recorded calls and the
recipe match answers inline.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QWidget

from origenerator import recipe_match
from origenerator.gui import combine_controller as module
from origenerator.gui.combine_controller import ALREADY_GENAUD, CombineController
from origenerator.gui.reroll_prompt import REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO

IMAGE_WORKFLOW = "sdxl_t2i"
VIDEO_WORKFLOW = "wan22_i2v"


class FakePanel:
    """The combine panel reduced to what the controller drives."""

    class _Slot:
        def __init__(self):
            self.item = None

        def current_id(self):
            return self.item

        def set_item(self, prompt_id):
            self.item = prompt_id

    def __init__(self, accepts_image, accepts_video, preview):
        self.accepts_image = accepts_image
        self.accepts_video = accepts_video
        self.preview = preview
        self.image_slot = self._Slot()
        self.video_slot = self._Slot()
        self.intent = recipe_match.PLAYERS
        self.category = ""
        self.available = None
        self.visible = None
        self.lit_for = []
        self.cleared = 0
        self.generate_requested = _Signal()
        self.category_requested = _Signal()
        self.open_requested = _Signal()
        self.open_category_requested = _Signal()
        self.intent_changed = _Signal()

    def selected_intent(self):
        return self.intent

    def selected_category(self):
        return self.category

    def set_intent(self, intent):
        self.intent = intent

    def set_category(self, category):
        self.category = category

    def set_available_categories(self, categories):
        self.available = list(categories)

    def setVisible(self, visible):
        self.visible = visible

    def show_drop_candidates(self, prompt_id):
        self.lit_for.append(prompt_id)

    def clear_drop_candidates(self):
        self.cleared += 1


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


class FakeReroll:
    def __init__(self, launches="new-run"):
        self.prepared = []
        self.from_image = []
        self.launches = launches

    def start_prepared(self, key, workflow, params):
        self.prepared.append((key, workflow.name, dict(params)))
        return self.launches

    def start_reroll_from_image(self, key, image_row, image_workflow, workflow, params):
        self.from_image.append((key, image_row["prompt_id"]))
        return True


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: dict(row) for row in rows}
        self.recipe_sources = []
        self.requested = []
        self.exported = []

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def list_generations(self):
        return [dict(row) for row in self.rows.values()]

    def set_recipe_source(self, prompt_id, *, category="", video_prompt_id=None):
        self.recipe_sources.append((prompt_id, category, video_prompt_id))

    def mark_genau_requested(self, prompt_id):
        self.requested.append(prompt_id)

    def mark_genau_exported(self, prompt_id):
        self.exported.append(prompt_id)


class FakeShows:
    def __init__(self, showing=None):
        self.showing = showing
        self.runs_said = []

    def note_voice_run(self, prompt_id, message):
        self.runs_said.append((prompt_id, message))


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

    def set_recipe_source(self, category, video_id):
        self.source = (category, video_id)

    def show_combination(self, still, looping):
        self.combination = (still, looping)


class FakeHost:
    """A gallery reduced to what a combine asks of one."""

    def __init__(self, *, rows=(), reproduces=False, seed_answer=None):
        self.rows = list(rows)
        self.reproduces = reproduces
        self.seed_answer = seed_answer
        self.queue_redraws = 0
        self.revealed = []
        self.told = []
        self.asked = []
        self.off_thread_calls = []

    def image_rows(self):
        return self.rows

    def animated_preview(self, row):
        return f"{row['prompt_id']}.webp"

    def folder_key_of(self, row):
        return f"folder-of-{row['prompt_id']}"

    def folder_key_for(self, workflow_name, params, workflow_version=None):
        return f"folder-for-{workflow_name}-{workflow_version}"

    def would_reproduce_a_completed_run(self, workflow, params):
        return self.reproduces

    def off_thread(self, work, done):
        self.off_thread_calls.append((work, done))
        done(work())

    def queue_changed(self):
        self.queue_redraws += 1

    def reveal_launch(self, key):
        self.revealed.append(key)

    def ask_which_seed(self, workflow, *, can_reroll_image):
        self.asked.append(can_reroll_image)
        return self.seed_answer

    def tell(self, title, message):
        self.told.append((title, message))


def _image(prompt_id="img", *, prompt="a doll on a couch", files=("one.png",),
           source="generated"):
    return {
        "prompt_id": prompt_id,
        "workflow_name": IMAGE_WORKFLOW,
        "positive_prompt": prompt,
        "status": "completed",
        "source": source,
        "thumbnail_path": f"{prompt_id}-thumb.png",
        "output_files": json.dumps([{"filename": name} for name in files]),
        "params_json": "{}",
    }


def _video(prompt_id="clip", *, workflow_name=VIDEO_WORKFLOW, status="completed",
           requested=None, exported=None, source_image=None, files=None):
    return {
        "prompt_id": prompt_id,
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
    a panel and the recipe match answering inline."""
    monkeypatch.setattr(module, "CombinePanel", FakePanel)
    built = []

    def build(host=None, *, db=None, reroll=None, client=object(), shows=None,
              tabs=None):
        host = host or FakeHost()
        parent = QWidget()
        qtbot.addWidget(parent)
        controller = CombineController(
            host, parent=parent, db=db or FakeDB(), reroll=reroll or FakeReroll(),
            client=client, info_tabs_of=lambda: tabs or FakeTabs(),
            shows=shows or FakeShows())
        # The wait between a press and a real job is what the stand-in row is
        # for; running it straight through is what lets a test press and look.
        controller._after_painting = lambda work: work()
        built.append((parent, controller))
        return controller, host
    yield build


# --- what the slots take ----------------------------------------------------


def test_the_image_slot_takes_a_picture_with_a_file_to_seed_from(combine):
    # Not merely anything that produced a file: a video's clip would satisfy
    # that and cannot be a start frame.
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    assert controller._accepts_image("img") is True
    assert controller._accepts_image("clip") is False


def test_the_video_slot_takes_only_a_recipe_this_app_can_rebuild(combine):
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


def test_the_session_keeps_both_slots_the_lane_and_the_act(combine):
    # None of the four is recoverable from the others: an act says nothing about
    # which lane answers it.
    controller, _host = combine()
    controller.panel.image_slot.set_item("img")
    controller.panel.video_slot.set_item("clip")
    controller.panel.set_intent(recipe_match.GENAU)
    controller.panel.set_category("waving")

    assert controller.selection() == {
        "image": "img", "video": "clip",
        "intent": recipe_match.GENAU, "category": "waving"}


def test_a_restore_puts_the_lane_in_before_the_act(combine):
    # The lane decides which acts are answerable, and set_category refuses one
    # that is greyed out under it.
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]))

    controller.restore({"image": "img", "video": "clip",
                        "intent": recipe_match.GENAU, "category": "waving"})

    assert controller.panel.intent == recipe_match.GENAU
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
    assert row.status == "queued" and row.starting is True
    assert row.recipe_thumbnail == "clip-thumb.png"
    assert host.queue_redraws == 1


def test_a_picked_act_names_itself_rather_than_showing_a_video(combine):
    controller, _host = combine(db=FakeDB([_image("img")]))

    controller._show_launching("img", category="waving")

    (row,) = controller.launching_rows()
    assert row.recipe_category == "waving"
    assert row.recipe_thumbnail is None


def test_the_stand_in_row_comes_off_however_the_launch_ends(combine):
    controller, host = combine(db=FakeDB([_image("img")]))
    key = controller._show_launching("img", category="waving")

    controller._drop_launching(key)
    controller._drop_launching(key)  # twice costs nothing

    assert controller.launching_rows() == []
    assert host.queue_redraws == 2


# --- launching a dropped pair ----------------------------------------------


def test_a_dropped_pair_runs_the_videos_recipe_on_the_picture(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params",
                        lambda video_row, image_row, wf: {"seed": 7, "input_image": "one.png"})
    reroll = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert [name for _key, name, _params in reroll.prepared] == [VIDEO_WORKFLOW]
    assert host.revealed == ["folder-of-clip"]


def test_a_press_that_would_reproduce_a_run_asks_which_seed(combine, monkeypatch):
    # A pinned seed can re-create a byte-identical past generation, and spending
    # a slot on that is the one thing the ask exists to prevent.
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params",
                        lambda v, i, wf: {"seed": 7})
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: {"seed": 99})
    reroll = FakeReroll()
    controller, host = combine(
        FakeHost(reproduces=True, seed_answer=REROLL_VIDEO),
        db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert host.asked == [True]  # the dropped picture is itself re-buildable
    assert reroll.prepared[0][2] == {"seed": 99}


def test_saying_no_to_that_question_launches_nothing(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params", lambda v, i, wf: {"seed": 7})
    reroll = FakeReroll()
    controller, _host = combine(
        FakeHost(reproduces=True, seed_answer=None),
        db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert reroll.prepared == []


def test_re_drawing_the_frame_launches_the_picture_first(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params", lambda v, i, wf: {"seed": 7})
    reroll = FakeReroll()
    controller, host = combine(
        FakeHost(reproduces=True, seed_answer=REROLL_IMAGE),
        db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert [pid for _key, pid in reroll.from_image] == ["img"]
    assert reroll.prepared == []
    assert host.revealed == ["folder-of-clip"]


def test_both_seeds_re_rolled_re_draws_the_frame_with_the_new_video_seed(
        combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "combined_params", lambda v, i, wf: {"seed": 7})
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: {"seed": 99})
    reroll = FakeReroll()
    controller, _host = combine(
        FakeHost(reproduces=True, seed_answer=REROLL_BOTH),
        db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert reroll.from_image != []


def test_an_unrebuildable_pair_launches_nothing(combine, monkeypatch):
    monkeypatch.delitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, raising=False)
    reroll = FakeReroll()
    controller, _host = combine(db=FakeDB([_image("img"), _video("clip")]), reroll=reroll)

    controller._generate_combination("img", "clip")

    assert reroll.prepared == []


# --- finding the recipe an act names ----------------------------------------


def test_a_curated_recipe_outranks_the_mining(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.recipe_match, "curated_recipe",
                        lambda category, intent: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "curated_params",
                        lambda spec, row, wf: {"seed": 3})
    mined = []
    monkeypatch.setattr(module.recipe_match, "smart_recipe",
                        lambda *a, **k: mined.append(1))
    reroll = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img")]), reroll=reroll)

    controller.generate_category("img", "waving")

    assert mined == []  # never asked: the overlay had a pinned recipe
    assert reroll.prepared[0][0] == f"folder-for-{VIDEO_WORKFLOW}-3"
    assert host.revealed == [f"folder-for-{VIDEO_WORKFLOW}-3"]


def test_an_act_with_no_recipe_under_it_says_so_and_launches_nothing(combine,
                                                                     monkeypatch):
    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    monkeypatch.setattr(module.recipe_match, "smart_recipe", lambda *a, **k: None)
    monkeypatch.setattr(module.recipe_match, "best_recipe", lambda *a, **k: None)
    reroll = FakeReroll()
    controller, host = combine(db=FakeDB([_image("img")]), reroll=reroll)

    controller.generate_category("img", "waving")

    assert reroll.prepared == []
    assert host.told == [("No recipe yet",
                          "No past “waving” video to base a recipe on yet — make "
                          "one first, or drop a specific video instead.")]


def test_that_hint_lands_in_the_shows_corner_rather_than_a_dialog(combine,
                                                                  monkeypatch):
    # A dialog thrown over a picture someone is talking to is the one place this
    # must never appear.
    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    monkeypatch.setattr(module.recipe_match, "smart_recipe", lambda *a, **k: None)
    monkeypatch.setattr(module.recipe_match, "best_recipe", lambda *a, **k: None)
    shows = FakeShows(showing=object())
    controller, host = combine(db=FakeDB([_image("img")]), shows=shows)

    controller.generate_category("img", "waving", recipe_match.GENAU)

    assert host.told == []
    assert shows.runs_said == [
        (None, "🎤 no past looping “waving” clip to base a recipe on yet")]


def test_the_mined_recipe_is_matched_against_its_start_frames_scene(combine,
                                                                    monkeypatch):
    # Where the situation to match lives is the video's start frame, not the
    # video's own prompt.
    asked = {}

    def smart(category, scene, candidates, **kwargs):
        asked["scenes"] = [c["start_scene"] for c in candidates]

    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    monkeypatch.setattr(module.recipe_match, "smart_recipe", smart)
    monkeypatch.setattr(module.recipe_match, "best_recipe", lambda *a, **k: None)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "find_source_image_id",
                        lambda row, rows: "img")
    image = _image("img", prompt="a doll on a couch")
    controller, _host = combine(
        FakeHost(rows=[image]), db=FakeDB([image, _video("clip")]))

    controller.generate_category("img", "waving")

    assert asked["scenes"] == ["a doll on a couch"]


def test_the_stand_in_row_goes_whatever_the_match_answers(combine, monkeypatch):
    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    monkeypatch.setattr(module.recipe_match, "smart_recipe", lambda *a, **k: None)
    monkeypatch.setattr(module.recipe_match, "best_recipe", lambda *a, **k: None)
    controller, _host = combine(db=FakeDB([_image("img")]))

    controller.panel.category_requested.emit("img", "waving", recipe_match.PLAYERS)

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

    controller._open_combination("img", "clip", "waving")

    assert tabs.opened == [(VIDEO_WORKFLOW, {"seed": 7})]
    assert panel.source == ("waving", "clip")
    assert panel.combination == ("img-thumb.png", "clip.webp")


def test_a_curated_act_opened_shows_the_frame_alone(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.recipe_match, "curated_recipe",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "curated_params", lambda s, r, wf: {"seed": 3})
    monkeypatch.setattr(module.gallery, "resolve_preview", lambda row, out: None)
    panel = FakeConfigPanel()
    controller, _host = combine(db=FakeDB([_image("img")]), tabs=FakeTabs(panel))

    controller._open_category("img", "waving")

    assert panel.combination == ("img-thumb.png", None)


# --- the spoken "genau it" ---------------------------------------------------


def test_genau_it_reads_the_act_off_the_pictures_own_prompt(combine, monkeypatch):
    monkeypatch.setattr(module.recipe_match, "category_for_prompt",
                        lambda prompt: "waving")
    monkeypatch.setattr(module.recipe_match, "available_categories",
                        lambda rows, intent: ["waving"])
    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    monkeypatch.setattr(module.recipe_match, "smart_recipe", lambda *a, **k: None)
    monkeypatch.setattr(module.recipe_match, "best_recipe", lambda *a, **k: None)
    controller, _host = combine(db=FakeDB([_image("img")]))

    prompt_id, message = controller.genau_it("img")

    assert prompt_id == "img"
    assert message == "🎤 animating as a “waving” loop"


def test_genau_it_declines_a_video(combine):
    controller, _host = combine(db=FakeDB([_video("clip")]))

    assert controller.genau_it("clip") == (
        None, "🎤 only a picture can become a Genau clip")


def test_genau_it_says_so_rather_than_guessing_an_unreadable_prompt(combine,
                                                                    monkeypatch):
    monkeypatch.setattr(module.recipe_match, "category_for_prompt", lambda p: None)
    controller, _host = combine(db=FakeDB([_image("img")]))

    _prompt_id, message = controller.genau_it("img")

    assert message == (
        "🎤 this prompt doesn't say what's happening — no act to animate")


def test_a_second_genau_it_over_a_picture_with_a_clip_coming_is_refused(combine,
                                                                        monkeypatch):
    # Saying it twice is what someone does when the first time appeared to do
    # nothing, and it usually did: the clip waits its turn in the line and the
    # picture on screen doesn't change.
    monkeypatch.setattr(module.gallery, "find_source_image_id",
                        lambda row, rows: "img")
    db = FakeDB([_image("img"), _video("clip", status="running", requested="now")])
    controller, _host = combine(db=db)

    assert controller.genau_it("img") == (None, ALREADY_GENAUD)


def test_a_run_that_errored_made_no_clip_and_does_not_stand_in_for_one(combine,
                                                                       monkeypatch):
    monkeypatch.setattr(module.gallery, "find_source_image_id",
                        lambda row, rows: "img")
    monkeypatch.setattr(module.recipe_match, "category_for_prompt", lambda p: None)
    db = FakeDB([_image("img"),
                 _video("clip", status="error", requested="now", files=[])])
    controller, _host = combine(db=db)

    # It gets as far as reading the act, which means the picture was not refused.
    assert controller.genau_it("img")[1] != ALREADY_GENAUD


def test_one_said_while_the_recipe_is_still_being_chosen_is_refused_too(combine,
                                                                        monkeypatch):
    # The mined tier asks a local model that thinks for several seconds, which is
    # exactly the silence a second command is said into.
    monkeypatch.setattr(module.recipe_match, "curated_recipe", lambda c, i: None)
    said = []

    def slow_match(work, done):
        said.append(controller.genau_it("img"))  # said into the wait

    controller, _host = combine(FakeHost(), db=FakeDB([_image("img")]))
    controller._host.off_thread = slow_match

    controller.generate_category("img", "waving", recipe_match.GENAU, send=True)

    assert said == [(None, ALREADY_GENAUD)]


def test_a_spoken_launch_is_stamped_to_hand_its_clip_on(combine, monkeypatch):
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.recipe_match, "curated_recipe",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "curated_params", lambda s, r, wf: {"seed": 3})
    db = FakeDB([_image("img")])
    controller, _host = combine(db=db)

    controller.generate_category("img", "waving", recipe_match.GENAU, send=True)

    assert db.requested == ["new-run"]


def test_a_pressed_generate_leaves_its_clip_in_the_gallery(combine, monkeypatch):
    # Someone at the keyboard can look at it first; someone talking to a
    # fullscreen picture cannot.
    workflow = FakeWorkflow()
    monkeypatch.setattr(module.recipe_match, "curated_recipe",
                        lambda c, i: {"workflow": VIDEO_WORKFLOW})
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, VIDEO_WORKFLOW, workflow)
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    monkeypatch.setattr(module.gallery, "curated_params", lambda s, r, wf: {"seed": 3})
    db = FakeDB([_image("img")])
    controller, _host = combine(db=db)

    controller.generate_category("img", "waving", recipe_match.GENAU)

    assert db.requested == []


def test_a_spoken_clip_hands_itself_on_when_it_lands(combine, monkeypatch, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "clip.mp4").write_bytes(b"pixels")
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output)
    sent = []
    monkeypatch.setattr(module.evolver_export, "export_video",
                        lambda path, destination: sent.append(path.name))
    db = FakeDB()
    controller, _host = combine(db=db)

    controller.send_to_genau_if_requested(_video("clip", requested="now"))

    assert sent == ["clip.mp4"]
    assert db.exported == ["clip"]


def test_a_clip_already_handed_on_is_not_sent_twice(combine, monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(module.evolver_export, "export_video",
                        lambda path, destination: sent.append(path))
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
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output)

    def boom(path, destination):
        raise OSError("the inbox is not there")

    monkeypatch.setattr(module.evolver_export, "export_video", boom)
    db = FakeDB()
    controller, _host = combine(db=db)

    controller.send_to_genau_if_requested(_video("clip", requested="now"))

    assert db.exported == []


# --- which acts are pickable at all -----------------------------------------


def test_an_act_with_no_video_under_it_is_greyed_out(combine, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_image_conditioned",
                        lambda name: name == VIDEO_WORKFLOW)
    monkeypatch.setattr(module.recipe_match, "available_categories",
                        lambda rows, intent: [r["prompt_id"] for r in rows])
    controller, _host = combine()

    controller.offer_the_acts([_video("clip"), _image("img"),
                               _video("half", status="running")])

    assert controller.panel.available == ["clip"]


def test_switching_lanes_re_asks_which_acts_are_answerable(combine, monkeypatch):
    # An act with plenty of long-form video under it may have no loop at all.
    monkeypatch.setattr(module.gallery, "is_image_conditioned", lambda name: True)
    seen = []
    monkeypatch.setattr(module.recipe_match, "available_categories",
                        lambda rows, intent: seen.append(intent) or [])
    controller, _host = combine(db=FakeDB([_video("clip")]))
    controller.panel.set_intent(recipe_match.GENAU)

    controller.panel.intent_changed.emit(recipe_match.GENAU)

    assert seen == [recipe_match.GENAU]


def test_a_drag_lights_the_slot_it_fits(combine):
    controller, _host = combine()

    controller.drag_started("img")
    controller.drag_ended()

    assert controller.panel.lit_for == ["img"]
    assert controller.panel.cleared == 1
