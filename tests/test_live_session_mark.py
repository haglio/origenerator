from __future__ import annotations

import uuid

from app_support import live_session, win32

from origenerator import live_session_mark


def test_the_trainers_ask_for_the_very_mark_every_production_funestra_holds():
    assert live_session_mark.LIVE_SESSION == live_session.LIVE_SESSION


def test_a_held_mark_reads_as_a_funestra_playing_and_a_free_one_as_none(monkeypatch):
    name = f"Local\\origenerator-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(live_session_mark, "LIVE_SESSION", name)
    held = win32.share_mutex(name)
    try:
        while_held = live_session_mark.is_live()
    finally:
        win32.release_mutex(held)

    assert (while_held, live_session_mark.is_live()) == (True, False)
