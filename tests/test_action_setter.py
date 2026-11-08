from __future__ import annotations

import json

from origenerator.action_setter import Locks, SetterSession, waiting
from origenerator.gallery.enhance import enhance_file_stem
from origenerator.generation_state import GenerationSource
from origenerator.item_actions import ItemActions, stored
from origenerator.media import MediaType

_SET = ItemActions(("alpha", "beta"), ("first box",))


class _Store:
    def __init__(self):
        self.item_actions = {}

    def set_actions(self, prompt_id, side, item_actions):
        self.item_actions[prompt_id] = (side, item_actions)


def _items(*prompt_ids, before=None):
    return [{"prompt_id": prompt_id, "actions": before} for prompt_id in prompt_ids]


def test_a_press_saves_its_actions_on_the_item_on_screen_and_the_next_one_comes_up():
    store = _Store()
    session = SetterSession(_items("first", "second"), store, MediaType.IMAGE)

    session.set_as("two", _SET)

    assert store.item_actions == {"first": (MediaType.IMAGE, _SET)}
    assert (session.current["prompt_id"], session.remaining) == ("second", 1)


def test_a_press_with_nothing_on_screen_does_nothing():
    store = _Store()
    session = SetterSession([], store, MediaType.VIDEO)

    session.set_as("two", _SET)

    assert (store.item_actions, session.current) == ({}, None)


def test_skipping_sends_the_item_to_the_back_of_the_line_without_actions():
    store = _Store()
    session = SetterSession(_items("first", "second"), store, MediaType.IMAGE)

    session.skip()

    assert store.item_actions == {}
    assert (session.current["prompt_id"], session.remaining) == ("second", 2)


def test_undo_puts_back_the_actions_the_item_had_and_puts_it_on_screen_again():
    store = _Store()
    before = ItemActions(("gamma",))
    session = SetterSession(_items("first", "second", before=before), store, MediaType.IMAGE)
    session.set_as("two", _SET)

    session.undo()

    assert store.item_actions == {"first": (MediaType.IMAGE, before)}
    assert (session.current["prompt_id"], session.remaining) == ("first", 2)


def test_undo_takes_an_item_nobody_had_given_actions_back_to_none():
    store = _Store()
    session = SetterSession(_items("first"), store, MediaType.VIDEO)
    session.set_as("two", _SET)

    session.undo()

    assert store.item_actions == {"first": (MediaType.VIDEO, None)}


def test_undo_with_nothing_pressed_yet_changes_nothing():
    store = _Store()
    session = SetterSession(_items("first"), store, MediaType.IMAGE)

    session.undo()

    assert (store.item_actions, session.current["prompt_id"]) == ({}, "first")


def test_the_session_says_what_the_last_press_was_and_whether_it_can_be_undone():
    session = SetterSession(_items("first", "second"), _Store(), MediaType.IMAGE)
    before = (session.last, session.can_undo)

    session.set_as("two", _SET)
    after = (session.last, session.can_undo)
    session.undo()

    assert (before, after, (session.last, session.can_undo)) == (
        (None, False), (("two", _SET), True), (None, False))


class _Bin:
    def __init__(self):
        self.thrown = []

    def away(self, prompt_id):
        self.thrown.append(prompt_id)

    def back(self, prompt_id):
        self.thrown.remove(prompt_id)


def test_trash_throws_the_item_on_screen_away_and_the_next_one_comes_up():
    rubbish = _Bin()
    session = SetterSession(_items("first", "second"), _Store(), MediaType.IMAGE, rubbish)

    session.trash()

    assert (rubbish.thrown, session.current["prompt_id"], session.remaining) == (
        ["first"], "second", 1)


def test_trash_throws_away_the_item_shown_where_its_actions_live_on_another():
    rubbish = _Bin()
    session = SetterSession([{"prompt_id": "frame", "shown_id": "video", "actions": None}],
                            _Store(), MediaType.IMAGE, rubbish)

    session.trash()

    assert rubbish.thrown == ["video"]


def test_undo_brings_a_trashed_item_back_and_puts_it_on_screen_again():
    rubbish = _Bin()
    store = _Store()
    session = SetterSession(_items("first", "second"), store, MediaType.IMAGE, rubbish)
    session.trash()

    session.undo()

    assert (rubbish.thrown, store.item_actions, session.current["prompt_id"], session.remaining) == (
        [], {}, "first", 2)


def test_same_as_last_goes_by_the_last_press_past_an_item_trashed_since():
    session = SetterSession(_items("first", "second", "third"), _Store(), MediaType.IMAGE,
                            _Bin())
    session.set_as("two", _SET)

    session.trash()

    assert (session.last, session.can_undo) == (("two", _SET), True)


def test_with_no_trash_to_throw_into_nothing_is_thrown_away():
    session = SetterSession(_items("first"), _Store(), MediaType.IMAGE)

    session.trash()

    assert (session.current["prompt_id"], session.can_undo) == ("first", False)


def test_locks_hold_each_checkbox_as_it_was_left_until_they_are_let_go(tmp_path):
    path = tmp_path / "locks.json"
    Locks(path).hold(MediaType.IMAGE, "first box", True)
    Locks(path).hold(MediaType.VIDEO, "third box", False)

    held = Locks(path)
    before = (held.held(MediaType.IMAGE), held.held(MediaType.VIDEO))
    held.let_go(MediaType.IMAGE, "first box")

    assert before == ({"first box": True}, {"third box": False})
    assert Locks(path).held(MediaType.IMAGE) == {}


def test_locks_that_cannot_be_read_hold_nothing(tmp_path):
    path = tmp_path / "locks.json"
    path.write_text("not json", encoding="utf-8")

    assert Locks(path).held(MediaType.IMAGE) == {}


def _row(prompt_id, filename, *, created="2026-01-01 00:00:00", item_actions=None, **extra):
    files = [{"filename": filename, "subfolder": "", "type": "output"}] if filename else []
    actions, checked = stored(item_actions) if item_actions is not None else (None, None)
    return {
        "prompt_id": prompt_id, "workflow_name": "sdxl_t2i", "workflow_version": "v001",
        "status": "completed", "params_json": "{}",
        "output_files": json.dumps(files) if files else None, "created_at": created,
        "image_actions": actions, "image_checked": checked,
        "video_actions": actions, "video_checked": checked, **extra,
    }


def _ids(waiting_now):
    return [entry.holder["prompt_id"] for entry in waiting_now]


def test_only_finished_images_with_no_actions_yet_wait_for_their_actions():
    rows = [
        _row("image", "scene_00001_.png"),
        _row("given actions", "scene_00002_.png", item_actions=ItemActions(("alpha",))),
        _row("checked only", "scene_00005_.png", item_actions=ItemActions((), ("first box",))),
        _row("no-file", None),
    ]

    assert _ids(waiting(rows, MediaType.IMAGE)) == ["image", "checked only"]


def test_a_video_made_from_no_image_waits_among_the_images_as_itself():
    rows = [_row("made from words", "words_00001_.mp4"),
            _row("given actions", "words_00002_.mp4", item_actions=ItemActions(("alpha",)))]

    [entry] = waiting(rows, MediaType.IMAGE)

    assert (entry.holder["prompt_id"], entry.shown["prompt_id"]) == (
        "made from words", "made from words")


def test_a_video_made_from_an_image_leaves_its_image_actions_to_that_image():
    rows = [_row("image", "scene_00001_.png", item_actions=ItemActions(("alpha",))),
            _row("video", "video_00001_.mp4", params_json=json.dumps(
                {"input_image": "scene_00001_.png"}))]

    assert _ids(waiting(rows, MediaType.IMAGE)) == []


def test_a_video_brought_in_waits_among_the_images_to_be_saved_on_the_frame_taken_from_it():
    frame = _row("frame", "frame_00001_.png", source=GenerationSource.STARTING_FRAME)
    video = _row("theirs", "theirs_00001_.mp4", source=GenerationSource.OUTSIDE,
                 params_json=json.dumps({"input_image": "frame_00001_.png"}))

    [entry] = waiting([frame, video], MediaType.IMAGE)

    assert (entry.holder["prompt_id"], entry.shown["prompt_id"]) == ("frame", "theirs")


def test_only_finished_videos_with_no_actions_yet_wait_for_their_actions():
    rows = [
        _row("video", "scene_00001_.mp4"),
        _row("given actions", "scene_00002_.mp4", item_actions=ItemActions(("alpha",))),
        _row("image", "scene_00003_.png"),
    ]

    assert _ids(waiting(rows, MediaType.VIDEO)) == ["video"]


def test_an_enhancement_waiting_to_be_folded_is_not_a_second_image_to_label():
    rows = [
        _row("image", "scene_00001_.png"),
        _row("its-better-version", f"{enhance_file_stem()}_00001_.png"),
    ]

    assert _ids(waiting(rows, MediaType.IMAGE)) == ["image"]


def test_the_favorites_come_first_and_each_half_runs_newest_backwards():
    rows = [
        _row("plain-old", "a_00001_.png", created="2026-01-01 00:00:00"),
        _row("favorite-old", "b_00001_.png", created="2026-01-02 00:00:00", starred=1),
        _row("plain-new", "c_00001_.png", created="2026-01-03 00:00:00"),
        _row("favorite-new", "d_00001_.png", created="2026-01-04 00:00:00", starred=1),
    ]

    assert _ids(waiting(rows, MediaType.IMAGE)) == [
        "favorite-new", "favorite-old", "plain-new", "plain-old"]


def test_items_sent_back_for_their_actions_come_first_in_the_order_they_were_sent():
    rows = [
        _row("plain-old", "a_00001_.png", created="2026-01-01 00:00:00"),
        _row("favorite", "b_00001_.png", created="2026-01-02 00:00:00", starred=1),
        _row("plain-new", "c_00001_.png", created="2026-01-03 00:00:00"),
    ]

    assert _ids(waiting(rows, MediaType.IMAGE, sent_back=("plain-old", "gone", "plain-new"))) == [
        "plain-old", "plain-new", "favorite"]
