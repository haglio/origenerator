from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest
from funestra.console import (
    OSR2_PARKED,
)
from PyQt6.QtCore import (
    QPoint,
    QRect,
)

from origenerator import (
    act_settings,
    config,
    gallery,
    motion_engine,
)
from origenerator.animate_command import AnimateRequest
from origenerator.box_breaks import BOX_BREAK
from origenerator.config import (
    EVOLVER_INBOX_DIR,
    GENAU_SOURCE,
)
from origenerator.db import Database
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
)
from origenerator.gui import (
    combine_controller,
    omnipause,
    voice_router,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.notice_overlay import NOTICE, WARNING
from origenerator.gui.slideshow_pace import DEFAULT_S
from origenerator.voice.commands import SurfaceCommand
from origenerator.voice.commands import match_voice_command as match
from origenerator.voice.dictation import RequestDictation
from origenerator.voice.listener import CommandAndRequestListener
from origenerator.workflows import detail_parts
from origenerator.workflows.detail_parts import DEFAULT_FIX_DENOISE
from tests.conftest import FakeHearing
from tests.gallery_view_support import (
    _REROLL_HISTORY,
    _SDXL,
    _click_off,
    _double_click_slideshow,
    _enhanceable_db,
    _finish_reroll,
    _genau_db,
    _genau_view,
    _on_screen,
    _requesting_view,
    _reroll_client,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _set_enhance,
    _will_move_on,
)
from tests.marked_words import words
from tests.text_readers import clip_reader

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- the microphone, which its button alone opens and closes ----------------


def test_words_that_are_no_command_leave_a_running_auto_generate_as_it_was(
        qtbot, tmp_path, monkeypatch):
    # Neither a command nor a request, a sentence does nothing while Auto-Generate
    # runs, exactly as when it does not: its prompt and its folder stay as they were.
    hearing = FakeHearing("make it a dog")
    monkeypatch.setattr(voice_router, "CommandAndRequestListener",
                        partial(CommandAndRequestListener, hearing=hearing))
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._bank.mic.setChecked(True)
    view._toggle_auto(True)
    prompt = view._live_jobs[key].params["positive_prompt"]

    hearing.hear()
    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    assert list(view._live_jobs) == [key]
    assert view._live_jobs[key].params["positive_prompt"] == prompt
    assert words(view._voice.status) == "heard: “make it a dog”"


def test_auto_generate_ending_leaves_an_open_mic_open(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)

    view._toggle_auto(True)
    view._toggle_auto(False)

    assert view._voice.listener.commands_on    # the mic is the button's, still open


def test_the_mic_button_is_the_only_thing_that_opens_the_mic(qtbot, tmp_path):
    # It used to come on with Auto-Generate and again with a fullscreen slideshow,
    # which made "is it listening?" a thing to work out rather than to look at.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_auto(True)
    assert not view._voice.listener.commands_on
    view._toggle_auto(False)

    view._bank.mic.setChecked(True)
    assert view._voice.listener.commands_on

    view._bank.mic.setChecked(False)
    assert not view._voice.listener.commands_on


def test_voice_status_caption_shows_listening_and_what_was_heard(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._bank.mic.setChecked(True)
    assert not view._voice.status.isHidden()
    assert "Listening" in words(view._voice.status)

    view._voice.listener.heard.emit("no hat")
    assert "no hat" in words(view._voice.status)

    view._bank.mic.setChecked(False)
    assert view._voice.status.isHidden()


def test_the_captions_section_is_up_only_while_the_caption_is(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.show()
    section = view._voice.status.parentWidget()
    assert not section.isVisible()

    view._bank.mic.setChecked(True)
    assert section.isVisible()

    view._bank.mic.setChecked(False)
    assert not section.isVisible()


def test_what_was_heard_gives_way_after_a_few_seconds(qtbot, tmp_path):
    """The caption holds an utterance for a beat and then reverts — to "Listening"
    while the mic is still open, and to nothing at all once it is closed."""
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)
    view._voice.listener.heard.emit("no hat")

    view._voice._flash_timer.timeout.emit()  # the beat is up

    assert words(view._voice.status) == "Listening…"
    assert not view._voice.status.isHidden()

    view._bank.mic.setChecked(False)
    view._voice._show("nothing here to enhance", transient=True)

    view._voice._flash_timer.timeout.emit()

    assert view._voice.status.isHidden()  # no mic open, so nothing to say


def test_the_caption_spells_a_command_the_way_the_app_knows_it(qtbot, tmp_path):
    # Whisper renders a command several ways and the matcher answers to all of
    # them, so printing the transcription showed a misspelling of a command that
    # was understood perfectly well — "enhanced it" over a caption that then went
    # and enhanced the image.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)

    view._voice.listener.heard.emit("Enhanced it.")
    assert "enhance it" in words(view._voice.status)
    assert "Enhanced" not in words(view._voice.status)

    view._voice.listener.heard.emit("give her a wider hat")  # no command: as it was heard
    assert "give her a wider hat" in words(view._voice.status)


def test_voice_status_caption_keeps_clear_of_the_header_buttons(qtbot, tmp_path):
    # It used to float centered over the top of the view, landing squarely on the
    # header toolbar the user was trying to click. It now takes its own room at
    # the top of the left pane, so it covers nothing however long the message.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    _on_screen(qtbot, view, 1200, 800)
    _select_first_leaf(view)

    view._bank.mic.setChecked(True)
    view._voice.listener.heard.emit("give her a much longer caption than the idle one")
    qtbot.wait(1)  # let the layout settle around the grown caption

    caption = QRect(view._voice.status.mapTo(view, QPoint(0, 0)), view._voice.status.size())
    for button in (view._bank.back, view._bank.forward, view._bank.undo, view._bank.delete):
        assert not caption.intersects(
            QRect(button.mapTo(view, QPoint(0, 0)), button.size())
        )
    assert caption.bottomLeft().y() <= view._search.field.mapTo(view, QPoint(0, 0)).y()


# --- standalone enhance: the folder button, the selection action, the queue ---


class _VoiceSurface:
    """A slideshow standing in for the one being spoken over."""

    def __init__(self, prompt_id, *, favoritable=True):
        self._prompt_id = prompt_id
        self._favoritable = favoritable
        self.noted = None
        self.enhancing = {}
        self.said = None    # what a spoken command was answered with
        self.steps = []     # the transport moves it was asked for, in order
        self.culled = 0
        self.favorited = 0
        self.locked = False
        self.queued = []     # what the poll last fed its corner queue
        self.in_flight = set()
        self.shown = self    # and where it is seen, whose corner shows the queue

    def is_showing(self):
        return True

    @property
    def locked_on(self):
        return self._prompt_id if self.locked else None

    def back_to_what_was_said_over(self, said_at):
        return self._prompt_id

    def note_voice_run(self, prompt_id, message, *, kind):
        self.noted = (prompt_id, message, kind)

    def note_enhancing(self, statuses, frames=None):
        self.enhancing = statuses

    def note_voice_command(self, message, *, kind=NOTICE):
        self.said = message

    def slideshow_step(self, delta):
        self.steps.append(delta)

    def cull(self):
        self.culled += 1

    def favorite(self):
        if not self._favoritable:
            return False
        self.favorited += 1
        return True

    def set_locked(self, locked):
        if locked == self.locked:
            return False
        self.locked = locked
        return True

    # The gallery's poll feeds every open slideshow its queue and what is in flight,
    # and it fires while these tests run: a stand-in that answered none of that
    # blew up inside the Qt event loop, on whichever test the timer happened to
    # land in.
    def set_queue(self, items, foreign_queued=0):
        self.queued = list(items)

    def holds(self, prompt_id):
        return False

    def note_in_flight(self, prompt_ids):
        self.in_flight = set(prompt_ids)

    # A real slideshow is a FunestraSlideshow, which answers all of these, and the
    # view calls them without asking first. A stand-in that answered fewer would
    # have to be guarded against in production, which is the same as saying the
    # guards would exist for this class alone.
    def state(self):
        return None

    def toggle_favorites_filter(self):
        self.favorites_filter = not getattr(self, "favorites_filter", False)

    @property
    def hud_favorites_filter(self):
        return getattr(self, "favorites_filter", False)

    def set_paused(self, paused):
        self.paused = paused

    def adopt_hud(self):
        self.adopted = True


def test_the_poll_runs_over_a_slideshow_being_spoken_to(qtbot, tmp_path):
    # The 1.5s poll feeds every open slideshow, and it lands mid-test wherever it
    # lands: a stand-in that had drifted out of step with what a slideshow answers
    # raised inside the Qt event loop, failing whichever test it fired in rather
    # than the one that let it drift.
    view = GalleryView(_enhanceable_db(tmp_path, count=1))
    qtbot.addWidget(view)
    view.refresh()
    view._slideshows._slideshow = _VoiceSurface("g0")

    view._update_queue()

    assert view._slideshows.showing.queued == []


def test_a_slideshow_opening_and_closing_leaves_the_mic_as_it_found_it(
        qtbot, tmp_path, monkeypatch):
    # It used to arm the mic and disarm it again, which is what left "start
    # slideshow" unhearable in the one state it is for.
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)

    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._voice.listener.commands_on

    view._slideshows.showing.close()
    assert view._slideshows.showing is None
    assert view._voice.listener.commands_on  # still on, because the button still is


def test_a_closed_gallery_leaves_the_mic_shut_and_its_button_as_it_was(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._bank.mic.setChecked(True)

    view.close()

    assert not view._voice.listener.commands_on
    assert view._bank.mic.isChecked()


def test_a_slideshow_with_the_mic_off_hears_nothing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    slideshow = _double_click_slideshow(view, qtbot)

    assert not view._voice.listener.commands_on
    slideshow.close()


def _fix_slideshow(qtbot, tmp_path, monkeypatch, *detectors):
    """A gallery playing one image fullscreen with the mic on, and exactly these
    detectors installed — the state every spoken fix is said into."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: list(detectors))
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    return view


def test_a_spoken_fix_launches_the_targeted_pass_on_the_slide(
        qtbot, tmp_path, monkeypatch):
    view = _fix_slideshow(qtbot, tmp_path, monkeypatch, "teeth_yolov8n.pt")

    assert view._voice.listener.speak_command("Fix her teeth.") is not None

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_detail_fixes"] == {"teeth": DEFAULT_FIX_DENOISE}
    assert "fixing teeth" in words(view._slideshows.showing.shown._note)
    assert view._slideshows.showing.hud_item_note == "Enhancement queued"


def test_a_spoken_fix_of_two_parts_runs_a_pass_for_each(
        qtbot, tmp_path, monkeypatch):
    # Two bad parts in one image is one command, and one run that fixes both.
    view = _fix_slideshow(qtbot, tmp_path, monkeypatch,
                          "teeth_yolov8n.pt", "hand_yolov8s.pt")

    view._voice.listener.speak_command("fix hands and teeth")

    (job,) = view._live_jobs.values()
    assert job.params["enhance_detail_fixes"] == {
        "hands": DEFAULT_FIX_DENOISE, "teeth": DEFAULT_FIX_DENOISE}
    assert "fixing hands & teeth" in words(view._slideshows.showing.shown._note)


def test_fix_all_goes_over_every_part_something_can_find(
        qtbot, tmp_path, monkeypatch):
    # The whole table in a breath — minus the parts nothing installed can find,
    # which the caption leaves out rather than claiming a pass that can't run.
    view = _fix_slideshow(qtbot, tmp_path, monkeypatch,
                          "teeth_yolov8n.pt", "hand_yolov8s.pt")

    view._voice.listener.speak_command("fix everything")

    (job,) = view._live_jobs.values()
    assert job.params["enhance_detail_fixes"] == {
        "hands": DEFAULT_FIX_DENOISE, "teeth": DEFAULT_FIX_DENOISE}
    assert "fixing hands & teeth" in words(view._slideshows.showing.shown._note)


def test_a_spoken_fix_with_nothing_to_find_it_answers_on_the_slideshow(
        qtbot, tmp_path, monkeypatch):
    view = _fix_slideshow(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak_command("fix teeth")

    assert view._live_jobs == {}
    assert "no teeth detector" in words(view._slideshows.showing.shown._note)


# --- spoken slideshow control: start it, pause it, close it -----------------


def _voiceable(qtbot, tmp_path, monkeypatch):
    """A gallery on a playable folder with the microphone switched on."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._bank.mic.setChecked(True)
    return view


def test_start_slideshow_opens_one_at_the_standard_pace(qtbot, tmp_path, monkeypatch):
    view = _voiceable(qtbot, tmp_path, monkeypatch)
    assert view._slideshows.showing is None

    view._voice.listener.speak_command("start slideshow")

    assert view._slideshows.showing is not None
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing.dwell_s == DEFAULT_S
    assert _will_move_on(view._slideshows.showing)
    view._slideshows.showing.close()


def test_open_slideshow_says_the_same_thing(qtbot, tmp_path, monkeypatch):
    view = _voiceable(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak_command("open slideshow")

    assert view._slideshows.showing is not None
    qtbot.addWidget(view._slideshows.showing.shown)
    view._slideshows.showing.close()


def test_a_double_clicked_images_slideshow_opens_at_the_clip_seconds_set(
        qtbot, tmp_path, monkeypatch):
    view = _voiceable(qtbot, tmp_path, monkeypatch)
    view._pace.set_seconds(7)

    slideshow = _double_click_slideshow(view, qtbot)

    assert slideshow.dwell_s == 7
    assert _will_move_on(slideshow)
    slideshow.close()


def test_pause_slideshow_pauses_the_whole_room_as_esc_does_and_play_slideshow_plays_it(
        qtbot, tmp_path, monkeypatch):
    view = _voiceable(qtbot, tmp_path, monkeypatch)
    view._voice.listener.speak_command("start slideshow")
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)

    view._voice.listener.speak_command("pause slideshow")
    assert omnipause.frozen()
    assert slideshow.shown._paused
    assert view._slideshows.showing is slideshow  # paused, not closed
    assert slideshow.dwell_s == DEFAULT_S

    view._voice.listener.speak_command("play slideshow")
    assert not omnipause.frozen()
    assert not slideshow.shown._paused
    slideshow.close()


@pytest.mark.parametrize("said", ["stop slideshow", "end slideshow",
                                  "close slideshow"])
def test_stopping_the_slideshow_closes_it(qtbot, tmp_path, monkeypatch, said):
    view = _voiceable(qtbot, tmp_path, monkeypatch)
    view._voice.listener.speak_command("start slideshow")
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow.shown.show()

    view._voice.listener.speak_command(said)

    assert not slideshow.shown.isVisible()
    assert view._slideshows.showing is None


def test_a_slideshow_command_with_no_slideshow_up_answers_in_the_gallery(
        qtbot, tmp_path, monkeypatch):
    # There is no note to write on, so the caption that carries every other
    # voice answer says it instead.
    view = _voiceable(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak_command("close slideshow")

    assert "no slideshow" in words(view._voice.status)


def test_a_spoken_fix_with_no_slideshow_up_says_so_rather_than_vanishing(
        qtbot, tmp_path, monkeypatch):
    # The mic hears commands with nothing on screen too, so "fix teeth" is
    # claimed there — it must not disappear silently.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["teeth_yolov8n.pt"])
    view = _voiceable(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak_command("fix teeth")

    assert view._live_jobs == {}
    assert "image on screen" in words(view._voice.status)


def test_start_slideshow_is_heard_with_no_slideshow_and_no_auto_generate(qtbot, tmp_path,
                                                          monkeypatch):
    # The state the command is for: nothing playing, nothing generating, mic on.
    view = _voiceable(qtbot, tmp_path, monkeypatch)
    assert view._slideshows.showing is None

    view._voice.listener.speak_command("start slideshow")

    assert view._slideshows.showing is not None
    qtbot.addWidget(view._slideshows.showing.shown)
    view._slideshows.showing.close()


# --- spoken requests: "Request … over" over what's on screen -----------------


def _speak_request(view, qtbot, *utterances):
    """Say a request and wait for the app to have answered it — the revision is
    worked out off the UI thread, so the answer arrives a hop later.

    Answered means the promise the slideshow holds while it works is taken down,
    which only that request's own answer does.  It used to wait for the words
    "working out" to leave the corner, inside a budget that was exactly the
    note's own flash time -- which told answered from timed out only because
    a hidden notice happens not to clear its text (bug 44).
    """
    for text in utterances:
        view._voice.listener.speak(text)
    qtbot.waitUntil(lambda: view._slideshows.showing.shown._working_request is None, timeout=5000)


def test_saying_request_pauses_the_slideshow_until_over(qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak("Request.")
    assert view._slideshows.showing._keeps()
    assert "Request" in words(view._slideshows.showing.shown._note)

    view._voice.listener.speak("no hat. Over.")
    assert not view._slideshows.showing._keeps()


def test_a_finished_request_stands_in_every_job_queue_until_its_job_does(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    shown = view._slideshows.showing.shown

    view._voice.listener.speak("Request, no hat, over.")  # answered a hop later

    (standing,) = view._queue._items
    assert standing.starting
    assert standing.requested
    assert [item.key for item in shown.queue_foot.hud_queue[0]] == [standing.key]
    qtbot.waitUntil(lambda: shown._working_request is None, timeout=5000)
    (queued,) = view._queue._items
    assert queued.requested
    assert not queued.starting
    assert [item.key for item in shown.queue_foot.hud_queue[0]] == [queued.key]


def test_a_finished_request_queues_the_revision_with_the_same_seed(
        qtbot, tmp_path, monkeypatch):
    # "the same image but without X" means the image, so the one thing not
    # re-rolled is the seed that draws it.
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    assert job.params["seed"] == 7
    assert job.params["positive_prompt"] == "a woman, soft light"
    assert job.params["negative_prompt"] == "blurry"


def test_a_request_rewritten_past_a_boxs_end_queues_in_boxes_of_whole_words(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    cats = [" ".join(["cat"] * count) for count in (80, 75, 5)]
    view = _requesting_view(qtbot, tmp_path, monkeypatch, prompt=f"a hat, {cats[0]}")

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    assert job.params["positive_prompt"] == f"{cats[1]}{BOX_BREAK}{cats[2]}"


def test_a_request_on_a_prompt_in_boxes_is_recorded_as_stored_and_as_queued(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    cats = [" ".join(["cat"] * count) for count in (75, 5)]
    stored = f"a hat,{BOX_BREAK}{cats[0]}{BOX_BREAK}{cats[1]}"
    view = _requesting_view(qtbot, tmp_path, monkeypatch, prompt=stored)

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    record = view._db.get_request(job.prompt_id)
    assert (record["old_positive"], record["new_positive"]) == (
        stored, f"{cats[0]}{BOX_BREAK}{cats[1]}")
    assert record["new_positive"] == job.params["positive_prompt"]


def test_a_queued_request_says_only_that_it_was_submitted(qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    _speak_request(view, qtbot, "Request, no hat, over.")

    assert words(view._slideshows.showing.shown._note) == "Request submitted"


def test_a_request_for_something_absent_goes_to_the_negative_prompt(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch, prompt="a woman, soft light")

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    assert job.params["negative_prompt"] == "blurry, hat"


def test_a_queued_request_is_recorded_against_what_it_was_asked_about(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    record = view._db.get_request(job.prompt_id)
    assert record["source_prompt_id"] == "orig"
    assert record["heard"] == "Request, no hat, over."
    assert record["old_positive"] == "a woman, a hat, soft light"
    assert record["new_positive"] == "a woman, soft light"


def test_a_queued_request_keeps_its_words_without_the_markers(qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    _speak_request(view, qtbot, "Request, no hat, over.")

    (job,) = view._live_jobs.values()
    assert view._db.get_request(job.prompt_id)["asked"] == "no hat"


def test_a_queued_request_is_logged_by_the_images_it_joins_never_by_its_words(
        qtbot, tmp_path, monkeypatch, caplog):
    view = _requesting_view(qtbot, tmp_path, monkeypatch,
                            prompt="gamma form, an example lantern, soft light")

    with caplog.at_level("INFO"):
        _speak_request(view, qtbot, "Request, no example lantern, over.")

    (job,) = view._live_jobs.values()
    assert f"Request on orig: term dropped, queued as {job.prompt_id}" in caplog.messages
    for private in ("lantern", "soft light", "blurry"):
        assert private not in caplog.text


def test_the_request_lands_on_the_slide_it_was_opened_over(
        qtbot, tmp_path, monkeypatch):
    # The words take seconds; the slideshow holds, but the target is taken when the
    # request opens rather than when it runs out.
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    view._voice.listener.speak("Request.")

    view._slideshows.showing._set.playlist.add(("other.png", "image", "elsewhere", None))
    view._slideshows.showing.slideshow_step(1)
    _speak_request(view, qtbot, "no hat. Over.")

    (job,) = view._live_jobs.values()
    assert view._db.get_request(job.prompt_id)["source_prompt_id"] == "orig"


def test_a_request_that_never_hears_over_says_so_and_resumes(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    view._voice.listener._dictation = RequestDictation(max_utterances=2)

    view._voice.listener.speak("Request.")
    view._voice.listener.speak("no hat")

    assert not view._slideshows.showing._keeps()
    assert "never heard" in words(view._slideshows.showing.shown._note)
    assert view._live_jobs == {}


def test_a_request_naming_nothing_is_answered_not_generated(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    _speak_request(view, qtbot, "Request. Over.")

    assert view._live_jobs == {}
    assert "didn't catch" in words(view._slideshows.showing.shown._note)


def test_the_words_of_a_request_never_reach_the_fix_matcher(
        qtbot, tmp_path, monkeypatch):
    # An open request swallows what it hears; "fix teeth" said inside one is
    # part of the sentence, not a command.
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    view._voice.listener.speak("Request.")

    view._voice.listener.speak("fix teeth")

    assert view._live_jobs == {}  # no enhance launched


def test_a_request_item_links_back_to_what_it_was_asked_about(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    _speak_request(view, qtbot, "Request, no hat, over.")
    view._slideshows.showing.close()
    (job,) = view._live_jobs.values()
    _finish_reroll(view, job)

    view._on_thumbnail_clicked(job.prompt_id)

    section = view._info_tabs.current_config_panel()._related._requests_section
    assert not section.isHidden()
    assert [(tile._heading.text(), tile._prompt_id) for tile in section._tiles] == [
        ("Requested from", "orig")]


def test_a_request_landing_takes_the_place_of_its_image_on_a_slideshow_locked_on_it(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    _speak_request(view, qtbot, "Request, no hat, over.")
    slideshow = view._slideshows.showing
    slideshow.show_item("orig.png", lock=True)  # the double-click on the map
    (job,) = view._live_jobs.values()
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, output_dir: (f"{row['prompt_id']}.png", "image"))

    _finish_reroll(view, job)

    assert (slideshow.voice_target(), slideshow.locked) == (job.prompt_id, True)


def test_a_request_item_shows_its_words_in_its_tab_s_request_section(
        qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    _speak_request(view, qtbot, "Request, no hat, over.")
    view._slideshows.showing.close()
    (job,) = view._live_jobs.values()
    _finish_reroll(view, job)

    view._on_thumbnail_clicked(job.prompt_id)

    field = view._info_tabs.current_config_panel()._param_form.request_field()
    assert field._words.text() == "no hat"


def test_what_the_microphone_heard_reaches_the_slideshow(
        qtbot, tmp_path, monkeypatch):
    # From a slideshow this window is invisible, so a mic that heard nothing and
    # one that heard the wrong words used to look exactly alike.
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    view._voice.listener.heard.emit("something off the mic")

    assert "something off the mic" in words(view._slideshows.showing.shown._note)


def test_a_voice_failure_reaches_the_slideshow_too(qtbot, tmp_path, monkeypatch):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    view._voice.listener.error.emit("mic unavailable — No module named 'sounddevice'")

    assert "mic unavailable" in words(view._slideshows.showing.shown._note)


def test_the_slideshow_shows_the_request_as_it_is_being_said(
        qtbot, tmp_path, monkeypatch):
    # What was missing when a spoken request looked like nothing happening.
    view = _requesting_view(qtbot, tmp_path, monkeypatch)

    view._voice.listener.speak("Request.")
    assert "Request" in words(view._slideshows.showing.shown._note)

    view._voice.listener.speak("no hat")
    assert "no hat" in words(view._slideshows.showing.shown._note)


# --- "animate as go now", spoken over a fullscreen image -------------------


_SPOKEN_LOOP = AnimateRequest(act_settings.GENAU, "")


def test_a_spoken_loop_takes_the_one_act_the_sorted_image_leaves(qtbot, tmp_path,
                                                                 monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    # "img_act" is sorted, and its state leaves the Genau lane one act, so the
    # command needs none said.
    prompt_id, message, kind = view.animate_it("img_act", _SPOKEN_LOOP)

    assert prompt_id == "img_act"
    assert "alpha" in message
    assert kind == NOTICE
    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_flf2v_loop"
    assert job.params["input_image"] == "sdxl_act.png [output]"
    # Spoken, so it hands itself on: whoever said it is not at the keyboard.
    assert view._db.get_generation(job.prompt_id)["genau_requested_at"]


def test_a_spoken_loop_over_an_unsorted_image_asks_for_its_action(qtbot, tmp_path,
                                                                  monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    prompt_id, message, kind = view.animate_it("img", _SPOKEN_LOOP)  # never sorted

    assert prompt_id is None
    assert "hasn't been sorted" in message
    assert kind == WARNING
    assert not view._live_jobs  # nothing was launched on a guess


def test_a_spoken_loop_says_so_when_the_act_has_no_loop_behind_it(qtbot, tmp_path,
                                                                  monkeypatch):
    db = _genau_db(tmp_path)
    # A sorted image of a state whose act the gallery holds no looping clip of.
    db.insert_generation(
        prompt_id="img_delta", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="another image", seed=3,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=3,
                                    positive_prompt="another image")),
        workflow_json="{}",
    )
    db.update_generation("img_delta", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_delta.png", "subfolder": ""}]))
    db.set_image_state("img_delta", "state two")
    db.set_settings_source("loop", category=None)  # nothing left to mine a loop from
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    prompt_id, message, kind = view.animate_it("img_delta", _SPOKEN_LOOP)

    assert prompt_id is None
    assert "to take settings from yet" in message
    assert message.startswith("no past looping “")
    assert kind == WARNING
    assert not view._live_jobs


def test_a_spoken_loop_declines_a_video(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    prompt_id, message, kind = view.animate_it("loop", _SPOKEN_LOOP)

    assert prompt_id is None
    assert "image" in message
    assert kind == WARNING


def test_a_spoken_loop_is_answered_on_the_surface_that_heard_it(qtbot, tmp_path,
                                                                monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    surface = _VoiceSurface("img_act")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))

    # Answered in the surface's own corner, not in a dialog over it — the speaker
    # is looking at the image, not at this pane.
    assert surface.noted[0] == "img_act"
    assert "alpha" in surface.noted[1]
    assert next(iter(view._live_jobs.values())).workflow.name == "wan22_flf2v_loop"


def _spoken_genau_rows(view):
    """Every run a spoken animation has launched into the Genau lane, landed or not."""
    return [r for r in view._db.list_generations() if r.get("genau_requested_at")]


def test_a_second_spoken_loop_over_the_same_image_is_refused(qtbot, tmp_path, monkeypatch):
    # Saying it twice is what you do when the first time appeared to do nothing,
    # and it does appear to: the video queues after whatever the machine is on
    # and the image on screen doesn't change. Two identical runs would spend
    # minutes of the one GPU making a video that is already coming.
    view = _genau_view(qtbot, tmp_path)
    surface = _VoiceSurface("img_act")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))
    assert len(_spoken_genau_rows(view)) == 1

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))

    assert surface.noted == (None, combine_controller.ALREADY_GENAUD, WARNING)
    assert len(_spoken_genau_rows(view)) == 1


def test_an_image_whose_clip_has_landed_is_answered_the_same_way(
        qtbot, tmp_path, monkeypatch):
    # A video that has arrived is still a video of this image — asking again
    # would only re-make it, so it is answered rather than run.
    view = _genau_view(qtbot, tmp_path)
    surface = _VoiceSurface("img_act")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))
    (made,) = _spoken_genau_rows(view)
    view._db.update_generation(made["prompt_id"], status="completed",
                               output_files=json.dumps([{"filename": "loop_2.mp4"}]))

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))

    assert surface.noted == (None, combine_controller.ALREADY_GENAUD, WARNING)
    assert len(_spoken_genau_rows(view)) == 1


def test_a_run_that_errored_made_no_clip_and_does_not_stand_in_for_one(
        qtbot, tmp_path, monkeypatch):
    # Asking again is the only way to get a video after a failure, so a row that
    # produced nothing must not read as this image having been Genau'd.
    view = _genau_view(qtbot, tmp_path)
    view._slideshows._slideshow = _VoiceSurface("img_act")

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))
    (failed,) = _spoken_genau_rows(view)
    view._jobs.job_for_prompt(failed["prompt_id"]).failed.emit("ComfyUI said no")

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))

    assert len(_spoken_genau_rows(view)) == 2


def test_a_pressed_generate_of_the_same_act_is_not_what_the_guard_counts(
        qtbot, tmp_path, monkeypatch):
    # Only a spoken one is stamped, and only a spoken one can be said again into
    # the wait: someone at the keyboard can see the queue they just joined.
    view = _genau_view(qtbot, tmp_path)
    view._combine.generate_category("img_act", "alpha", act_settings.GENAU)
    view._slideshows._slideshow = _VoiceSurface("img_act")

    view._voice.on_command(SurfaceCommand(_SPOKEN_LOOP))

    assert len(_spoken_genau_rows(view)) == 1


def test_a_spoken_enhance_asks_for_the_better_version_of_the_slide(qtbot, tmp_path):
    # The spoken form of the Enhance button, aimed at the image being watched.
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 29})
    surface = _VoiceSurface("g0")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 29
    # Answered in the slideshow's own corner: the speaker is looking at the image.
    assert surface.noted == ("g0", "enhancing…", NOTICE)


def test_a_spoken_enhance_leaves_an_already_enhanced_image_alone(qtbot, tmp_path):
    # Said over a slideshow, this is a gesture made with no view of the Enhance panel
    # — the same reason a hold's Down leaves one alone — so it says so rather
    # than re-deriving the image at whatever the settings happen to read now.
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps([
        {"filename": "image_enhance_1.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
    ]), original_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    surface = _VoiceSurface("g0")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    assert surface.noted == (None, "this one is enhanced already", WARNING)
    assert view._live_jobs == {}


def test_a_spoken_enhance_over_a_clip_says_there_is_nothing_to_enhance(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps(
        [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    surface = _VoiceSurface("g0")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    assert surface.noted == (None, "only a finished image can be enhanced", WARNING)
    assert view._live_jobs == {}


def test_a_spoken_enhance_over_a_row_that_names_no_file_says_so(qtbot, tmp_path):
    # A row can hold an output entry with no name; it reads as a finished image
    # everywhere else, and there is nothing to feed the enhancer.
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps(
        [{"subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    surface = _VoiceSurface("g0")
    view._slideshows._slideshow = surface

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    assert surface.noted == (None, "this one has no file to enhance", WARNING)
    assert view._live_jobs == {}


def test_a_spoken_enhance_with_no_slideshow_up_presses_the_bank_button(qtbot, tmp_path):
    # The word names a bank button as well as the image on screen, and with no
    # image filling the screen it is the button — aimed the way a click aims
    # it, at the folder's images that have never been enhanced.
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 29})
    _select_first_leaf(view)

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 29


def test_a_spoken_enhance_with_nothing_to_enhance_says_so(qtbot, tmp_path):
    # The utterance has already been claimed as a command by the time it gets
    # here, so it is answered in this pane rather than vanishing — in the
    # button's own words, which is what a speaker not looking at it needs.
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND))

    assert words(view._voice.status) == "Nothing here to enhance"
    assert view._live_jobs == {}


def test_the_voice_surface_is_given_the_whole_spoken_vocabulary():
    # One matcher reaches the mic for everything that tolerates a filler word, so
    # a verb added to the vocabulary lands there without this module listing the
    # parts a second time and drifting from it.  It wraps what it matches with
    # the side the utterance named, which is how a room with two slideshows in it
    # says which image is meant.

    assert match("enhance").command == gallery.ENHANCE_COMMAND
    assert match("animate as alpha").command.act == "alpha"
    assert [part.name for part in match("fix teeth").command] == ["teeth"]
    assert match("start slideshow") is not None
    assert match("make her hair longer") is None    # a sentence, not a command
    # The bare words are not in this one: they match whole utterances only,
    # which is what lets them be asked ahead of an opening request instead.
    assert match("weird") is None


def test_a_spoken_loop_hands_its_finished_clip_on(qtbot, tmp_path, monkeypatch):
    # The folder is read off the lane, so a spoken send and a pressed one cannot
    # differ about where a video lands.
    view = _genau_view(qtbot, tmp_path)
    view._db.mark_genau_requested("loop")   # as a spoken launch would have
    video = Path("C:/out/flf2v_loop_1.mp4")
    monkeypatch.setattr(gallery_view_module.gallery, "resolve_preview",
                        lambda row, out: (video, "video"))
    sent = []
    monkeypatch.setattr(combine_controller.evolver_export, "export_video",
                        lambda src, dest, funscript=None:
                        sent.append((src, dest)) or dest / src.name)

    view._on_reroll_finished("k", "loop")

    assert sent == [(video, EVOLVER_INBOX_DIR / GENAU_SOURCE)]
    assert view._db.get_generation("loop")["genau_exported_at"]


def test_a_clip_already_handed_on_is_not_sent_twice(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)
    view._db.mark_genau_requested("loop")
    view._db.mark_genau_exported("loop")
    monkeypatch.setattr(gallery_view_module.gallery, "resolve_preview",
                        lambda row, out: (Path("C:/out/flf2v_loop_1.mp4"), "video"))
    sent = []
    monkeypatch.setattr(combine_controller.evolver_export, "export_video",
                        lambda src, dest, funscript=None: sent.append(src))

    view._on_reroll_finished("k", "loop")

    assert sent == []


def test_a_failed_hand_off_leaves_the_clip_in_the_gallery(qtbot, tmp_path, monkeypatch):
    # The inbox copy is the only thing that failed; the video itself is fine, and
    # Send-to-Genau is still there to retry with.
    view = _genau_view(qtbot, tmp_path)
    view._db.mark_genau_requested("loop")
    monkeypatch.setattr(gallery_view_module.gallery, "resolve_preview",
                        lambda row, out: (Path("C:/out/flf2v_loop_1.mp4"), "video"))

    def boom(src, dest, funscript=None):
        raise OSError("the inbox is not there")

    monkeypatch.setattr(combine_controller.evolver_export, "export_video", boom)

    view._on_reroll_finished("k", "loop")  # must not raise

    assert view._db.get_generation("loop")["genau_exported_at"] is None


# --- the bare vocabulary: a collection, a bank button, a word over the slideshow ---


def _listening(qtbot, tmp_path, db=None):
    """A gallery with the mic armed — the one switch that opens it — and its
    tree drawn, so a collection name has a row to land on."""
    view = GalleryView(db if db is not None else _seeded_db(tmp_path),
                       client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._bank.mic.setChecked(True)
    return view


@pytest.mark.parametrize("said, key", [
    ("experiments", EXPERIMENTS_KEY),
    ("trash", TRASH_KEY),
    ("recents", LATEST_KEY),
    ("go to favorites", FAVORITES_KEY),
    ("go to experiments", EXPERIMENTS_KEY),
])
def test_a_spoken_collection_name_stands_you_in_that_collection(qtbot, tmp_path, said, key):
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak(said)

    assert _selected_folder(view) == key


def test_a_collection_the_tree_has_not_got_says_so_rather_than_doing_nothing(
        qtbot, tmp_path):
    # Favorites appears only once there are folders; a word for a row that isn't
    # there must not vanish, having already been claimed as a command.
    db = Database(tmp_path / "empty.db")
    view = _listening(qtbot, tmp_path, db=db)

    view._voice.listener.speak("go to favorites")

    assert words(view._voice.status) == "no Favorites collection yet"


def test_fun_times_own_words_do_here_what_they_do_there(qtbot, tmp_path):
    # "weird" condemns what is on screen and a lock holds it — the two rooms are
    # one room to whoever is speaking.
    view = _listening(qtbot, tmp_path)
    surface = _VoiceSurface("orig")
    view._slideshows._slideshow = surface

    view._voice.listener.speak("weird")
    assert surface.culled == 1

    view._voice.listener.speak("lock")
    assert surface.locked
    assert surface.said == "locked this one"

    view._voice.listener.speak("lock")
    assert surface.said == "already locked"  # asked for a state, not a flip

    view._voice.listener.speak("unlock")
    assert not surface.locked
    assert surface.said == "let go"


def test_the_transport_words_step_the_slideshow_they_are_said_over(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)
    surface = _VoiceSurface("orig")
    view._slideshows._slideshow = surface

    for said in ("next", "skip", "back", "previous"):
        view._voice.listener.speak(said)

    assert surface.steps == [1, 1, -1, -1]


def test_a_spoken_favorite_over_a_slideshow_favorites_the_slide(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)
    surface = _VoiceSurface("orig")
    view._slideshows._slideshow = surface

    view._voice.listener.speak("favorite")

    assert surface.favorited == 1
    assert surface.said == "favorited"


def test_the_same_two_words_walk_the_history_with_no_slideshow_up(qtbot, tmp_path):
    # The active side, with two sides: over a slideshow "back" is the slide before,
    # and in the gallery it is the stop before — both are the one before.
    view = _listening(qtbot, tmp_path)
    first = _select_first_leaf(view)
    view._voice.listener.speak("trash")            # a second stop to come back from

    view._voice.listener.speak("back")

    assert _selected_folder(view) == first


def test_a_step_with_nowhere_to_go_says_so(qtbot, tmp_path):
    # Back and Forward wear bare labels, so they carry their own refusal rather
    # than reading their tooltip back.
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("forward")

    assert words(view._voice.status) == "nowhere forward"


def test_a_bank_word_presses_its_button_and_answers_in_its_own_words(
        qtbot, tmp_path):
    # The tip already names the target it is aimed at, which is exactly what a
    # speaker who is not looking at the bank needs told back.
    view = _listening(qtbot, tmp_path)
    _select_first_leaf(view)
    _click_off(view)                               # so the button is the folder's
    aimed = view._bank.favorite.toolTip()
    assert aimed.startswith("Favorite folder")

    view._voice.listener.speak("favorite")

    assert words(view._voice.status) == aimed
    assert view._bank.favorite.toolTip().startswith("Unfavorite folder")


def test_a_bank_word_with_nothing_to_do_says_why(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("undo")

    assert words(view._voice.status) == "Nothing to undo"


def test_locking_is_a_slideshows_word_and_says_so_with_none_up(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("lock")

    assert words(view._voice.status) == "lock is a slideshow's — none is up"


def test_a_spoken_switch_flips_the_bank_switch_itself(qtbot, tmp_path):
    # Set through the button rather than around it, so a spoken switch and a
    # clicked one are the same event and the bank lights the same way.
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("drive on")
    assert view.osr2_control.isChecked()
    assert words(view._voice.status) == "OSR2 on"

    view._voice.listener.speak("drive")           # bare: flips whichever way it stands
    assert not view.osr2_control.isChecked()

    view._voice.listener.speak("drive off")       # already off: still ends up off
    assert not view.osr2_control.isChecked()


def test_osr2_off_parks_the_device_as_the_console_switch_does(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)
    view._voice.listener.speak("drive on")

    view._voice.listener.speak("OSR2 off")

    assert view.osr2_control.state() == OSR2_PARKED
    assert words(view._voice.status) == "OSR2 off"


def test_the_mic_can_be_shut_by_voice(qtbot, tmp_path):
    # And only shut: a mic that hears nothing cannot hear "mic on", so the
    # toolbar switch is the only way back.
    view = _listening(qtbot, tmp_path)
    assert view._voice.listener.commands_on

    view._voice.listener.speak("mic off")

    assert not view._bank.mic.isChecked()
    assert not view._voice.listener.commands_on


def test_a_spoken_bar_word_moves_its_bar_the_way_its_key_does(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)
    bars = view._osr2_motion.state.state
    amplitude, center = bars.amplitude, bars.center

    view._voice.listener.speak("amp down")   # travel opens at its widest, so down from there
    view._voice.listener.speak("center up")

    assert bars.amplitude == amplitude - 10
    assert bars.center == center + 5
    # Answered with what the device now reads, which is the panel's own line.
    assert words(view._voice.status) == view._osr2_motion.status_text()


def test_a_spoken_number_puts_a_bar_where_it_says(qtbot, tmp_path):
    # The nudges walk a bar five or ten at a time, which never arrives from the
    # far end; the number said outright is what Fun Time answers with too.
    view = _listening(qtbot, tmp_path)
    bars = view._osr2_motion.state.state

    view._voice.listener.speak("amp fifty")
    assert bars.amplitude == 50

    view._voice.listener.speak("center 30")   # whisper writes the number either way
    assert bars.intended_center == 30

    view._voice.listener.speak("max speed")
    assert bars.speed == motion_engine.MAX_SPEED
    assert words(view._voice.status) == view._osr2_motion.status_text()


def test_min_speed_lands_on_the_slowest_the_bar_actually_moves(qtbot, tmp_path):
    # The vocabulary says nought and the bar says what its floor is; the
    # clamping is the bar's business, which is why the grid can be uniform.
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("min speed")

    assert view._osr2_motion.state.state.speed == motion_engine.MIN_SPEED


def test_human_inspired_motion_can_be_asked_for_outright_rather_than_flipped(qtbot, tmp_path):
    view = _listening(qtbot, tmp_path)

    view._voice.listener.speak("human inspired on")
    assert view._osr2_motion.state.learned.active

    view._voice.listener.speak("human inspired on")       # already on: still ends up on
    assert view._osr2_motion.state.learned.active

    view._voice.listener.speak("human inspired off")
    assert not view._osr2_motion.state.learned.active


def test_a_motion_word_answers_from_a_slideshow_too(qtbot, tmp_path):
    # The driver is app-wide, so its words belong to no surface — but the answer
    # goes where the speaker is looking.
    view = _listening(qtbot, tmp_path)
    surface = _VoiceSurface("orig")
    view._slideshows._slideshow = surface

    view._voice.listener.speak("next shape")

    assert surface.said == view._osr2_motion.status_text()


def test_a_sentence_holding_a_command_word_is_no_command(qtbot, tmp_path):
    # Nothing in the bare vocabulary matches anything but the whole utterance,
    # so a sentence holding one of its words asks for nothing.
    view = _listening(qtbot, tmp_path)
    surface = _VoiceSurface("orig")
    view._slideshows._slideshow = surface

    assert view._voice.listener.speak("a lock of hair over her eye") is None
    assert surface.said is None
    assert surface.steps == []
