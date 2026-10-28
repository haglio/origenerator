from __future__ import annotations

import os

from app_support import origenerator_handoff as handoff

from origenerator.fun_time_mode import Rect
from origenerator.gui.fun_time_watch import FunTimeWatch


def _takeover(state_dir, *, pid):
    handoff.hand_over(state_dir, pid=pid, args=[
        "--fun-time", "--x", "0", "--y", "206", "--width", "853", "--height", "1234"])


def _claim(state_dir, *, pid, created_at=None):
    created = handoff.this_process().created_at if created_at is None else created_at
    (state_dir / handoff.SESSION).write_text(f"{pid} {created}", encoding="utf-8")


def test_an_open_app_offers_itself_to_a_session_by_its_process(tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)

    assert (tmp_path / handoff.OFFER).read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(handoff.this_process().created_at)]
    watch.withdraw()


def test_a_takeover_for_this_app_hands_it_the_session_and_withdraws_the_offer(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)

    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    assert [session.main_rect for session in taken] == [Rect(0, 206, 853, 1234)]
    assert not (tmp_path / handoff.OFFER).exists()
    _takeover(tmp_path, pid=os.getpid())
    qtbot.wait(600)
    assert len(taken) == 1
    assert (tmp_path / handoff.TAKEOVER).exists()
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

    assert (tmp_path / handoff.OFFER).exists()
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

    (tmp_path / handoff.SESSION).unlink()
    qtbot.waitUntil(lambda: said[-1] is False)
    watch.withdraw()


def _preview_and_production(tmp_path):
    preview, production = tmp_path / "preview", tmp_path / "production"
    preview.mkdir()
    production.mkdir()
    return preview, production


def test_a_preview_is_told_the_device_is_taken_by_a_claim_on_the_production_copy(
        qtbot, tmp_path):
    preview, production = _preview_and_production(tmp_path)
    said = []
    watch = FunTimeWatch(preview, take_over=lambda session: None,
                         device_claimed=said.append, library_state_dir=production)

    _claim(production, pid=os.getpid())
    qtbot.waitUntil(lambda: said[-1] is True)

    watch.withdraw()


def test_a_preview_offers_itself_in_the_production_copy_s_state_where_every_session_looks(
        tmp_path):
    preview, production = _preview_and_production(tmp_path)

    watch = FunTimeWatch(preview, take_over=lambda session: None, library_state_dir=production)

    assert (production / handoff.OFFER).read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(handoff.this_process().created_at)]
    watch.withdraw()


def test_a_session_that_found_the_offer_in_the_production_copy_s_state_takes_the_preview(
        qtbot, tmp_path):
    preview, production = _preview_and_production(tmp_path)
    taken = []
    watch = FunTimeWatch(preview, take_over=taken.append, library_state_dir=production)

    _takeover(production, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    assert [session.main_rect for session in taken] == [Rect(0, 206, 853, 1234)]
    assert not (preview / handoff.OFFER).exists()
    assert not (production / handoff.OFFER).exists()
    del watch


def test_a_claim_left_by_a_session_that_died_holds_nothing(qtbot, tmp_path):
    said = []
    _claim(tmp_path, pid=os.getpid(), created_at=handoff.this_process().created_at - 1)
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None,
                         device_claimed=said.append)

    assert said == [False]
    watch.withdraw()


def test_an_offer_deleted_under_an_open_window_is_put_back(qtbot, tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / handoff.OFFER

    offer.unlink()
    qtbot.waitUntil(offer.exists)

    assert offer.read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(handoff.this_process().created_at)]
    watch.withdraw()


def test_an_offer_another_instance_overwrote_is_taken_back(qtbot, tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / handoff.OFFER

    offer.write_text("999999 12345", encoding="utf-8")
    qtbot.waitUntil(lambda: offer.read_text(encoding="utf-8").startswith(f"{os.getpid()} "))

    watch.withdraw()


def test_a_window_taken_over_stops_standing_its_offer(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append)
    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    qtbot.wait(600)

    assert not (tmp_path / handoff.OFFER).exists()
    del watch


def test_an_offer_another_instance_overwrote_is_recorded_when_it_is_taken_back(
        qtbot, tmp_path, caplog):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None)
    offer = tmp_path / handoff.OFFER

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
    offer = tmp_path / handoff.OFFER

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        caplog.clear()
        offer.unlink()
        qtbot.waitUntil(offer.exists)

    assert caplog.records == []
    watch.withdraw()


def test_the_offer_made_while_starting_becomes_the_plain_one_without_a_word(tmp_path, caplog):
    handoff.offer_this_process(tmp_path, starting=True)

    with caplog.at_level("INFO", logger="origenerator.gui.fun_time_watch"):
        watch = FunTimeWatch(tmp_path, take_over=lambda session: None)

    assert (tmp_path / handoff.OFFER).read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(handoff.this_process().created_at)]
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


def _marked(state_dir):
    mark = state_dir / handoff.SHOWING
    return mark.read_text(encoding="utf-8").split() if mark.exists() else None


def test_an_open_app_says_beside_its_offer_which_side_its_slideshow_is_showing_on(tmp_path):
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None,
                         showing_on=lambda: "portrait")

    assert _marked(tmp_path) == [str(os.getpid()), str(handoff.this_process().created_at), "portrait"]
    watch.withdraw()


def test_the_slideshow_mark_follows_the_slideshow_from_monitor_to_monitor(qtbot, tmp_path):
    on = [None]
    watch = FunTimeWatch(tmp_path, take_over=lambda session: None, showing_on=lambda: on[0])
    assert _marked(tmp_path) is None

    on[0] = "landscape"
    qtbot.waitUntil(lambda: (_marked(tmp_path) or [None])[-1] == "landscape")
    on[0] = "portrait"
    qtbot.waitUntil(lambda: (_marked(tmp_path) or [None])[-1] == "portrait")
    on[0] = None
    qtbot.waitUntil(lambda: _marked(tmp_path) is None)
    watch.withdraw()


def test_a_window_taken_over_takes_its_slideshow_mark_down_with_its_offer(qtbot, tmp_path):
    taken = []
    watch = FunTimeWatch(tmp_path, take_over=taken.append, showing_on=lambda: "portrait")

    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    assert _marked(tmp_path) is None
    del watch


def test_a_preview_marks_its_slideshow_in_the_everyday_copy_s_state_too(tmp_path):
    preview, everyday = _preview_and_production(tmp_path)

    watch = FunTimeWatch(preview, take_over=lambda session: None,
                         showing_on=lambda: "landscape", library_state_dir=everyday)

    assert _marked(everyday) == _marked(preview) == [
        str(os.getpid()), str(handoff.this_process().created_at), "landscape"]
    watch.withdraw()
