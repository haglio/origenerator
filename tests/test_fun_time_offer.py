from __future__ import annotations

import json
import os

from origenerator.fun_time_mode import Rect
from origenerator.gui.fun_time_offer import FunTimeOffer
from origenerator.win32 import this_process_creation_time


def _takeover(state_dir, *, pid):
    (state_dir / "fun_time_takeover.json").write_text(json.dumps({
        "pid": pid,
        "args": ["--fun-time", "--x", "0", "--y", "206", "--width", "853", "--height", "1234"],
    }), encoding="utf-8")


def test_an_open_app_offers_itself_to_a_session_by_its_process(tmp_path):
    offer = FunTimeOffer(tmp_path, take_over=lambda session: None)

    assert (tmp_path / "fun_time_offer.txt").read_text(encoding="utf-8").split() == [
        str(os.getpid()), str(this_process_creation_time())]
    offer.withdraw()


def test_a_takeover_for_this_app_hands_it_the_session_and_withdraws_the_offer(qtbot, tmp_path):
    taken = []
    offer = FunTimeOffer(tmp_path, take_over=taken.append)

    _takeover(tmp_path, pid=os.getpid())
    qtbot.waitUntil(lambda: bool(taken))

    assert [session.main_rect for session in taken] == [Rect(0, 206, 853, 1234)]
    assert not (tmp_path / "fun_time_offer.txt").exists()
    _takeover(tmp_path, pid=os.getpid())
    qtbot.wait(600)
    assert len(taken) == 1
    assert (tmp_path / "fun_time_takeover.json").exists()
    del offer
