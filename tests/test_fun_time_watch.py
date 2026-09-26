from __future__ import annotations

import json
import os

from origenerator.fun_time_mode import Rect, offer_the_window_while_it_is_built
from origenerator.gui.fun_time_watch import FunTimeWatch
from origenerator.win32 import this_process_creation_time


def _takeover(state_dir, *, pid):
    (state_dir / "fun_time_takeover.json").write_text(json.dumps({
        "pid": pid,
        "args": ["--fun-time", "--x", "0", "--y", "206", "--width", "853", "--height", "1234"],
    }), encoding="utf-8")


def _claim(state_dir, *, pid, created_at=None):
    created = this_process_creation_time() if created_at is None else created_at
    (state_dir / "fun_time_session.txt").write_text(
        f"{pid} {created}", encoding="utf-8")


def test_an_open_app_offers_itself_to_a_session_by_its_process(tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)

    assert (tmp_path / "fun_time_offer.txt").read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(this_process_creation_time())]
    watch.withdraw()


def test_a_takeover_for_this_app_hands_it_the_session_and_withdraws_the_offer(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)

    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    assert [session.main_rect for session in taken] == [Rect(0, 206, 853, 1234)]
    assert not (tmp_path / "fun_time_offer.txt").exists()
    _takeover(tmp_path, pid=os.getpid())
    qtbot.wait(600)
    assert len(taken) == 1
    assert (tmp_path / "fun_time_takeover.json").exists()
    del watch


def test_a_session_that_asked_while_the_window_was_being_built_takes_it_at_once(tmp_path):
    taken = []
    _takeover(tmp_path, pid=os.getpid())

    watch = FunTimeWatch(tmp_path, take_over=taken.append)

    assert [session.main_rect for session in taken] == [Rect(0, 206, 853, 1234)]
    assert not watch.stands_its_offer()


def test_an_app_handed_back_offers_itself_to_the_next_session(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)
    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: len(taken) == 1)

    watch.renew()

    assert (tmp_path / "fun_time_offer.txt").exists()
    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: len(taken) == 2)
    del watch


def test_a_window_opening_beside_a_live_session_is_told_the_device_is_taken(tmp_path):
    _claim(tmp_path, pid=os.getpid())
    said = []

    watch = FunTimeWatch(tmp_path, take_over=lambda session: None,
                         device_claimed=said.append)

    assert said == [True]
    watch.withdraw()


def test_a_session_starting_beside_an_open_window_takes_the_device_from_it(qtbot, tmp_path):
    said = []
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None,
                         device_claimed=said.append)

    _claim(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: said[-1] is True)

    (tmp_path / "fun_time_session.txt").unlink()
    qtbot.waitUntil(lambda: said[-1] is False)
    watch.withdraw()


def test_a_preview_is_told_the_device_is_taken_by_a_claim_on_the_everyday_copy(
        qtbot, tmp_path):
    preview, everyday = tmp_path / "preview", tmp_path / "everyday"
    preview.mkdir()
    everyday.mkdir()
    said = []
    watch = FunTimeWatch(preview, take_over=lambda session: None,
                         device_claimed=said.append, library_state_dir=everyday)

    _claim(everyday, pid=os.getpid())
    qtbot.waitUntil(lambda: said[-1] is True)

    watch.withdraw()


def test_a_claim_left_by_a_session_that_died_holds_nothing(qtbot, tmp_path):
    said = []
    _claim(tmp_path, pid=os.getpid(), created_at=this_process_creation_time() - 1)
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None,
                         device_claimed=said.append)

    assert said == [False]
    watch.withdraw()


def test_an_offer_deleted_under_an_open_window_is_put_back(qtbot, tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / "fun_time_offer.txt"

    offer.unlink()
    qtbot.waitUntil(offer.exists)

    assert offer.read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(this_process_creation_time())]
    watch.withdraw()


def test_an_offer_another_instance_overwrote_is_taken_back(qtbot, tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / "fun_time_offer.txt"

    offer.write_text("999999 12345", encoding="utf-8")
    qtbot.waitUntil(lambda: offer.read_text(encoding="utf-8").startswith(f"{os.getpid()} "))

    watch.withdraw()


def test_a_window_taken_over_stops_standing_its_offer(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)
    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    qtbot.wait(600)

    assert not (tmp_path / "fun_time_offer.txt").exists()
    del watch


def test_an_offer_another_instance_overwrote_is_recorded_when_it_is_taken_back(
        qtbot, tmp_path, caplog):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / "fun_time_offer.txt"

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        caplog.clear()
        offer.write_text("999999 12345", encoding="utf-8")
        qtbot.waitUntil(lambda: offer.read_text(encoding="utf-8").startswith(
            f"{os.getpid()} "))

    assert [record.message for record in caplog.records] == [
        "The offer to Fun Time named someone else; standing ours again"]
    watch.withdraw()


def test_an_offer_simply_missing_is_put_back_without_a_word(qtbot, tmp_path, caplog):
    # Withdrawn and renewed is the ordinary course of a session; only another
    # writer is worth a line.
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / "fun_time_offer.txt"

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        caplog.clear()
        offer.unlink()
        qtbot.waitUntil(offer.exists)

    assert caplog.records == []
    watch.withdraw()


def test_the_offer_made_while_starting_becomes_the_plain_one_without_a_word(tmp_path, caplog):
    offer_the_window_while_it_is_built(tmp_path)

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        watch = FunTimeWatch(tmp_path, take_over=lambda session: None)

    assert (tmp_path / "fun_time_offer.txt").read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(this_process_creation_time())]
    assert caplog.records == []
    watch.withdraw()


def test_a_takeover_arriving_is_recorded(qtbot, tmp_path, caplog):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        caplog.clear()
        _takeover(tmp_path, pid=os.getpid())
        qtbot.waitUntil(lambda: bool(taken))

    assert "A Fun Time session asked for this window" in caplog.text
    del watch
